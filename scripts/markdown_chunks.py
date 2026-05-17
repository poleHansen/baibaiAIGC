"""Markdown-aware chunking for the deai API.

The base chunking pipeline was designed for plain text and collapses
all whitespace, which destroys Markdown table rows, blockquote lines,
and list items.  This module preserves structural Markdown blocks
while delegating plain-text chunking to the existing pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Markdown block detection
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})\s*\w*\s*$", re.MULTILINE)
_LIST_RE = re.compile(r"(?m)(?:^[-*+]\s[^\n]*(?:\n|$))+")
_OLIST_RE = re.compile(r"(?m)(?:^\d+\.\s[^\n]*(?:\n|$))+")
_BLOCKQUOTE_RE = re.compile(r"(?m)(?:^>[^\n]*(?:\n|$))+")


@dataclass
class MarkdownBlock:
    block_type: str  # "code", "table", "list", "olist", "blockquote", "text"
    text: str
    preserved: bool  # True if block should skip LLM processing


# List item patterns (allow leading whitespace for nested items)
_UL_RE_LINE = re.compile(r"^\s+[-*+]\s")
_OL_RE_LINE = re.compile(r"^\s+\d+\.\s")
_UL_TOP_RE = re.compile(r"^[-*+]\s")
_OL_TOP_RE = re.compile(r"^\d+\.\s")
# Reference link pattern: [ref]: url "title"
# Allow word characters plus '-' in the label (CommonMark labels are broader,
# but this covers the common cases including hyphenated tags like [my-ref]).
_REF_LINK_RE = re.compile(r"^\[[\w-]+\]:\s")


def _is_list_continuation(line: str) -> bool:
    """Check if a line is a nested list item (indented -/*/+ or number.)."""
    return bool(_UL_RE_LINE.match(line) or _OL_RE_LINE.match(line))


def _is_indented_text(line: str) -> bool:
    """Indented non-blank line (a paragraph continuation inside a list item)."""
    return bool(line) and line[0] in (" ", "\t") and bool(line.strip())


def _list_resumes_after_blank(
    lines: list[str], i: int, marker_re: re.Pattern[str]
) -> int | None:
    """Look past blank lines starting at *i*.

    Returns the index of the next non-blank line if it continues the current
    list block (another list marker or an indented continuation paragraph),
    or ``None`` if the list ends. ``marker_re`` matches the top-level marker
    type of the list we are currently inside.
    """
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return None
    nl = lines[j]
    if marker_re.match(nl) or _is_list_continuation(nl) or _is_indented_text(nl):
        return j
    return None


def detect_markdown_blocks(text: str) -> list[MarkdownBlock]:
    """Split *text* into structural Markdown blocks."""
    blocks: list[MarkdownBlock] = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # --- fenced code block ---
        fence_match = re.match(r"^(`{3,}|~{3,})\s*(\w*)\s*$", line)
        if fence_match:
            fence_char = fence_match.group(1)[0]
            start = i
            i += 1
            while i < len(lines):
                if re.match(r"^" + re.escape(fence_char) + r"{3,}\s*$", lines[i]):
                    i += 1
                    break
                i += 1
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("code", block_text, preserved=True))
            continue

        # --- table ---
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-: |]+", lines[i + 1]):
            start = i
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("table", block_text, preserved=True))
            continue

        # --- blockquote ---
        if line.startswith(">"):
            start = i
            while i < len(lines) and lines[i].startswith(">"):
                i += 1
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("blockquote", block_text, preserved=True))
            continue

        # --- unordered list (top-level or nested) ---
        if _UL_TOP_RE.match(line):
            start = i
            i += 1
            while i < len(lines):
                l = lines[i]
                if _UL_TOP_RE.match(l) or _is_list_continuation(l):
                    i += 1
                    continue
                if _is_indented_text(l):
                    i += 1
                    continue
                if not l.strip():
                    resume = _list_resumes_after_blank(lines, i, _UL_TOP_RE)
                    if resume is not None:
                        i = resume
                        continue
                break
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("list", block_text, preserved=True))
            continue

        # --- ordered list (top-level or nested) ---
        if _OL_TOP_RE.match(line):
            start = i
            i += 1
            while i < len(lines):
                l = lines[i]
                if _OL_TOP_RE.match(l) or _is_list_continuation(l):
                    i += 1
                    continue
                if _is_indented_text(l):
                    i += 1
                    continue
                if not l.strip():
                    resume = _list_resumes_after_blank(lines, i, _OL_TOP_RE)
                    if resume is not None:
                        i = resume
                        continue
                break
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("olist", block_text, preserved=True))
            continue

        # --- reference-style link ---
        if _REF_LINK_RE.match(line):
            start = i
            i += 1
            block_text = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("ref_link", block_text, preserved=True))
            continue

        # --- blank line or structural element ---
        if not line.strip() or re.match(r"^[-=*]{3,}\s*$", line):
            blocks.append(MarkdownBlock("text", line, preserved=True))
            i += 1
            continue

        # --- regular text (accumulate consecutive non-blank, non-structural lines) ---
        start = i
        while i < len(lines):
            l = lines[i]
            if not l.strip() or re.match(r"^[-=*]{3,}\s*$", l):
                break
            if re.match(r"^#{1,6}\s", l):
                if i > start:
                    text_block = "\n".join(lines[start:i])
                    blocks.append(MarkdownBlock("text", text_block, preserved=False))
                blocks.append(MarkdownBlock("text", l, preserved=True))
                i += 1
                start = i
                continue
            if l.startswith("|") or re.match(r"^[-*+]\s", l) or re.match(r"^\d+\.\s", l) or l.startswith(">") or _REF_LINK_RE.match(l) or _is_list_continuation(l):
                break
            i += 1
        if i > start:
            text_block = "\n".join(lines[start:i])
            blocks.append(MarkdownBlock("text", text_block, preserved=False))

    return blocks


def process_text_blocks(
    blocks: list[MarkdownBlock],
    *,
    transform: Callable[[str, str, int, str], str],
    prompt_profile: str,
    round_number: int,
    chunk_limit: int,
) -> str:
    """Process only the non-preserved blocks through the chunking pipeline.

    Preserved blocks (tables, code, lists, etc.) are passed through unchanged.
    Regular text blocks are processed through the standard chunking pipeline.
    """
    from aigc_round_service import run_round  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    results: list[str] = []

    for block in blocks:
        if block.preserved:
            results.append(block.text)
            continue

        if not block.text.strip():
            results.append(block.text)
            continue

        # Run the standard chunking pipeline on this text block
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            doc_id = "deai_api_block"
            input_path = tmp / "input.txt"
            output_path = tmp / "output.txt"
            manifest_path = tmp / "manifest.json"

            input_path.write_text(block.text, encoding="utf-8")

            run_round(
                doc_id=doc_id,
                round_number=round_number,
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                transform=transform,
                prompt_profile=prompt_profile,
                chunk_limit=chunk_limit,
            )

            results.append(output_path.read_text(encoding="utf-8"))

    return "\n".join(results)
