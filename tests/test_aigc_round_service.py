from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
TEMP_ROOT = ROOT_DIR / ".tmp_tests"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from aigc_round_service import (
    RoundPausedError,
    RoundStoppedError,
    build_progress_path,
    build_stop_request_path,
    detect_disallowed_answer_style_pattern,
    detect_prefixed_wrapper,
    detect_suffixed_wrapper,
    detect_wrapped_chat_answer,
    request_stop,
    run_round,
    validate_chunk_output,
)


class ValidateChunkOutputTests(unittest.TestCase):
    def test_disallowed_explanation_prefix_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "contains disallowed answer-style pattern"):
            validate_chunk_output("这是改写后的内容", "说明：这是改写后的内容", "p0_c0")

    def test_disallowed_answer_prefix_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "contains disallowed answer-style pattern"):
            validate_chunk_output("这是改写后的内容", "修改后：这是改写后的内容", "p0_c0")

    def test_input_prefix_inheritance_is_allowed(self) -> None:
        validate_chunk_output("说明：实验结果如下。", "说明：实验结果如下，但是表达更自然。", "p0_c0")
        validate_chunk_output("修改后：系统配置如下。", "修改后：系统配置如下，并补充了说明。", "p0_c1")
        validate_chunk_output("改写后：这是示例文本。", "改写后：这是示例文本，并给出后续描述。", "p0_c2")

    def test_mid_sentence_reference_is_allowed(self) -> None:
        validate_chunk_output("原文", "系统返回“改写后：”字段作为标识。", "p0_c0")
        validate_chunk_output("原文", "标签“说明：”用于提示，不代表回答前缀。", "p0_c1")
        validate_chunk_output("原文", "正文中部出现修改后：这种标签时默认放行。", "p0_c2")

    def test_added_invitation_suffix_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "contains disallowed answer-style pattern"):
            validate_chunk_output("这是原始正文。", "这是原始正文。如果你愿意，我也可以继续帮你调整。", "p0_c0")

    def test_original_invitation_content_is_allowed(self) -> None:
        validate_chunk_output("如果你愿意，这句话本身就是原文。", "如果你愿意，这句话本身就是原文，并略作润色。", "p0_c0")


class DetectAnswerStylePatternTests(unittest.TestCase):
    def test_detects_new_prefixed_wrapper_only_when_body_aligns(self) -> None:
        self.assertEqual(detect_prefixed_wrapper("这是新增前缀", "说明：这是新增前缀"), "说明：")
        self.assertEqual(detect_prefixed_wrapper("这是新增前缀", "修改后：这是新增前缀"), "修改后：")
        self.assertEqual(detect_prefixed_wrapper("这是新增前缀", "改写后：这是新增前缀"), "改写后：")

    def test_detects_new_suffix_wrapper_when_body_aligns(self) -> None:
        self.assertEqual(
            detect_suffixed_wrapper("这是原始正文。", "这是原始正文。如果你愿意，我也可以继续帮你调整。"),
            "如果你愿意",
        )
        self.assertEqual(
            detect_suffixed_wrapper("这是原始正文。", "这是原始正文。请把需要修改的内容继续发我。"),
            "请把需要",
        )

    def test_ignores_original_or_mid_sentence_content(self) -> None:
        self.assertIsNone(detect_disallowed_answer_style_pattern("说明：实验结果如下", "说明：实验结果如下，并补充解释"))
        self.assertIsNone(detect_disallowed_answer_style_pattern("如果你愿意，这句话本身就是原文。", "如果你愿意，这句话本身就是原文，并补充解释。"))
        self.assertIsNone(detect_disallowed_answer_style_pattern("普通正文", "系统返回“改写后：”字段"))
        self.assertIsNone(detect_disallowed_answer_style_pattern("普通正文", "正文中部出现修改后：标签"))

    def test_detects_combined_wrapped_answer(self) -> None:
        self.assertEqual(
            detect_wrapped_chat_answer(
                "这是原始正文。",
                "说明：这是原始正文。如果你愿意，我也可以继续帮你调整。",
            ),
            "说明： ... 如果你愿意",
        )


