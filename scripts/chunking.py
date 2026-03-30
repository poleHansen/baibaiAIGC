from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


DEFAULT_CHUNK_LIMIT = 850
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？；!?;])")
ENGLISH_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?;:])\s+")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b")
ChunkMetric = Literal["char", "word"]


@dataclass
class Chunk:
    chunk_id: str
    paragraph_index: int
    chunk_index: int
    text: str
    char_count: int
    word_count: int


@dataclass
class ParagraphManifest:
    paragraph_index: int
    original_text: str
    chunk_ids: list[str]


@dataclass
class ChunkManifest:
    chunk_limit: int
    chunk_metric: ChunkMetric
    paragraph_count: int
    chunk_count: int
    paragraphs: list[ParagraphManifest]
    chunks: list[Chunk]

    def to_dict(self) -> dict:
        return {
            "chunk_limit": self.chunk_limit,
            "chunk_metric": self.chunk_metric,
            "paragraph_count": self.paragraph_count,
            "chunk_count": self.chunk_count,
            "paragraphs": [asdict(paragraph) for paragraph in self.paragraphs],
            "chunks": [asdict(chunk) for chunk in self.chunks],
        }


def split_text_to_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append("\n".join(current).strip())
    return paragraphs


def split_paragraph_to_chunks(paragraph: str, chunk_limit: int, chunk_metric: ChunkMetric = "char") -> list[str]:
    compact = re.sub(r"\s+", " ", paragraph).strip()
    if not compact:
        return []
    if _measure_chunk(compact, chunk_metric) <= chunk_limit:
        return [compact]

    sentences = _split_into_sentences(compact, chunk_metric)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if _measure_chunk(sentence, chunk_metric) > chunk_limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_sentence(sentence, chunk_limit, chunk_metric))
            continue

        candidate = sentence if not current else _join_fragments(current, sentence, chunk_metric)
        if _measure_chunk(candidate, chunk_metric) <= chunk_limit:
            current = candidate
            continue

        chunks.append(current)
        current = sentence

    if current:
        chunks.append(current)
    return chunks


def build_manifest(text: str, chunk_limit: int = DEFAULT_CHUNK_LIMIT, chunk_metric: ChunkMetric = "char") -> ChunkManifest:
    paragraphs = split_text_to_paragraphs(text)
    manifest_paragraphs: list[ParagraphManifest] = []
    manifest_chunks: list[Chunk] = []

    for paragraph_index, paragraph in enumerate(paragraphs):
        chunk_texts = split_paragraph_to_chunks(paragraph, chunk_limit, chunk_metric=chunk_metric)
        chunk_ids: list[str] = []
        for chunk_index, chunk_text in enumerate(chunk_texts):
            chunk_id = f"p{paragraph_index}_c{chunk_index}"
            chunk_ids.append(chunk_id)
            manifest_chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    paragraph_index=paragraph_index,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    word_count=count_words(chunk_text),
                )
            )
        manifest_paragraphs.append(
            ParagraphManifest(
                paragraph_index=paragraph_index,
                original_text=paragraph,
                chunk_ids=chunk_ids,
            )
        )

    return ChunkManifest(
        chunk_limit=chunk_limit,
        chunk_metric=chunk_metric,
        paragraph_count=len(manifest_paragraphs),
        chunk_count=len(manifest_chunks),
        paragraphs=manifest_paragraphs,
        chunks=manifest_chunks,
    )


def restore_text_from_chunks(manifest: ChunkManifest, chunk_results: dict[str, str]) -> str:
    restored_paragraphs: list[str] = []
    for paragraph in manifest.paragraphs:
        parts = [chunk_results[chunk_id].strip() for chunk_id in paragraph.chunk_ids]
        restored_paragraphs.append("".join(part for part in parts if part))
    return "\n\n".join(restored_paragraphs)


def save_manifest(manifest: ChunkManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(path: Path) -> ChunkManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ChunkManifest(
        chunk_limit=int(data["chunk_limit"]),
        chunk_metric=str(data.get("chunk_metric", "char")),
        paragraph_count=int(data["paragraph_count"]),
        chunk_count=int(data["chunk_count"]),
        paragraphs=[ParagraphManifest(**paragraph) for paragraph in data["paragraphs"]],
        chunks=[Chunk(**chunk) for chunk in data["chunks"]],
    )


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def _measure_chunk(text: str, chunk_metric: ChunkMetric) -> int:
    if chunk_metric == "word":
        return count_words(text)
    return len(text)


def _join_fragments(left: str, right: str, chunk_metric: ChunkMetric) -> str:
    if chunk_metric == "word":
      return f"{left} {right}".strip()
    return f"{left}{right}"


def _split_into_sentences(text: str, chunk_metric: ChunkMetric) -> list[str]:
    pieces = ENGLISH_SENTENCE_BOUNDARY_RE.split(text) if chunk_metric == "word" else SENTENCE_BOUNDARY_RE.split(text)
    sentences = [piece.strip() for piece in pieces if piece and piece.strip()]
    return sentences or [text]


def _split_long_sentence(sentence: str, chunk_limit: int, chunk_metric: ChunkMetric) -> list[str]:
    fragments = re.split(r"(?<=[，、：:,])|(?<=[,;:])\s+", sentence)
    chunks: list[str] = []
    current = ""
    for fragment in fragments:
        fragment = fragment.strip()
        if not fragment:
            continue
        candidate = fragment if not current else _join_fragments(current, fragment, chunk_metric)
        if _measure_chunk(candidate, chunk_metric) <= chunk_limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if _measure_chunk(fragment, chunk_metric) <= chunk_limit:
            current = fragment
            continue
        chunks.extend(_split_oversized_fragment(fragment, chunk_limit, chunk_metric))
    if current:
        chunks.append(current)
    return chunks


def _split_oversized_fragment(fragment: str, chunk_limit: int, chunk_metric: ChunkMetric) -> list[str]:
    if chunk_metric == "word":
        words = fragment.split()
        chunks: list[str] = []
        current_words: list[str] = []
        for word in words:
            candidate_words = [*current_words, word]
            if len(candidate_words) <= chunk_limit:
                current_words = candidate_words
                continue
            if current_words:
                chunks.append(" ".join(current_words))
            current_words = [word]
        if current_words:
            chunks.append(" ".join(current_words))
        return chunks

    return [fragment[index:index + chunk_limit] for index in range(0, len(fragment), chunk_limit)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Chunk paper text by paragraph and sentence boundaries")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a chunk manifest from a text file")
    build_parser.add_argument("input", type=Path)
    build_parser.add_argument("output", type=Path)
    build_parser.add_argument("--chunk-limit", type=int, default=DEFAULT_CHUNK_LIMIT)
    build_parser.add_argument("--chunk-metric", choices=["char", "word"], default="char")

    args = parser.parse_args(argv)

    if args.command == "build":
        text = args.input.read_text(encoding="utf-8")
        manifest = build_manifest(text, chunk_limit=args.chunk_limit, chunk_metric=args.chunk_metric)
        save_manifest(manifest, args.output)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
