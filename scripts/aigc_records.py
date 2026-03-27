"""Utility helpers for reading and writing AIGC reduction records.

This module maintains a JSON file under the workspace root `finish/` directory,
by default called `aigc_records.json`.

The JSON structure is intentionally simple and stable so that other tools
or workflows can rely on it:

{
  "origin/毕业论文_原始_utf8.txt": {
    "origin_path": "origin/毕业论文_原始_utf8.txt",
    "rounds": [
      {
        "round": 1,
        "prompt": "prompts/baibaiAIGC1.md",
        "input_path": "origin/毕业论文_原始_utf8.txt",
        "output_path": "finish/intermediate/毕业论文_原始_utf8_round1.txt",
        "score_total": 38,
        "timestamp": "2026-03-27T10:01:23Z"
      }
    ]
  }
}

- The top-level keys are logical document identifiers, typically the
  relative path of the source file under `origin/`.
- Each document entry stores the original path and an ordered list of
  completed rounds (1, 2, 3).
- Each round records which prompt was used, which file was the input,
  which file is the output, an optional checklist total score, and a
  timestamp in ISO 8601 format.

You can import this module from other Python code, or use the CLI:

  python scripts/aigc_records.py show                # show all records
  python scripts/aigc_records.py show origin/xxx.txt # show one document
  python scripts/aigc_records.py update-round \
      origin/xxx.txt 1 prompts/baibaiAIGC1.md \
      origin/xxx.txt finish/intermediate/xxx_round1.txt \
      --score-total 38

The baibaiaigc skill should conceptually perform the same operations as
`update-round` whenever it finishes a single reduction round.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Paths are computed relative to this file: scripts/ -> workspace root.
ROOT_DIR = Path(__file__).resolve().parents[1]
FINISH_DIR = ROOT_DIR / "finish"
RECORDS_PATH = FINISH_DIR / "aigc_records.json"


@dataclass
class RoundRecord:
    """Single reduction round metadata for one document."""

    round: int
    prompt: str
    input_path: str
    output_path: str
    score_total: Optional[int] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = asdict(self)
        # Drop empty timestamp / None score to keep JSON clean.
        if not data.get("timestamp"):
            data.pop("timestamp", None)
        if data.get("score_total") is None:
            data.pop("score_total", None)
        return data


def _ensure_finish_dir() -> None:
    FINISH_DIR.mkdir(parents=True, exist_ok=True)


def load_records() -> Dict[str, Any]:
    """Load all AIGC records from the JSON file.

    Returns an empty dict if the file does not exist or is empty.
    """

    if not RECORDS_PATH.exists():
        return {}
    try:
        raw = RECORDS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # If the JSON is corrupted, return empty instead of crashing.
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_records(records: Dict[str, Any]) -> None:
    """Persist the records dictionary back to disk as JSON."""

    _ensure_finish_dir()
    text = json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True)
    RECORDS_PATH.write_text(text, encoding="utf-8")


def update_round(
    doc_id: str,
    round_number: int,
    prompt: str,
    input_path: str,
    output_path: str,
    score_total: Optional[int] = None,
) -> Dict[str, Any]:
    """Update (or create) the record for a single document round.

    If a record for the same document and round already exists, it will be
    replaced. Otherwise it will be appended to the rounds list.

    Returns the updated document record.
    """

    records = load_records()

    doc_entry = records.get(doc_id)
    if not isinstance(doc_entry, dict):
        doc_entry = {"origin_path": doc_id, "rounds": []}

    rounds = doc_entry.get("rounds")
    if not isinstance(rounds, list):
        rounds = []

    # Remove any existing entry for this round, to make updates idempotent.
    filtered_rounds: List[Dict[str, Any]] = [
        r for r in rounds if not isinstance(r, dict) or r.get("round") != round_number
    ]

    record = RoundRecord(
        round=round_number,
        prompt=prompt,
        input_path=input_path,
        output_path=output_path,
        score_total=score_total,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    filtered_rounds.append(record.to_dict())
    # Keep rounds sorted by round number for readability.
    filtered_rounds.sort(key=lambda r: r.get("round", 0))

    doc_entry["origin_path"] = doc_id
    doc_entry["rounds"] = filtered_rounds
    records[doc_id] = doc_entry

    save_records(records)
    return doc_entry


def show_records(doc_id: Optional[str] = None) -> None:
    """Print all records, or the record for a single document.

    Output is raw JSON on stdout so it can be piped or inspected easily.
    """

    records = load_records()
    if doc_id is not None:
        payload: Any = records.get(doc_id, {})
    else:
        payload = records
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage AIGC reduction records in finish/aigc_records.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser(
        "show", help="Show all records or a single document",
    )
    show_parser.add_argument(
        "doc_id",
        nargs="?",
        help="Document identifier (e.g. origin/xxx.txt). If omitted, show all records.",
    )

    update_parser = subparsers.add_parser(
        "update-round", help="Create or update a single document round record",
    )
    update_parser.add_argument(
        "doc_id",
        help="Document identifier, typically the origin/ relative path.",
    )
    update_parser.add_argument(
        "round",
        type=int,
        help="Round number (1, 2, or 3).",
    )
    update_parser.add_argument(
        "prompt",
        help="Prompt file path used for this round (e.g. prompts/baibaiAIGC1.md).",
    )
    update_parser.add_argument(
        "input_path",
        help="Input text file path for this round.",
    )
    update_parser.add_argument(
        "output_path",
        help="Output text file path for this round.",
    )
    update_parser.add_argument(
        "--score-total",
        type=int,
        default=None,
        help="Optional checklist total score for this round.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "show":
        show_records(args.doc_id)
    elif args.command == "update-round":
        doc_entry = update_round(
            doc_id=args.doc_id,
            round_number=args.round,
            prompt=args.prompt,
            input_path=args.input_path,
            output_path=args.output_path,
            score_total=args.score_total,
        )
        text = json.dumps(doc_entry, ensure_ascii=False, indent=2, sort_keys=True)
        print(text)
    else:  # pragma: no cover - argparse guarantees command
        parser.error("Unknown command")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
