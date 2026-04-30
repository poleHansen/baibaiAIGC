from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from chunking import _split_long_sentence, split_paragraph_to_chunks


class ChunkingTests(unittest.TestCase):
    def test_chinese_colon_no_longer_creates_trailing_colon_chunk(self) -> None:
        text = ("甲" * 840) + "说明如下：" + ("乙" * 20)

        chunks = split_paragraph_to_chunks(text, 850, "char")

        self.assertEqual(len(chunks), 2)
        self.assertFalse(chunks[0].endswith("："))
        self.assertEqual("".join(chunks), text)

    def test_chinese_comma_split_behavior_is_preserved(self) -> None:
        text = ("甲" * 840) + "，" + ("乙" * 20)

        chunks = split_paragraph_to_chunks(text, 850, "char")

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("，"))
        self.assertEqual("".join(chunks), text)

    def test_english_word_mode_still_splits_on_colon(self) -> None:
        sentence = "alpha beta gamma delta epsilon zeta eta theta note: iota kappa lambda mu"

        chunks = _split_long_sentence(sentence, 10, "word")

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].endswith("note:"))
        self.assertEqual(" ".join(chunks), sentence)


if __name__ == "__main__":
    unittest.main()
