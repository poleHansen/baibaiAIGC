"""Deai (降AIGC / de-AI-flavor) API server.

Exposes a simple HTTP API for the two-round AIGC reduction pipeline
built on baibaiAIGC's existing scripts.  Designed to run as a
standalone Docker service in a docker-compose stack.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

# ---------------------------------------------------------------------------
# Bootstrap: make the scripts/ directory importable
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from markdown_chunks import detect_markdown_blocks, process_text_blocks  # noqa: E402
from aigc_round_service import run_round  # noqa: E402
from llm_client import llm_completion, read_api_config  # noqa: E402
from app_config import get_app_config_path, load_app_config  # noqa: E402

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_api_config(payload: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve API credentials with fallback chain.

    Priority order:
    1. Request body parameters (``payload``)
    2. Environment variables (handled by :func:`read_api_config`)
    3. ``~/.baibaiaigc/config.json`` via :func:`load_app_config`
       (maps ``baseUrl`` / ``apiKey`` / ``model`` / ``apiType``)
    """
    api_key = payload.get("api_key") or payload.get("apiKey")
    model = payload.get("model")
    base_url = payload.get("base_url") or payload.get("baseUrl")
    api_type = payload.get("api_type") or payload.get("apiType")

    api_key, model, base_url, api_type = read_api_config(api_key, model, base_url, api_type)

    if not (api_key and model and base_url) and get_app_config_path().exists():
        try:
            cfg = load_app_config()
        except Exception:
            cfg = {}
        api_key = api_key or (cfg.get("apiKey") or None)
        model = model or (cfg.get("model") or None)
        base_url = base_url or (cfg.get("baseUrl") or None)
        api_type = api_type or (cfg.get("apiType") or None)

    return api_key, model, base_url, api_type


def _build_transform(
    api_key: str,
    model: str,
    base_url: str,
    api_type: str | None,
    temperature: float,
    timeout: int,
):
    """Return a transform(chunk_text, prompt_input, round_number, chunk_id) -> str."""
    def transform(chunk_text: str, prompt_input: str, round_number: int, chunk_id: str) -> str:
        return llm_completion(
            prompt_input,
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_type=api_type,
            temperature=temperature,
            timeout=timeout,
        )
    return transform


def _markdown_structural_markers(text: str) -> dict[str, int]:
    """Count key Markdown structural markers in *text*."""
    return {
        "tables": len(re.findall(r"^\|", text, re.MULTILINE)),
        "images": len(re.findall(r"!\[", text)),
        "links": len(re.findall(r"(?<!\!)\[", text)),
        "code_blocks": len(re.findall(r"```", text)) // 2,
        "inline_code": len(re.findall(r"`(?![`])", text)) // 2,
        "headings": len(re.findall(r"^#{1,6}\s", text, re.MULTILINE)),
        "bold": len(re.findall(r"\*\*", text)) // 2,
        "italic": len(re.findall(r"(?<!\*)\*(?!\*)", text)) // 2,
        "list_items": len(re.findall(r"^\s*[-*+]\s", text, re.MULTILINE))
                    + len(re.findall(r"^\s*\d+\.\s", text, re.MULTILINE)),
        "blockquotes": len(re.findall(r"^>", text, re.MULTILINE)),
        "horizontal_rules": len(re.findall(r"^---+$", text, re.MULTILINE))
                           + len(re.findall(r"^\*\*\*+$", text, re.MULTILINE)),
    }


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------

def _looks_like_markdown(text: str) -> bool:
    """Quick heuristic: does *text* contain Markdown structural elements?"""
    indicators = [
        re.search(r"^\|", text, re.MULTILINE),          # tables
        re.search(r"!\[", text),                          # images
        re.search(r"^```", text, re.MULTILINE),           # code blocks
        re.search(r"^> ", text, re.MULTILINE),            # blockquotes
        re.search(r"^\s*[-*+]\s", text, re.MULTILINE),    # unordered lists
        re.search(r"^\s*\d+\.\s", text, re.MULTILINE),    # ordered lists
    ]
    return sum(1 for m in indicators if m) >= 1