class RunRoundRetryTests(unittest.TestCase):
    def make_temp_dir(self) -> Path:
        TEMP_ROOT.mkdir(exist_ok=True)
        temp_dir = TEMP_ROOT / f"case_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, temp_dir, True)
        return temp_dir

    def test_answer_style_failure_retries_once_and_succeeds(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        input_path.write_text("这是改写后的正文。", encoding="utf-8")

        prompts: list[str] = []
        responses = iter(["说明：这是改写后的正文。", "这是改写后的正文。"])

        def transform(_: str, prompt_input: str, __: int, ___: str) -> str:
            prompts.append(prompt_input)
            return next(responses)

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            result = run_round(
                doc_id="tests/retry-success.txt",
                round_number=1,
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                transform=transform,
            )

        self.assertEqual(result["completed_chunk_count"], 1)
        self.assertEqual(output_path.read_text(encoding="utf-8"), "这是改写后的正文。")
        self.assertEqual(len(prompts), 2)
        self.assertIn("Do not output phrases like", prompts[0])
        self.assertIn("[RETRY OUTPUT CONTRACT]", prompts[1])
        self.assertIn("Do not add any answer-style prefix", prompts[1])

    def test_inherited_input_prefix_does_not_retry(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        input_path.write_text("说明：实验结果如下。", encoding="utf-8")

        prompts: list[str] = []

        def transform(_: str, prompt_input: str, __: int, ___: str) -> str:
            prompts.append(prompt_input)
            return "说明：实验结果如下，并作了更自然的表达。"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            result = run_round(
                doc_id="tests/inherited-prefix.txt",
                round_number=1,
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                transform=transform,
            )

        self.assertEqual(result["completed_chunk_count"], 1)
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("[RETRY OUTPUT CONTRACT]", prompts[0])

    def test_inherited_original_invitation_does_not_retry(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        input_path.write_text("如果你愿意，这句话本身就是原文。", encoding="utf-8")

        prompts: list[str] = []

        def transform(_: str, prompt_input: str, __: int, ___: str) -> str:
            prompts.append(prompt_input)
            return "如果你愿意，这句话本身就是原文，并稍作润色。"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            result = run_round(
                doc_id="tests/inherited-invitation.txt",
                round_number=1,
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                transform=transform,
            )

        self.assertEqual(result["completed_chunk_count"], 1)
        self.assertEqual(len(prompts), 1)

    def test_second_answer_style_failure_pauses_with_same_error_shape(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        progress_path = build_progress_path(manifest_path)
        input_path.write_text("仍然是回答腔", encoding="utf-8")

        call_count = 0

        def transform(_: str, __: str, ___: int, ____: str) -> str:
            nonlocal call_count
            call_count += 1
            return "说明：仍然是回答腔"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            with self.assertRaisesRegex(RoundPausedError, "contains disallowed answer-style pattern"):
                run_round(
                    doc_id="tests/retry-fail.txt",
                    round_number=1,
                    input_path=input_path,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    transform=transform,
                )

        self.assertEqual(call_count, 2)
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertEqual(progress["status"], "paused")
        self.assertIn("contains disallowed answer-style pattern", progress["last_error"])

    def test_non_answer_style_failure_does_not_retry(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        input_path.write_text("这是原始正文。", encoding="utf-8")

        call_count = 0

        def transform(_: str, __: str, ___: int, ____: str) -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("network error")

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            with self.assertRaisesRegex(RoundPausedError, "network error"):
                run_round(
                    doc_id="tests/network-error.txt",
                    round_number=1,
                    input_path=input_path,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    transform=transform,
                )

        self.assertEqual(call_count, 1)

    def test_user_requested_stop_marks_progress_stopped(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        progress_path = build_progress_path(manifest_path)
        stop_path = build_stop_request_path(manifest_path)
        input_path.write_text("第一段。\n\n第二段。", encoding="utf-8")

        call_count = 0

        def transform(chunk_text: str, __: str, ___: int, ____: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                request_stop(progress_path)
            return f"{chunk_text} 已改写"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            with self.assertRaisesRegex(RoundStoppedError, "用户手动停止"):
                run_round(
                    doc_id="tests/stopped.txt",
                    round_number=1,
                    input_path=input_path,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    transform=transform,
                    chunk_limit=3,
                )

        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.assertEqual(progress["status"], "stopped")
        self.assertEqual(progress["completed_chunks"], 1)
        self.assertEqual(progress["stop_reason"], "用户手动停止，保留当前进度，可继续执行当前轮。")
        self.assertFalse(progress["stop_requested"])
        self.assertFalse(stop_path.exists())

    def test_resume_after_stop_uses_saved_progress(self) -> None:
        temp_path = self.make_temp_dir()
        input_path = temp_path / "input.txt"
        output_path = temp_path / "output.txt"
        manifest_path = temp_path / "manifest.json"
        input_path.write_text("第一段。\n\n第二段。", encoding="utf-8")

        first_call_count = 0

        def stop_after_first_chunk(chunk_text: str, __: str, ___: int, ____: str) -> str:
            nonlocal first_call_count
            first_call_count += 1
            if first_call_count == 1:
                request_stop(build_progress_path(manifest_path))
            return f"{chunk_text} 已改写"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            with self.assertRaises(RoundStoppedError):
                run_round(
                    doc_id="tests/resume-after-stop.txt",
                    round_number=1,
                    input_path=input_path,
                    output_path=output_path,
                    manifest_path=manifest_path,
                    transform=stop_after_first_chunk,
                    chunk_limit=3,
                )

        resumed_call_count = 0

        def resume_transform(chunk_text: str, __: str, ___: int, ____: str) -> str:
            nonlocal resumed_call_count
            resumed_call_count += 1
            return f"{chunk_text} 已改写"

        with patch("aigc_round_service.update_round", return_value={"ok": True}):
            result = run_round(
                doc_id="tests/resume-after-stop.txt",
                round_number=1,
                input_path=input_path,
                output_path=output_path,
                manifest_path=manifest_path,
                transform=resume_transform,
                chunk_limit=3,
            )

        self.assertTrue(result["resumed"])
        self.assertEqual(resumed_call_count, result["completed_chunk_count"] - 1)
        output_text = output_path.read_text(encoding="utf-8")
        self.assertIn("第一段", output_text)
        self.assertIn("第二段", output_text)
        self.assertIn("已改写", output_text)


if __name__ == "__main__":
    unittest.main()
