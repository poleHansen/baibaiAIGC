from __future__ import annotations

from pathlib import Path
from typing import Callable

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
) -> dict:
    normalized_input_path = normalize_path(input_path)
    normalized_output_path = normalize_path(output_path)
    normalized_manifest_path = normalize_path(manifest_path)
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    chunk_metric = get_chunk_metric(normalized_prompt_profile)

    text = normalized_input_path.read_text(encoding="utf-8")
    manifest = build_manifest(text, chunk_limit=chunk_limit, chunk_metric=chunk_metric)
    save_manifest(manifest, normalized_manifest_path)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "chunking-ready",
                "round": round_number,
                "totalChunks": manifest.chunk_count,
                "paragraphCount": manifest.paragraph_count,
                "inputPath": str(normalized_input_path),
                "outputPath": str(normalized_output_path),
            }
        )

    prompts = get_prompt_mapping(normalized_prompt_profile)
    prompt_text = load_prompt(normalized_prompt_profile, round_number)
    chunk_outputs = {}
    for index, chunk in enumerate(manifest.chunks, start=1):
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
        chunk_output = transform(
            chunk.text,
            build_prompt_input(prompt_text, chunk.text, round_number, chunk.chunk_id),
            round_number,
            chunk.chunk_id,
        )
        validate_chunk_output(chunk.text, chunk_output, chunk.chunk_id)
        chunk_outputs[chunk.chunk_id] = chunk_output

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
    }
