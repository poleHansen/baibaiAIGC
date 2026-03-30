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
    completed rounds (1, 2).
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
    prompt_profile: str = "cn"
    score_total: Optional[int] = None
    chunk_limit: Optional[int] = None
    input_segment_count: Optional[int] = None
    output_segment_count: Optional[int] = None
    manifest_path: Optional[str] = None
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


def normalize_record_path(path: str) -> str:
    candidate = str(path or "").strip().replace("\\", "/")
    while "//" in candidate:
        candidate = candidate.replace("//", "/")
    return candidate


def normalize_doc_id(doc_id: str) -> str:
    return normalize_record_path(doc_id)


def normalize_records(records: Dict[str, Any]) -> Dict[str, Any]:
    normalized_records: Dict[str, Any] = {}

    for raw_key, raw_entry in records.items():
        if not isinstance(raw_entry, dict):
            continue

        normalized_key = normalize_doc_id(str(raw_key))
        if not normalized_key:
            continue

        target_entry = normalized_records.setdefault(
            normalized_key,
            {"origin_path": normalized_key, "rounds": []},
        )
        target_rounds = target_entry.get("rounds")
        if not isinstance(target_rounds, list):
            target_rounds = []

        merged_by_round: Dict[int, Dict[str, Any]] = {
            int(item.get("round")): item
            for item in target_rounds
            if isinstance(item, dict) and isinstance(item.get("round"), int)
        }

        incoming_rounds = raw_entry.get("rounds")
        if not isinstance(incoming_rounds, list):
            incoming_rounds = []

        for item in incoming_rounds:
            if not isinstance(item, dict):
                continue
            round_number = item.get("round")
            if not isinstance(round_number, int):
                continue
            normalized_item = dict(item)
            for field in ("prompt", "input_path", "output_path", "manifest_path"):
                value = normalized_item.get(field)
                if isinstance(value, str):
                    normalized_item[field] = normalize_record_path(value)
            prompt_profile = str(normalized_item.get("prompt_profile", "cn") or "cn").strip().lower()
            normalized_item["prompt_profile"] = prompt_profile if prompt_profile in {"cn", "en"} else "cn"
            merged_by_round[round_number] = normalized_item

        target_entry["origin_path"] = normalize_record_path(str(raw_entry.get("origin_path", normalized_key))) or normalized_key
        target_entry["rounds"] = [merged_by_round[key] for key in sorted(merged_by_round)]

    return normalized_records


def load_records_normalized() -> Dict[str, Any]:
    raw_records = load_records()
    normalized_records = normalize_records(raw_records)
    if normalized_records != raw_records:
        save_records(normalized_records)
    return normalized_records


def _record_path_to_absolute(path: str) -> Optional[Path]:
    normalized = normalize_record_path(path)
    if not normalized:
        return None
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate.resolve()


def _collect_round_file_paths(rounds: List[Dict[str, Any]]) -> set[Path]:
    collected: set[Path] = set()
    for item in rounds:
        if not isinstance(item, dict):
            continue
        for field in ("input_path", "output_path", "manifest_path"):
            value = item.get(field)
            if not isinstance(value, str):
                continue
            absolute = _record_path_to_absolute(value)
            if absolute is not None:
                collected.add(absolute)
    return collected


def _is_safe_generated_artifact(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT_DIR)
    except ValueError:
        return False

    relative_parts = relative.parts
    if not relative_parts:
        return False

    if relative_parts[0] != "finish":
        return False

    if len(relative_parts) < 2:
        return False

    return relative_parts[1] in {"intermediate", "web_exports"}


def _delete_artifacts_for_removed_rounds(
    deleted_rounds: List[Dict[str, Any]],
    retained_rounds: List[Dict[str, Any]],
) -> List[str]:
    retained_paths = _collect_round_file_paths(retained_rounds)
    deleted_paths = _collect_round_file_paths(deleted_rounds)
    removed_paths: List[str] = []

    for candidate in sorted(deleted_paths):
        if candidate in retained_paths:
            continue
        if not _is_safe_generated_artifact(candidate):
            continue
        if not candidate.exists() or not candidate.is_file():
            continue
        candidate.unlink()
        removed_paths.append(str(candidate.relative_to(ROOT_DIR)).replace("\\", "/"))

    return removed_paths


