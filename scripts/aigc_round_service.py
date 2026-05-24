from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import json
from pathlib import Path
from typing import Callable

from aigc_records import ROOT_DIR, update_round
from chunking import DEFAULT_CHUNK_LIMIT, Chunk, ChunkManifest, build_manifest, restore_text_from_chunks, save_manifest


PROMPT_PROFILES = {
    "cn": {
        1: "prompts/baibaiaigc1.md",
        2: "prompts/baibaiaigc2.md",
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


class RoundPausedError(RuntimeError):
    def __init__(self, message: str, *, chunk_id: str, completed_chunks: int, total_chunks: int):
        super().__init__(message)
        self.chunk_id = chunk_id
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks


class RoundStoppedError(RuntimeError):
    def __init__(self, message: str, *, completed_chunks: int, total_chunks: int):
        super().__init__(message)
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks


SHARED_OUTPUT_CONTRACT = """
[OUTPUT CONTRACT]
- Only return the rewritten body text for the current input chunk.
- Preserve the original meaning, facts, claims, conclusions, numbering, and paragraph role.
- Do not add, remove, or replace viewpoints or conclusions.
- Do not output explanations, suggestions, options, comments, invitations, or summaries.
- Do not output phrases like: 修改后：, 改写后：, 可以改成, 如果你愿意, 说明：, 原因很简单, 我也可以继续帮你.
- Do not turn the text into chat, Q&A, title suggestions, bullet recommendations, or markdown formatting unless the input already contains it.
""".strip()

RETRY_OUTPUT_CONTRACT = """
[RETRY OUTPUT CONTRACT]
- Your previous attempt used answer-style phrasing and was rejected.
- Do not add any answer-style prefix such as 修改后：, 改写后：, 说明：, or any title-like lead-in.
- Return only the rewritten body text itself, starting directly with the正文内容.
""".strip()

ANSWER_STYLE_PREFIX_WINDOW = 80
ANSWER_STYLE_SUFFIX_WINDOW = 120
PREFIX_WRAPPER_PATTERNS = (
    "可以改成",
    "改写后：",
    "修改后：",
    "说明：",
)
SUFFIX_WRAPPER_PATTERNS = (
    "如果你愿意",
    "原因很简单",
    "我也可以继续帮你",
    "请把需要",
    "你可以直接贴",
)

ANSWER_STYLE_ERROR_MARKER = "contains disallowed answer-style pattern"


def validate_chunk_output(input_text: str, output_text: str, chunk_id: str) -> None:
    normalized_output = output_text.strip()
    if not normalized_output:
        raise ValueError(f"Chunk {chunk_id} returned empty output")

    answer_style_pattern = detect_disallowed_answer_style_pattern(input_text, normalized_output)
    if answer_style_pattern is not None:
        raise ValueError(f"Chunk {chunk_id} contains disallowed answer-style pattern: {answer_style_pattern}")

    markdown_markers = ("**", "### ", "## ", "- **", "> ")
    if any(marker in normalized_output for marker in markdown_markers) and not any(marker in input_text for marker in markdown_markers):
        raise ValueError(f"Chunk {chunk_id} introduced markdown-style formatting")

    if len(normalized_output) > max(len(input_text) * 2, len(input_text) + 200):
        raise ValueError(f"Chunk {chunk_id} expanded abnormally; possible answer-style drift")


def is_answer_style_validation_error(exc: Exception) -> bool:
    return isinstance(exc, ValueError) and ANSWER_STYLE_ERROR_MARKER in str(exc)


def _normalize_text_for_wrapper_detection(text: str) -> str:
    return text.strip()


def _normalize_prefix_window(text: str) -> str:
    return _normalize_text_for_wrapper_detection(text)[:ANSWER_STYLE_PREFIX_WINDOW]


def _normalize_suffix_window(text: str) -> str:
    normalized = _normalize_text_for_wrapper_detection(text)
    return normalized[-ANSWER_STYLE_SUFFIX_WINDOW:]


def _has_body_alignment(candidate_body: str, input_body: str) -> bool:
    normalized_candidate = _normalize_text_for_wrapper_detection(candidate_body)
    normalized_input = _normalize_text_for_wrapper_detection(input_body)
    if not normalized_candidate or not normalized_input:
        return False
    if normalized_candidate == normalized_input:
        return True
    return normalized_candidate.startswith(normalized_input) or normalized_candidate.endswith(normalized_input)


def detect_prefixed_wrapper(input_text: str, output_text: str) -> str | None:
    normalized_output = _normalize_text_for_wrapper_detection(output_text)
    normalized_input = _normalize_text_for_wrapper_detection(input_text)
    output_prefix = normalized_output[:ANSWER_STYLE_PREFIX_WINDOW]
    input_prefix = normalized_input[:ANSWER_STYLE_PREFIX_WINDOW]

    for pattern in PREFIX_WRAPPER_PATTERNS:
        if not output_prefix.startswith(pattern):
            continue
        if input_prefix.startswith(pattern):
            continue
        if _has_body_alignment(normalized_output[len(pattern):], normalized_input):
            return pattern

    return None


def detect_suffixed_wrapper(input_text: str, output_text: str) -> str | None:
    normalized_output = _normalize_text_for_wrapper_detection(output_text)
    normalized_input = _normalize_text_for_wrapper_detection(input_text)
    output_suffix_window = _normalize_suffix_window(normalized_output)
    input_suffix_window = _normalize_suffix_window(normalized_input)

    for pattern in SUFFIX_WRAPPER_PATTERNS:
        if pattern not in output_suffix_window:
            continue
        output_suffix_index = normalized_output.rfind(pattern)
        if output_suffix_index < 0:
            continue
        if pattern in input_suffix_window and normalized_input.rfind(pattern) == output_suffix_index:
            continue
        if _has_body_alignment(normalized_output[:output_suffix_index], normalized_input):
            return pattern

    return None


def detect_wrapped_chat_answer(input_text: str, output_text: str) -> str | None:
    prefix_pattern = detect_prefixed_wrapper(input_text, output_text)
    if prefix_pattern is None:
        return None

    normalized_output = _normalize_text_for_wrapper_detection(output_text)
    prefix_stripped_output = normalized_output[len(prefix_pattern):]
    suffix_pattern = detect_suffixed_wrapper(input_text, prefix_stripped_output)
    if suffix_pattern is None:
        return prefix_pattern
    return f"{prefix_pattern} ... {suffix_pattern}"


def detect_disallowed_answer_style_pattern(input_text: str, output_text: str) -> str | None:
    wrapped_pattern = detect_wrapped_chat_answer(input_text, output_text)
    if wrapped_pattern is not None:
        return wrapped_pattern

    suffix_pattern = detect_suffixed_wrapper(input_text, output_text)
    if suffix_pattern is not None:
        return suffix_pattern

    return None


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


def build_prompt_input(
    prompt_text: str,
    chunk_text: str,
    round_number: int,
    chunk_id: str,
    extra_contract: str | None = None,
) -> str:
    contract_parts = [SHARED_OUTPUT_CONTRACT]
    if extra_contract:
        contract_parts.append(extra_contract.strip())
    contract_text = "\n\n".join(part for part in contract_parts if part.strip())
    return (
        f"[ROUND {round_number}]\n"
        f"[CHUNK {chunk_id}]\n\n"
        f"{prompt_text.strip()}\n\n"
        f"{contract_text}\n\n"
        "[INPUT TEXT]\n"
        f"{chunk_text}"
    )


def _rewrite_chunk_with_validation(
    transform: Transform,
    prompt_text: str,
    chunk_text: str,
    round_number: int,
    chunk_id: str,
) -> str:
    prompt_input = build_prompt_input(prompt_text, chunk_text, round_number, chunk_id)
    chunk_output = transform(chunk_text, prompt_input, round_number, chunk_id)
    try:
        validate_chunk_output(chunk_text, chunk_output, chunk_id)
        return chunk_output
    except Exception as exc:
        if not is_answer_style_validation_error(exc):
            raise

    retry_prompt_input = build_prompt_input(
        prompt_text,
        chunk_text,
        round_number,
        chunk_id,
        extra_contract=RETRY_OUTPUT_CONTRACT,
    )
    retry_output = transform(chunk_text, retry_prompt_input, round_number, chunk_id)
    validate_chunk_output(chunk_text, retry_output, chunk_id)
    return retry_output


def build_progress_path(manifest_path: Path) -> Path:
    normalized_manifest_path = normalize_path(manifest_path)
    manifest_stem = normalized_manifest_path.stem
    if manifest_stem.endswith("_manifest"):
        progress_name = f"{manifest_stem[:-9]}_progress.json"
    else:
        progress_name = f"{manifest_stem}_progress.json"
    return normalized_manifest_path.with_name(progress_name)


def build_stop_request_path(manifest_path: Path) -> Path:
    normalized_manifest_path = normalize_path(manifest_path)
    path_stem = normalized_manifest_path.stem
    if path_stem.endswith("_manifest"):
        stop_name = f"{path_stem[:-9]}_stop.json"
    elif path_stem.endswith("_progress"):
        stop_name = f"{path_stem[:-9]}_stop.json"
    else:
        stop_name = f"{path_stem}_stop.json"
    return normalized_manifest_path.with_name(stop_name)


def _default_progress_payload(
    manifest: ChunkManifest,
    *,
    round_number: int,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    prompt_profile: str,
    apply_mode: str | None = None,
    source_round: int | None = None,
    target_round: int | None = None,
    revision_number: int | None = None,
    target_paragraph_indexes: list[int] | None = None,
    based_on_output_path: str | None = None,
    based_on_manifest_path: str | None = None,
) -> dict[str, object]:
    return {
        "version": 1,
        "status": "in_progress",
        "round": round_number,
        "prompt_profile": prompt_profile,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "total_chunks": manifest.chunk_count,
        "completed_chunks": 0,
        "last_error": "",
        "last_error_chunk_id": "",
        "stop_requested": False,
        "stop_reason": "",
        "chunk_outputs": {},
        "apply_mode": apply_mode or "",
        "source_round": source_round,
        "target_round": target_round if target_round is not None else round_number,
        "revision_number": revision_number,
        "target_paragraph_indexes": target_paragraph_indexes or [],
        "based_on_output_path": based_on_output_path or "",
        "based_on_manifest_path": based_on_manifest_path or "",
    }


def _load_progress_payload(
    progress_path: Path,
    manifest: ChunkManifest,
    *,
    round_number: int,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    prompt_profile: str,
    apply_mode: str | None = None,
    source_round: int | None = None,
    target_round: int | None = None,
    revision_number: int | None = None,
    target_paragraph_indexes: list[int] | None = None,
    based_on_output_path: str | None = None,
    based_on_manifest_path: str | None = None,
) -> dict[str, object]:
    if not progress_path.exists():
        return _default_progress_payload(
            manifest,
            round_number=round_number,
            input_path=input_path,
            output_path=output_path,
            manifest_path=manifest_path,
            prompt_profile=prompt_profile,
            apply_mode=apply_mode,
            source_round=source_round,
            target_round=target_round,
            revision_number=revision_number,
            target_paragraph_indexes=target_paragraph_indexes,
            based_on_output_path=based_on_output_path,
            based_on_manifest_path=based_on_manifest_path,
        )

    data = json.loads(progress_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _default_progress_payload(
            manifest,
            round_number=round_number,
            input_path=input_path,
            output_path=output_path,
            manifest_path=manifest_path,
            prompt_profile=prompt_profile,
            apply_mode=apply_mode,
            source_round=source_round,
            target_round=target_round,
            revision_number=revision_number,
            target_paragraph_indexes=target_paragraph_indexes,
            based_on_output_path=based_on_output_path,
            based_on_manifest_path=based_on_manifest_path,
        )

    chunk_ids = {chunk.chunk_id for chunk in manifest.chunks}
    raw_outputs = data.get("chunk_outputs")
    chunk_outputs = {
        str(chunk_id): str(output)
        for chunk_id, output in raw_outputs.items()
        if isinstance(raw_outputs, dict)
        and chunk_id in chunk_ids
        and isinstance(output, str)
        and output.strip()
    }

    payload = _default_progress_payload(
        manifest,
        round_number=round_number,
        input_path=input_path,
        output_path=output_path,
        manifest_path=manifest_path,
        prompt_profile=prompt_profile,
        apply_mode=apply_mode,
        source_round=source_round,
        target_round=target_round,
        revision_number=revision_number,
        target_paragraph_indexes=target_paragraph_indexes,
        based_on_output_path=based_on_output_path,
        based_on_manifest_path=based_on_manifest_path,
    )
    payload.update(
        {
            "version": int(data.get("version", 1) or 1),
            "status": str(data.get("status", "in_progress") or "in_progress"),
            "last_error": str(data.get("last_error", "") or ""),
            "last_error_chunk_id": str(data.get("last_error_chunk_id", "") or ""),
            "stop_requested": bool(data.get("stop_requested")),
            "stop_reason": str(data.get("stop_reason", "") or ""),
            "chunk_outputs": chunk_outputs,
            "completed_chunks": len(chunk_outputs),
            "apply_mode": str(data.get("apply_mode", apply_mode or "") or ""),
            "source_round": data.get("source_round", source_round),
            "target_round": data.get("target_round", target_round if target_round is not None else round_number),
            "revision_number": data.get("revision_number", revision_number),
            "target_paragraph_indexes": data.get("target_paragraph_indexes", target_paragraph_indexes or []),
            "based_on_output_path": str(data.get("based_on_output_path", based_on_output_path or "") or ""),
            "based_on_manifest_path": str(data.get("based_on_manifest_path", based_on_manifest_path or "") or ""),
        }
    )
    return payload


def _save_progress_payload(progress_path: Path, payload: dict[str, object]) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_target_paragraph_indexes(
    target_paragraph_indexes: list[int] | None,
    paragraph_count: int,
) -> list[int]:
    if target_paragraph_indexes is None:
        return []
    normalized = sorted({int(index) for index in target_paragraph_indexes})
    if not normalized:
        raise ValueError("target_paragraph_indexes must contain at least one paragraph index.")
    invalid = [index for index in normalized if index < 0 or index >= paragraph_count]
    if invalid:
        raise ValueError(f"target_paragraph_indexes out of range: {invalid}")
    return normalized


def _validate_saved_selection_context(
    progress_payload: dict[str, object],
    *,
    apply_mode: str | None,
    source_round: int | None,
    target_round: int | None,
    revision_number: int | None,
    target_paragraph_indexes: list[int],
    based_on_output_path: str | None,
    based_on_manifest_path: str | None,
) -> None:
    saved_apply_mode = str(progress_payload.get("apply_mode", "") or "")
    saved_targets = [int(index) for index in progress_payload.get("target_paragraph_indexes", []) if isinstance(index, int)]
    saved_source_round = progress_payload.get("source_round")
    saved_target_round = progress_payload.get("target_round")
    saved_revision_number = progress_payload.get("revision_number")
    saved_output_path = str(progress_payload.get("based_on_output_path", "") or "")
    saved_manifest_path = str(progress_payload.get("based_on_manifest_path", "") or "")

    if saved_apply_mode and apply_mode and saved_apply_mode != apply_mode:
        raise ValueError("Existing progress belongs to a different apply mode.")
    if saved_targets and saved_targets != target_paragraph_indexes:
        raise ValueError("Existing progress belongs to a different paragraph selection.")
    if isinstance(saved_source_round, int) and source_round is not None and saved_source_round != source_round:
        raise ValueError("Existing progress belongs to a different source round.")
    if isinstance(saved_target_round, int) and target_round is not None and saved_target_round != target_round:
        raise ValueError("Existing progress belongs to a different target round.")
    if isinstance(saved_revision_number, int) and revision_number is not None and saved_revision_number != revision_number:
        raise ValueError("Existing progress belongs to a different revision.")
    if saved_output_path and based_on_output_path and normalize_path(Path(saved_output_path)) != normalize_path(Path(based_on_output_path)):
        raise ValueError("Existing progress belongs to a different source output.")
    if saved_manifest_path and based_on_manifest_path and normalize_path(Path(saved_manifest_path)) != normalize_path(Path(based_on_manifest_path)):
        raise ValueError("Existing progress belongs to a different source manifest.")


def request_stop(progress_path: Path, *, reason: str = "用户手动停止，保留当前进度，可继续执行当前轮。") -> dict[str, object]:
    normalized_progress_path = normalize_path(progress_path)
    stop_request_path = build_stop_request_path(normalized_progress_path)
    stop_request_path.parent.mkdir(parents=True, exist_ok=True)
    stop_payload = {
        "requested": True,
        "reason": reason,
    }
    stop_request_path.write_text(json.dumps(stop_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if normalized_progress_path.exists():
        try:
            progress_payload = json.loads(normalized_progress_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            progress_payload = {}
        if isinstance(progress_payload, dict):
            progress_payload["stop_requested"] = True
            progress_payload["stop_reason"] = reason
            _save_progress_payload(normalized_progress_path, progress_payload)

    return stop_payload


def _consume_stop_request(stop_request_path: Path) -> str:
    normalized_stop_request_path = normalize_path(stop_request_path)
    if not normalized_stop_request_path.exists():
        return ""
    try:
        data = json.loads(normalized_stop_request_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
    reason = ""
    if isinstance(data, dict):
        reason = str(data.get("reason", "") or "")
    normalized_stop_request_path.unlink(missing_ok=True)
    return reason or "用户手动停止，保留当前进度，可继续执行当前轮。"


def _stop_if_requested(
    *,
    stop_request_path: Path,
    progress_path: Path,
    progress_payload: dict[str, object],
    round_number: int,
    completed_chunks: int,
    total_chunks: int,
    progress_callback: ProgressCallback | None,
) -> None:
    reason = _consume_stop_request(stop_request_path)
    if not reason:
        return

    progress_payload["status"] = "stopped"
    progress_payload["completed_chunks"] = completed_chunks
    progress_payload["stop_requested"] = False
    progress_payload["stop_reason"] = reason
    progress_payload["last_error"] = ""
    progress_payload["last_error_chunk_id"] = ""
    _save_progress_payload(progress_path, progress_payload)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "stopped",
                "round": round_number,
                "totalChunks": total_chunks,
                "completedChunks": completed_chunks,
                "remainingChunks": total_chunks - completed_chunks,
                "progressPath": str(progress_path),
                "message": reason,
            }
        )

    raise RoundStoppedError(
        reason,
        completed_chunks=completed_chunks,
        total_chunks=total_chunks,
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
    apply_mode: str | None = None,
    source_round: int | None = None,
    target_round: int | None = None,
    revision_number: int | None = None,
    target_paragraph_indexes: list[int] | None = None,
    based_on_output_path: str | None = None,
    based_on_manifest_path: str | None = None,
    concurrency: int = 1,
) -> dict:
    normalized_input_path = normalize_path(input_path)
    normalized_output_path = normalize_path(output_path)
    normalized_manifest_path = normalize_path(manifest_path)
    normalized_progress_path = build_progress_path(normalized_manifest_path)
    normalized_stop_request_path = build_stop_request_path(normalized_manifest_path)
    normalized_prompt_profile = normalize_prompt_profile(prompt_profile)
    chunk_metric = get_chunk_metric(normalized_prompt_profile)
    normalized_concurrency = min(max(1, int(concurrency or 1)), 16)

    text = normalized_input_path.read_text(encoding="utf-8")
    manifest = build_manifest(text, chunk_limit=chunk_limit, chunk_metric=chunk_metric)
    save_manifest(manifest, normalized_manifest_path)
    normalized_targets = _normalize_target_paragraph_indexes(target_paragraph_indexes, manifest.paragraph_count) if target_paragraph_indexes is not None else []

    progress_payload = _load_progress_payload(
        normalized_progress_path,
        manifest,
        round_number=round_number,
        input_path=normalized_input_path,
        output_path=normalized_output_path,
        manifest_path=normalized_manifest_path,
        prompt_profile=normalized_prompt_profile,
        apply_mode=apply_mode,
        source_round=source_round,
        target_round=target_round,
        revision_number=revision_number,
        target_paragraph_indexes=normalized_targets,
        based_on_output_path=based_on_output_path,
        based_on_manifest_path=based_on_manifest_path,
    )
    _validate_saved_selection_context(
        progress_payload,
        apply_mode=apply_mode,
        source_round=source_round,
        target_round=target_round,
        revision_number=revision_number,
        target_paragraph_indexes=normalized_targets,
        based_on_output_path=based_on_output_path,
        based_on_manifest_path=based_on_manifest_path,
    )
    chunk_outputs = dict(progress_payload["chunk_outputs"])
    completed_chunks = len(chunk_outputs)
    progress_payload["completed_chunks"] = completed_chunks
    progress_payload["total_chunks"] = manifest.chunk_count
    if progress_payload.get("status") == "completed" and completed_chunks < manifest.chunk_count:
        progress_payload["status"] = "paused"
    elif progress_payload.get("status") == "stopped" and completed_chunks < manifest.chunk_count:
        progress_payload["status"] = "in_progress"
    progress_payload["stop_requested"] = False
    progress_payload["stop_reason"] = ""
    progress_payload["apply_mode"] = apply_mode or str(progress_payload.get("apply_mode", "") or "")
    progress_payload["source_round"] = source_round
    progress_payload["target_round"] = target_round if target_round is not None else round_number
    progress_payload["revision_number"] = revision_number
    progress_payload["target_paragraph_indexes"] = normalized_targets
    progress_payload["based_on_output_path"] = based_on_output_path or str(progress_payload.get("based_on_output_path", "") or "")
    progress_payload["based_on_manifest_path"] = based_on_manifest_path or str(progress_payload.get("based_on_manifest_path", "") or "")
    _save_progress_payload(normalized_progress_path, progress_payload)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "chunking-ready",
                "round": round_number,
                "totalChunks": manifest.chunk_count,
                "completedChunks": completed_chunks,
                "remainingChunks": manifest.chunk_count - completed_chunks,
                "paragraphCount": manifest.paragraph_count,
                "inputPath": str(normalized_input_path),
                "outputPath": str(normalized_output_path),
                "manifestPath": str(normalized_manifest_path),
                "progressPath": str(normalized_progress_path),
                "resumed": completed_chunks > 0,
                "applyMode": progress_payload["apply_mode"],
                "targetParagraphIndexes": normalized_targets,
                "revisionNumber": revision_number,
                "concurrency": normalized_concurrency,
            }
        )

    prompts = get_prompt_mapping(normalized_prompt_profile)
    prompt_text = load_prompt(normalized_prompt_profile, round_number)
    target_paragraph_index_set = set(normalized_targets)

    def emit_processing(index: int, chunk: Chunk) -> None:
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "processing-chunk",
                    "round": round_number,
                    "currentChunk": index,
                    "totalChunks": manifest.chunk_count,
                    "completedChunks": len(chunk_outputs),
                    "chunkId": chunk.chunk_id,
                    "paragraphIndex": chunk.paragraph_index,
                    "chunkIndex": chunk.chunk_index,
                    "concurrency": normalized_concurrency,
                }
            )

    def rewrite_chunk(chunk: Chunk) -> str:
        if target_paragraph_index_set and chunk.paragraph_index not in target_paragraph_index_set:
            return chunk.text
        return _rewrite_chunk_with_validation(
            transform,
            prompt_text,
            chunk.text,
            round_number,
            chunk.chunk_id,
        )

    def save_chunk_output(index: int, chunk: Chunk, chunk_output: str) -> None:
        chunk_outputs[chunk.chunk_id] = chunk_output
        progress_payload["chunk_outputs"] = chunk_outputs
        progress_payload["status"] = "in_progress"
        progress_payload["last_error"] = ""
        progress_payload["last_error_chunk_id"] = ""
        progress_payload["stop_requested"] = False
        progress_payload["stop_reason"] = ""
        progress_payload["completed_chunks"] = len(chunk_outputs)
        _save_progress_payload(normalized_progress_path, progress_payload)

        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "chunk-complete",
                    "round": round_number,
                    "currentChunk": index,
                    "totalChunks": manifest.chunk_count,
                    "completedChunks": len(chunk_outputs),
                    "chunkId": chunk.chunk_id,
                    "progressPath": str(normalized_progress_path),
                    "concurrency": normalized_concurrency,
                }
            )

    def pause_on_chunk_error(index: int, chunk: Chunk, exc: Exception) -> None:
        error_message = str(exc)
        progress_payload["status"] = "paused"
        progress_payload["last_error"] = error_message
        progress_payload["last_error_chunk_id"] = chunk.chunk_id
        progress_payload["completed_chunks"] = len(chunk_outputs)
        _save_progress_payload(normalized_progress_path, progress_payload)
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "chunk-error",
                    "round": round_number,
                    "currentChunk": index,
                    "totalChunks": manifest.chunk_count,
                    "completedChunks": len(chunk_outputs),
                    "chunkId": chunk.chunk_id,
                    "progressPath": str(normalized_progress_path),
                    "error": error_message,
                    "concurrency": normalized_concurrency,
                }
            )
        raise RoundPausedError(
            f"Chunk {chunk.chunk_id} failed and progress was paused: {error_message}",
            chunk_id=chunk.chunk_id,
            completed_chunks=len(chunk_outputs),
            total_chunks=manifest.chunk_count,
        ) from exc

    def emit_skipped(index: int, chunk: Chunk) -> None:
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "chunk-skipped",
                    "round": round_number,
                    "currentChunk": index,
                    "totalChunks": manifest.chunk_count,
                    "completedChunks": len(chunk_outputs),
                    "chunkId": chunk.chunk_id,
                    "concurrency": normalized_concurrency,
                }
            )

    indexed_chunks = list(enumerate(manifest.chunks, start=1))

    if normalized_concurrency <= 1:
        for index, chunk in indexed_chunks:
            _stop_if_requested(
                stop_request_path=normalized_stop_request_path,
                progress_path=normalized_progress_path,
                progress_payload=progress_payload,
                round_number=round_number,
                completed_chunks=len(chunk_outputs),
                total_chunks=manifest.chunk_count,
                progress_callback=progress_callback,
            )
            if chunk.chunk_id in chunk_outputs:
                emit_skipped(index, chunk)
                continue

            emit_processing(index, chunk)
            try:
                chunk_output = rewrite_chunk(chunk)
            except Exception as exc:
                pause_on_chunk_error(index, chunk, exc)
            save_chunk_output(index, chunk, chunk_output)
    else:
        pending_chunks: list[tuple[int, Chunk]] = []
        for index, chunk in indexed_chunks:
            _stop_if_requested(
                stop_request_path=normalized_stop_request_path,
                progress_path=normalized_progress_path,
                progress_payload=progress_payload,
                round_number=round_number,
                completed_chunks=len(chunk_outputs),
                total_chunks=manifest.chunk_count,
                progress_callback=progress_callback,
            )
            if chunk.chunk_id in chunk_outputs:
                emit_skipped(index, chunk)
                continue
            pending_chunks.append((index, chunk))

        next_pending_index = 0
        active_futures: dict[Future[str], tuple[int, Chunk]] = {}
        executor = ThreadPoolExecutor(max_workers=normalized_concurrency)

        def submit_next_chunks() -> None:
            nonlocal next_pending_index
            while next_pending_index < len(pending_chunks) and len(active_futures) < normalized_concurrency:
                _stop_if_requested(
                    stop_request_path=normalized_stop_request_path,
                    progress_path=normalized_progress_path,
                    progress_payload=progress_payload,
                    round_number=round_number,
                    completed_chunks=len(chunk_outputs),
                    total_chunks=manifest.chunk_count,
                    progress_callback=progress_callback,
                )
                index, chunk = pending_chunks[next_pending_index]
                next_pending_index += 1
                emit_processing(index, chunk)
                active_futures[executor.submit(rewrite_chunk, chunk)] = (index, chunk)

        try:
            submit_next_chunks()
            while active_futures:
                done, _ = wait(active_futures, return_when=FIRST_COMPLETED)
                for future in done:
                    index, chunk = active_futures.pop(future)
                    try:
                        chunk_output = future.result()
                    except Exception as exc:
                        for active_future in active_futures:
                            active_future.cancel()
                        pause_on_chunk_error(index, chunk, exc)
                    save_chunk_output(index, chunk, chunk_output)
                    _stop_if_requested(
                        stop_request_path=normalized_stop_request_path,
                        progress_path=normalized_progress_path,
                        progress_payload=progress_payload,
                        round_number=round_number,
                        completed_chunks=len(chunk_outputs),
                        total_chunks=manifest.chunk_count,
                        progress_callback=progress_callback,
                    )
                submit_next_chunks()
        except (RoundPausedError, RoundStoppedError):
            for active_future in active_futures:
                active_future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    _stop_if_requested(
        stop_request_path=normalized_stop_request_path,
        progress_path=normalized_progress_path,
        progress_payload=progress_payload,
        round_number=round_number,
        completed_chunks=len(chunk_outputs),
        total_chunks=manifest.chunk_count,
        progress_callback=progress_callback,
    )

    restored = restore_text_from_chunks(manifest, chunk_outputs)

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "restoring-output",
                "round": round_number,
                "totalChunks": manifest.chunk_count,
                "completedChunks": len(chunk_outputs),
            }
        )

    normalized_output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_output_path.write_text(restored, encoding="utf-8")
    progress_payload["status"] = "completed"
    progress_payload["completed_chunks"] = len(chunk_outputs)
    progress_payload["stop_requested"] = False
    progress_payload["stop_reason"] = ""
    _save_progress_payload(normalized_progress_path, progress_payload)

    doc_entry: dict[str, object] = {}
    if revision_number is None:
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
            is_partial=bool(normalized_targets),
            target_paragraph_indexes=normalized_targets or None,
            based_on_output_path=relative_to_root(Path(based_on_output_path)) if based_on_output_path else None,
            based_on_manifest_path=relative_to_root(Path(based_on_manifest_path)) if based_on_manifest_path else None,
            source_round=source_round,
            target_round=target_round if target_round is not None else round_number,
        )

    return {
        "doc_entry": doc_entry,
        "round": round_number,
        "output_path": str(normalized_output_path),
        "manifest_path": str(normalized_manifest_path),
        "progress_path": str(normalized_progress_path),
        "chunk_limit": chunk_limit,
        "concurrency": normalized_concurrency,
        "input_segment_count": manifest.chunk_count,
        "output_segment_count": len(chunk_outputs),
        "completed_chunk_count": len(chunk_outputs),
        "paragraph_count": manifest.paragraph_count,
        "resumed": completed_chunks > 0,
        "apply_mode": str(progress_payload.get("apply_mode", "") or ""),
        "source_round": source_round,
        "target_round": target_round if target_round is not None else round_number,
        "revision_number": revision_number,
        "target_paragraph_indexes": normalized_targets,
        "based_on_output_path": based_on_output_path or "",
        "based_on_manifest_path": based_on_manifest_path or "",
        "is_partial": bool(normalized_targets),
    }
