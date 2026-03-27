from __future__ import annotations

from pathlib import Path
from typing import Callable

from aigc_records import ROOT_DIR, update_round
from chunking import DEFAULT_CHUNK_LIMIT, build_manifest, restore_text_from_chunks, save_manifest


PROMPTS = {
    1: "prompts/baibaiAIGC1.md",
    2: "prompts/baibaiAIGC2.md",
    3: "prompts/baibaiAIGC3.md",
}


Transform = Callable[[str, str, int, str], str]


def normalize_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


def relative_to_root(path: Path) -> str:
    normalized = normalize_path(path)
    return str(normalized.relative_to(ROOT_DIR)).replace("\\", "/")


def load_prompt(round_number: int) -> str:
    prompt_path = ROOT_DIR / PROMPTS[round_number]
    return prompt_path.read_text(encoding="utf-8")


def build_prompt_input(prompt_text: str, chunk_text: str, round_number: int, chunk_id: str) -> str:
    return (
        f"[ROUND {round_number}]\n"
        f"[CHUNK {chunk_id}]\n\n"
        f"{prompt_text.strip()}\n\n"
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
    chunk_limit: int = DEFAULT_CHUNK_LIMIT,
    score_total: int | None = None,
) -> dict:
    normalized_input_path = normalize_path(input_path)
    normalized_output_path = normalize_path(output_path)
    normalized_manifest_path = normalize_path(manifest_path)

    text = normalized_input_path.read_text(encoding="utf-8")
    manifest = build_manifest(text, chunk_limit=chunk_limit)
    save_manifest(manifest, normalized_manifest_path)

    prompt_text = load_prompt(round_number)
    chunk_outputs = {
        chunk.chunk_id: transform(
            chunk.text,
            build_prompt_input(prompt_text, chunk.text, round_number, chunk.chunk_id),
            round_number,
            chunk.chunk_id,
        )
        for chunk in manifest.chunks
    }
    restored = restore_text_from_chunks(manifest, chunk_outputs)

    normalized_output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_output_path.write_text(restored, encoding="utf-8")

    doc_entry = update_round(
        doc_id=doc_id,
        round_number=round_number,
        prompt=PROMPTS[round_number],
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
