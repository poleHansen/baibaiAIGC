from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from llm_client import LLMClientError, _load_json_response


class LLMClientResponseParsingTests(unittest.TestCase):
    def test_empty_response_body_is_explicitly_retriable(self) -> None:
        with self.assertRaises(LLMClientError) as context:
            _load_json_response(
                "",
                status_code=200,
                content_type="application/json",
                api_type="chat_completions",
            )

        error = context.exception
        self.assertEqual(error.code, "provider_empty_response")
        self.assertEqual(error.stage, "llm_parse")
        self.assertTrue(error.retriable)
        self.assertIn("empty response body", str(error))


if __name__ == "__main__":
    unittest.main()
