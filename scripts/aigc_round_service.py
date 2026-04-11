from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aigc_records import ROOT_DIR, update_round
from chunking import DEFAULT_CHUNK_LIMIT, build_manifest, restore_text_from_chunks, save_manifest


PROMPT_PROFILES = {
    "cn": {
        1: "prompts/baibaiAIGC1.md",
        2: "prompts/baibaiAIGC2.md",
    },
    "en": {
        1: "prompts/baibaiaigc-en.md",
    },
}

PROMPT_PROFILE_CHUNK_METRICS = {
    "cn": "char",
    "en": "word",
}

MAX_ROUNDS = max(max(rounds) for rounds in PROMPT_PROFILES.values())


Transform = Callable[[str, str, int, str], str]
ProgressCallback = Callable[[dict[str, object]], None]


class CancelledError(Exception):
    """Raised when a run_round operation is cancelled via cancel_event."""


SHARED_OUTPUT_CONTRACT = """
[OUTPUT CONTRACT]
- Only return the rewritten body text for the current input chunk.
- Preserve the original meaning, facts, claims, conclusions, numbering, and paragraph role.
- Do not add, remove, or replace viewpoints or conclusions.
- Do not output explanations, suggestions, options, comments, invitations, or summaries.
- Do not output phrases like: 修改后：, 改写后：, 可以改成, 如果你愿意, 说明：, 原因很简单, 我也可以继续帮你.
- Do not turn the text into chat, Q&A, title suggestions, bullet recommendations, or markdown formatting unless the input already contains it.
""".strip()

DISALLOWED_OUTPUT_PATTERNS = (
    "如果你愿意",
    "可以改成",
    "改写后：",
    "修改后：",
    "说明：",
    "原因很简单",
    "我也可以继续帮你",
    "请把需要",
    "你可以直接贴",
)


def validate_chunk_output(input_text: str, output_text: str, chunk_id: str) -> None:
    normalized_output = output_text.strip()
    if not normalized_output:
        raise ValueError(f"Chunk {chunk_id} returned empty output")

    for pattern in DISALLOWED_OUTPUT_PATTERNS:
        if pattern in normalized_output:
            raise ValueError(f"Chunk {chunk_id} contains disallowed answer-style pattern: {pattern}")

    markdown_markers = ("**", "### ", "## ", "- **", "> ")
    if any(marker in normalized_output for marker in markdown_markers) and not any(marker in input_text for marker in markdown_markers):
        raise ValueError(f"Chunk {chunk_id} introduced markdown-style formatting")

    if len(normalized_output) > max(len(input_text) * 2, len(input_text) + 200):
        raise ValueError(f"Chunk {chunk_id} expanded abnormally; possible answer-style drift")


def normalize_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


def relative_to_root(path: Path) -> str:
    normalized = normalize_path(path)
    try:
        relative = normalized.relative_to(ROOT_DIR)
        return str(relative).replace("\\", "/")
    except ValueError:
        return str(normalized)


def normalize_prompt_profile(prompt_profile: str | None) -> str:
    normalized = str(prompt_profile or "cn").strip().lower()
    if normalized not in PROMPT_PROFILES:
        raise ValueError(f"Unsupported prompt profile: {normalized}")
    return normalized


def get_prompt_mapping(prompt_profile: str | None) -> dict[int, str]:
    normalized_profile = normalize_prompt_profile(prompt_profile)
    return PROMPT_PROFILES[normalized_profile]


def get_max_rounds(prompt_profile: str | None) -> int:
    return max(get_prompt_mapping(prompt_profile))


def get_chunk_metric(prompt_profile: str | None) -> str:
    normalized_profile = normalize_prompt_profile(prompt_profile)
    return PROMPT_PROFILE_CHUNK_METRICS[normalized_profile]


def load_prompt(prompt_profile: str | None, round_number: int) -> str:
    prompts = get_prompt_mapping(prompt_profile)
    if round_number not in prompts:
        raise ValueError(
            f"Round {round_number} is not available for prompt profile {normalize_prompt_profile(prompt_profile)}. "
            f"Supported rounds: {sorted(prompts)}"
        )
    prompt_path = ROOT_DIR / prompts[round_number]
    return prompt_path.read_text(encoding="utf-8")