def update_round(
    doc_id: str,
    round_number: int,
    prompt: str,
    prompt_profile: str,
    input_path: str,
    output_path: str,
    score_total: Optional[int] = None,
    chunk_limit: Optional[int] = None,
    input_segment_count: Optional[int] = None,
    output_segment_count: Optional[int] = None,
    manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Update (or create) the record for a single document round.

    If a record for the same document and round already exists, it will be
    replaced. Otherwise it will be appended to the rounds list.

    Returns the updated document record.
    """

    normalized_doc_id = normalize_doc_id(doc_id)
    records = load_records_normalized()

    doc_entry = records.get(normalized_doc_id)
    if not isinstance(doc_entry, dict):
        doc_entry = {"origin_path": normalized_doc_id, "rounds": []}

    rounds = doc_entry.get("rounds")
    if not isinstance(rounds, list):
        rounds = []

    # Remove any existing entry for this round, to make updates idempotent.
    filtered_rounds: List[Dict[str, Any]] = [
        r for r in rounds if not isinstance(r, dict) or r.get("round") != round_number
    ]

    record = RoundRecord(
        round=round_number,
        prompt=normalize_record_path(prompt),
        prompt_profile=str(prompt_profile or "cn").strip().lower() or "cn",
        input_path=normalize_record_path(input_path),
        output_path=normalize_record_path(output_path),
        score_total=score_total,
        chunk_limit=chunk_limit,
        input_segment_count=input_segment_count,
        output_segment_count=output_segment_count,
        manifest_path=normalize_record_path(manifest_path) if manifest_path else None,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    filtered_rounds.append(record.to_dict())
    # Keep rounds sorted by round number for readability.
    filtered_rounds.sort(key=lambda r: r.get("round", 0))

    doc_entry["origin_path"] = normalized_doc_id
    doc_entry["rounds"] = filtered_rounds
    records[normalized_doc_id] = doc_entry

    save_records(records)
    return doc_entry


def list_records() -> Dict[str, Any]:
    return load_records_normalized()


def delete_rounds(doc_id: str, from_round: int) -> Dict[str, Any]:
    normalized_doc_id = normalize_doc_id(doc_id)
    records = load_records_normalized()
    doc_entry = records.get(normalized_doc_id)
    if not isinstance(doc_entry, dict):
        raise ValueError(f"Document record not found: {normalized_doc_id}")

    rounds = doc_entry.get("rounds")
    if not isinstance(rounds, list):
        rounds = []

    deleted_rounds = [
        item for item in rounds
        if isinstance(item, dict) and isinstance(item.get("round"), int) and item.get("round") >= from_round
    ]
    if not deleted_rounds:
        raise ValueError(f"No rounds found from round {from_round} for: {normalized_doc_id}")

    remaining_rounds = [
        item for item in rounds
        if isinstance(item, dict) and isinstance(item.get("round"), int) and item.get("round") < from_round
    ]

    if remaining_rounds:
        doc_entry["origin_path"] = normalized_doc_id
        doc_entry["rounds"] = remaining_rounds
        records[normalized_doc_id] = doc_entry
    else:
        records.pop(normalized_doc_id, None)

    save_records(records)
    removed_files = _delete_artifacts_for_removed_rounds(deleted_rounds, remaining_rounds)
    return {
        "docId": normalized_doc_id,
        "deletedRounds": [int(item["round"]) for item in deleted_rounds],
        "remainingRounds": [
            int(item["round"]) for item in remaining_rounds if isinstance(item, dict) and isinstance(item.get("round"), int)
        ],
        "removedDocument": not remaining_rounds,
        "deletedFiles": removed_files,
    }


def delete_document(doc_id: str) -> Dict[str, Any]:
    normalized_doc_id = normalize_doc_id(doc_id)
    records = load_records_normalized()
    doc_entry = records.pop(normalized_doc_id, None)
    if not isinstance(doc_entry, dict):
        raise ValueError(f"Document record not found: {normalized_doc_id}")
    save_records(records)
    rounds = doc_entry.get("rounds") if isinstance(doc_entry.get("rounds"), list) else []
    removed_files = _delete_artifacts_for_removed_rounds(
        [item for item in rounds if isinstance(item, dict)],
        [],
    )
    return {
        "docId": normalized_doc_id,
        "deletedRounds": [
            int(item["round"]) for item in rounds if isinstance(item, dict) and isinstance(item.get("round"), int)
        ],
        "remainingRounds": [],
        "removedDocument": True,
        "deletedFiles": removed_files,
    }


def show_records(doc_id: Optional[str] = None) -> None:
    """Print all records, or the record for a single document.

    Output is raw JSON on stdout so it can be piped or inspected easily.
    """

    records = load_records_normalized()
    if doc_id is not None:
        payload: Any = records.get(normalize_doc_id(doc_id), {})
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

    delete_parser = subparsers.add_parser(
        "delete-document", help="Delete a whole document record",
    )
    delete_parser.add_argument("doc_id", help="Document identifier to delete.")

    rollback_parser = subparsers.add_parser(
        "delete-rounds", help="Delete one round and all later rounds for a document",
    )
    rollback_parser.add_argument("doc_id", help="Document identifier to modify.")
    rollback_parser.add_argument("from_round", type=int, help="Delete this round and later rounds.")

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
        "--prompt-profile",
        default="cn",
        choices=["cn", "en"],
        help="Prompt profile for this round: cn=中文两轮, en=英文单轮.",
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
    update_parser.add_argument(
        "--chunk-limit",
        type=int,
        default=None,
        help="Optional per-chunk character limit used in this round.",
    )
    update_parser.add_argument(
        "--input-segment-count",
        type=int,
        default=None,
        help="Optional number of chunks produced from the input text.",
    )
    update_parser.add_argument(
        "--output-segment-count",
        type=int,
        default=None,
        help="Optional number of chunk outputs written back into the restored text.",
    )
    update_parser.add_argument(
        "--manifest-path",
        default=None,
        help="Optional path to the chunk manifest json for this round.",
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
            prompt_profile=args.prompt_profile,
            input_path=args.input_path,
            output_path=args.output_path,
            score_total=args.score_total,
            chunk_limit=args.chunk_limit,
            input_segment_count=args.input_segment_count,
            output_segment_count=args.output_segment_count,
            manifest_path=args.manifest_path,
        )
        text = json.dumps(doc_entry, ensure_ascii=False, indent=2, sort_keys=True)
        print(text)
    elif args.command == "delete-document":
        payload = delete_document(args.doc_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.command == "delete-rounds":
        payload = delete_rounds(args.doc_id, args.from_round)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:  # pragma: no cover - argparse guarantees command
        parser.error("Unknown command")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