def process_deai(
    content: str,
    *,
    rounds: int = 2,
    prompt_profile: str = "cn",
    api_key: str,
    model: str,
    base_url: str,
    api_type: str | None = None,
    temperature: float = 0.7,
    chunk_limit: int = 850,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the deai pipeline on *content* and return result dict.

    For Markdown content (detected by structural elements), uses block-aware
    processing that preserves tables, code blocks, lists, blockquotes, etc.
    For plain text, falls back to the standard chunking pipeline.
    """
    before_markers = _markdown_structural_markers(content)
    use_markdown_blocks = _looks_like_markdown(content)

    round_results: list[dict] = []
    current_text = content

    for round_num in range(1, rounds + 1):
        if dry_run:
            transform = lambda chunk_text, *_: chunk_text  # noqa: E731
        else:
            transform = _build_transform(
                api_key, model, base_url, api_type, temperature, timeout,
            )

        if use_markdown_blocks:
            blocks = detect_markdown_blocks(current_text)
            if dry_run:
                # In dry-run mode, just reconstruct without processing text blocks
                parts = []
                for block in blocks:
                    if block.preserved:
                        parts.append(block.text)
                    else:
                        parts.append(block.text)  # identity in dry-run
                current_text = "\n".join(parts)
                round_results.append({
                    "round": round_num,
                    "mode": "markdown_blocks_dry",
                    "blocks_total": len(blocks),
                    "preserved_blocks": sum(1 for b in blocks if b.preserved),
                })
            else:
                current_text = process_text_blocks(
                    blocks,
                    transform=transform,
                    prompt_profile=prompt_profile,
                    round_number=round_num,
                    chunk_limit=chunk_limit,
                )
                round_results.append({
                    "round": round_num,
                    "mode": "markdown_blocks",
                    "blocks_total": len(blocks),
                    "preserved_blocks": sum(1 for b in blocks if b.preserved),
                })
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                doc_id = "deai_api_input"
                input_path = tmp / "input.txt"
                output_path = tmp / f"round{round_num}.txt"
                manifest_path = tmp / f"round{round_num}_manifest.json"

                input_path.write_text(current_text, encoding="utf-8")

                result = run_round(
                    doc_id=doc_id,
                    round_number=round_num,
                    input_path=input_path,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    transform=transform,
                    prompt_profile=prompt_profile,
                    chunk_limit=chunk_limit,
                )
                round_results.append(result)
                current_text = output_path.read_text(encoding="utf-8")

    after_markers = _markdown_structural_markers(current_text)

    return {
        "content": current_text,
        "rounds_executed": rounds,
        "round_details": round_results,
        "dry_run": dry_run,
        "markdown_mode": use_markdown_blocks,
        "input_markers": before_markers,
        "output_markers": after_markers,
        "markdown_integrity": before_markers == after_markers,
        "input_length": len(content),
        "output_length": len(current_text),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health() -> Response:
    return jsonify({"status": "ok", "service": "deai"})


@app.route("/api/deai/process", methods=["POST"])
def deai_process() -> tuple[Response, int]:
    """Process text through the deai pipeline.

    Request JSON body:
    {
        "content": "...",           // required: text to process
        "rounds": 2,                // optional: 1 or 2, default 2
        "prompt_profile": "cn",     // optional: "cn" or "en", default "cn"
        "api_key": "...",           // optional (env / ~/.baibaiaigc/config.json fallback)
        "model": "...",             // optional (env / ~/.baibaiaigc/config.json fallback)
        "base_url": "...",          // optional (env / ~/.baibaiaigc/config.json fallback)
        "api_type": null,           // optional: "chat_completions" or "responses"
        "temperature": 0.7,         // optional
        "chunk_limit": 850,         // optional
        "timeout": 120,             // optional, per-chunk LLM timeout
        "dry_run": false            // optional, skip LLM for testing
    }
    """
    payload = request.get_json(silent=True)
    if not payload or "content" not in payload:
        return jsonify({"error": "content is required"}), 400

    content = payload["content"]
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "content must be a non-empty string"}), 400

    rounds = int(payload.get("rounds", 2))
    prompt_profile = payload.get("prompt_profile", "cn")
    temperature = float(payload.get("temperature", 0.7))
    chunk_limit = int(payload.get("chunk_limit", 850))
    timeout = int(payload.get("timeout", 120))
    dry_run = bool(payload.get("dry_run"))

    # en profile only supports 1 round
    if prompt_profile == "en" and rounds > 1:
        rounds = 1

    if dry_run:
        result = process_deai(
            content,
            rounds=rounds,
            prompt_profile=prompt_profile,
            api_key="",
            model="",
            base_url="",
            dry_run=True,
        )
        return jsonify(result), 200

    api_key, model, base_url, api_type = _resolve_api_config(payload)
    if not (api_key and model and base_url):
        return jsonify({
            "error": "API mode requires api_key, model, and base_url "
                     "(via request body, environment variables, or "
                     "~/.baibaiaigc/config.json). "
                     "Use dry_run=true to skip LLM calls.",
        }), 400

    try:
        result = process_deai(
            content,
            rounds=rounds,
            prompt_profile=prompt_profile,
            api_key=api_key,
            model=model,
            base_url=base_url,
            api_type=api_type,
            temperature=temperature,
            chunk_limit=chunk_limit,
            timeout=timeout,
        )
        return jsonify(result), 200
    except Exception:
        # Log the full traceback server-side but do not leak internal details
        # (stack frames, file paths, etc.) to the caller.
        app.logger.exception("deai_process failed")
        return jsonify({"error": "internal error processing deai request"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    port = int(os.environ.get("PORT", 8000))
    print(f"Deai API server starting on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