def build_prompt_input(prompt_text: str, chunk_text: str, round_number: int, chunk_id: str) -> str:
    return (
        f"[ROUND {round_number}]\n"
        f"[CHUNK {chunk_id}]\n\n"
        f"{prompt_text.strip()}\n\n"
        f"{SHARED_OUTPUT_CONTRACT}\n\n"
        "[INPUT TEXT]\n"
        f"{chunk_text}"
    )


# ---------------------------------------------------------------------------
# Checkpoint helpers — persist completed chunk results only on error
# ---------------------------------------------------------------------------

def _checkpoint_path(manifest_path: Path) -> Path:
    """Derive a checkpoint file path from the manifest path."""
    return manifest_path.with_name(
        manifest_path.name.replace("_manifest.json", "_checkpoint.json")
    )


def _load_checkpoint(
    path: Path,
    expected_total: int,
) -> dict[str, str]:
    """Load a checkpoint file if it exists and matches the expected chunk count.

    Returns a dict mapping chunk_id -> completed output text.
    Returns an empty dict if the checkpoint is missing, corrupt, or stale.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if int(data.get("total_chunks", -1)) != expected_total:
        # Input changed since last checkpoint — discard.
        return {}
    completed = data.get("completed_chunks", {})
    if not isinstance(completed, dict):
        return {}
    return {str(k): str(v) for k, v in completed.items()}


def _save_checkpoint(
    path: Path,
    *,
    doc_id: str,
    round_number: int,
    total_chunks: int,
    chunk_outputs: dict[str, str],
    error_message: str,
    failed_chunk_id: str | None,
) -> None:
    """Persist in-memory chunk results to a checkpoint file on error."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "round": round_number,
        "total_chunks": total_chunks,
        "completed_chunks": chunk_outputs,
        "completed_count": len(chunk_outputs),
        "error_message": error_message,
        "failed_chunk_id": failed_chunk_id,
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_checkpoint(path: Path) -> None:
    """Remove a checkpoint or partial output file if it exists."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _partial_output_path(output_path: Path) -> Path:
    """Derive a partial output .txt path from the final output path.

    Example: xxx_round1.txt -> xxx_round1_partial.txt
    """
    return output_path.with_name(
        output_path.stem + "_partial" + output_path.suffix
    )


def run_round(
    doc_id: str,
    round_number: int,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    transform: Transform,
    prompt_profile: str = "cn",
    chunk_limit: int = DEFAULT_CHUNK_LIMIT,
    score_total: int | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    normalized_input_path = normalize_path(input_path)
    normalized_output_path = normalize_path(output_path)
    normalized_manifest_path = normalize_path(manifest_path)
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    chunk_metric = get_chunk_metric(normalized_prompt_profile)

    text = normalized_input_path.read_text(encoding="utf-8")
    manifest = build_manifest(text, chunk_limit=chunk_limit, chunk_metric=chunk_metric)
    save_manifest(manifest, normalized_manifest_path)

    # --- Checkpoint: attempt to resume from a previous failed run ---
    ckpt_path = _checkpoint_path(normalized_manifest_path)
    resumed_chunks = _load_checkpoint(ckpt_path, expected_total=manifest.chunk_count)
    resumed_count = len(resumed_chunks)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "chunking-ready",
                "round": round_number,
                "totalChunks": manifest.chunk_count,
                "paragraphCount": manifest.paragraph_count,
                "inputPath": str(normalized_input_path),
                "outputPath": str(normalized_output_path),
                "resumedChunks": resumed_count,
            }
        )

    prompts = get_prompt_mapping(normalized_prompt_profile)
    prompt_text = load_prompt(normalized_prompt_profile, round_number)
    chunk_outputs: dict[str, str] = dict(resumed_chunks)
    failed_chunk_id: str | None = None

    try:
        for index, chunk in enumerate(manifest.chunks, start=1):
            # Skip chunks already completed in a previous (failed) run.
            if chunk.chunk_id in chunk_outputs:
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "chunk-resumed",
                            "round": round_number,
                            "currentChunk": index,
                            "totalChunks": manifest.chunk_count,
                            "chunkId": chunk.chunk_id,
                        }
                    )
                continue

            # Check for cancellation before processing each chunk.
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError(
                    f"Operation cancelled before chunk {chunk.chunk_id} "
                    f"({len(chunk_outputs)}/{manifest.chunk_count} chunks completed)"
                )

            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "processing-chunk",
                        "round": round_number,
                        "currentChunk": index,
                        "totalChunks": manifest.chunk_count,
                        "chunkId": chunk.chunk_id,
                        "paragraphIndex": chunk.paragraph_index,
                        "chunkIndex": chunk.chunk_index,
                    }
                )

            failed_chunk_id = chunk.chunk_id
            chunk_output = transform(
                chunk.text,
                build_prompt_input(prompt_text, chunk.text, round_number, chunk.chunk_id),
                round_number,
                chunk.chunk_id,
            )
            validate_chunk_output(chunk.text, chunk_output, chunk.chunk_id)
            chunk_outputs[chunk.chunk_id] = chunk_output
            failed_chunk_id = None

            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "chunk-complete",
                        "round": round_number,
                        "currentChunk": index,
                        "totalChunks": manifest.chunk_count,
                        "chunkId": chunk.chunk_id,
                    }
                )
    except Exception as exc:
        # --- Checkpoint: persist completed chunks on error ---
        partial_txt_path = _partial_output_path(normalized_output_path)
        if chunk_outputs:
            _save_checkpoint(
                ckpt_path,
                doc_id=doc_id,
                round_number=round_number,
                total_chunks=manifest.chunk_count,
                chunk_outputs=chunk_outputs,
                error_message=str(exc),
                failed_chunk_id=failed_chunk_id,
            )
            # Also write a partial .txt: completed chunks use AI result,
            # uncompleted chunks fall back to original input text.
            merged = {}
            for chunk in manifest.chunks:
                if chunk.chunk_id in chunk_outputs:
                    merged[chunk.chunk_id] = chunk_outputs[chunk.chunk_id]
                else:
                    merged[chunk.chunk_id] = chunk.text
            partial_text = restore_text_from_chunks(manifest, merged)
            partial_txt_path.parent.mkdir(parents=True, exist_ok=True)
            partial_txt_path.write_text(partial_text, encoding="utf-8")

        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "error-checkpoint-saved",
                    "round": round_number,
                    "completedChunks": len(chunk_outputs),
                    "totalChunks": manifest.chunk_count,
                    "failedChunkId": failed_chunk_id,
                    "checkpointPath": str(ckpt_path),
                    "partialOutputPath": str(partial_txt_path),
                    "errorMessage": str(exc),
                }
            )
        raise

    # --- All chunks done: clean up checkpoint + partial output ---
    _delete_checkpoint(ckpt_path)
    _delete_checkpoint(_partial_output_path(normalized_output_path))

    restored = restore_text_from_chunks(manifest, chunk_outputs)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "restoring-output",
                "round": round_number,
                "totalChunks": manifest.chunk_count,
            }
        )

    normalized_output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_output_path.write_text(restored, encoding="utf-8")

    doc_entry = update_round(
        doc_id=doc_id,
        round_number=round_number,
        prompt=prompts[round_number],
        prompt_profile=normalized_prompt_profile,
        input_path=relative_to_root(normalized_input_path),
        output_path=relative_to_root(normalized_output_path),
        score_total=score_total,
        chunk_limit=chunk_limit,
        input_segment_count=manifest.chunk_count,
        output_segment_count=len(chunk_outputs),
        manifest_path=relative_to_root(normalized_manifest_path),
    )

    return {
        "doc_entry": doc_entry,
        "round": round_number,
        "output_path": str(normalized_output_path),
        "manifest_path": str(normalized_manifest_path),
        "chunk_limit": chunk_limit,
        "input_segment_count": manifest.chunk_count,
        "output_segment_count": len(chunk_outputs),
        "paragraph_count": manifest.paragraph_count,
        "resumed_chunks": resumed_count,
    }
