from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from markdown_chunks import detect_markdown_blocks


class MultiParagraphListTests(unittest.TestCase):
    """Lists with blank lines between paragraphs must stay in a single
    preserved list block; otherwise indented continuation paragraphs leak
    into ``text`` blocks and the chunker collapses their whitespace."""

    def test_unordered_list_with_indented_continuation_paragraphs(self) -> None:
        text = (
            "- 第一项\n"
            "\n"
            "  第一项的第二段。\n"
            "\n"
            "- 第二项\n"
            "\n"
            "  第二项的第二段。\n"
        )

        blocks = detect_markdown_blocks(text)

        list_blocks = [b for b in blocks if b.block_type == "list"]
        self.assertEqual(len(list_blocks), 1, blocks)
        joined = list_blocks[0].text
        for needle in ("第一项", "第一项的第二段。", "第二项", "第二项的第二段。"):
            self.assertIn(needle, joined)
        non_preserved = [b for b in blocks if not b.preserved]
        self.assertEqual(non_preserved, [], non_preserved)

    def test_ordered_list_with_indented_continuation_paragraphs(self) -> None:
        text = (
            "1. 第一项\n"
            "\n"
            "   第一项的续段。\n"
            "2. 第二项\n"
            "\n"
            "   第二项的续段。\n"
        )

        blocks = detect_markdown_blocks(text)

        olist_blocks = [b for b in blocks if b.block_type == "olist"]
        self.assertEqual(len(olist_blocks), 1, blocks)
        joined = olist_blocks[0].text
        for needle in ("第一项", "第一项的续段。", "第二项", "第二项的续段。"):
            self.assertIn(needle, joined)
        non_preserved = [b for b in blocks if not b.preserved]
        self.assertEqual(non_preserved, [], non_preserved)

    def test_loose_list_blank_lines_between_siblings(self) -> None:
        text = (
            "- one\n"
            "\n"
            "- two\n"
            "\n"
            "- three\n"
        )

        blocks = detect_markdown_blocks(text)

        list_blocks = [b for b in blocks if b.block_type == "list"]
        self.assertEqual(len(list_blocks), 1, blocks)
        joined = list_blocks[0].text
        self.assertIn("one", joined)
        self.assertIn("two", joined)
        self.assertIn("three", joined)

    def test_list_terminates_when_blank_line_followed_by_plain_text(self) -> None:
        text = (
            "- alpha\n"
            "- beta\n"
            "\n"
            "Plain paragraph that should be its own text block.\n"
        )

        blocks = detect_markdown_blocks(text)

        list_blocks = [b for b in blocks if b.block_type == "list"]
        self.assertEqual(len(list_blocks), 1, blocks)
        self.assertIn("alpha", list_blocks[0].text)
        self.assertIn("beta", list_blocks[0].text)
        self.assertNotIn("Plain paragraph", list_blocks[0].text)
        text_blocks = [b for b in blocks if b.block_type == "text" and not b.preserved]
        self.assertEqual(len(text_blocks), 1, blocks)
        self.assertIn("Plain paragraph", text_blocks[0].text)


class ReferenceLinkTests(unittest.TestCase):
    def test_reference_link_label_allows_hyphen(self) -> None:
        text = "[my-ref]: https://example.com\n"

        blocks = detect_markdown_blocks(text)

        ref_blocks = [b for b in blocks if b.block_type == "ref_link"]
        self.assertEqual(len(ref_blocks), 1, blocks)
        self.assertEqual(ref_blocks[0].text, "[my-ref]: https://example.com")
        self.assertTrue(ref_blocks[0].preserved)


if __name__ == "__main__":
    unittest.main()
