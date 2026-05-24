from __future__ import annotations

import json
import sys
import shutil
from pathlib import Path
from typing import Any, Callable

from aigc_records import delete_document, delete_rounds, list_records, normalize_doc_id, normalize_record_status, update_revision, update_round
from aigc_round_service import MAX_ROUNDS, RoundPausedError, RoundStoppedError, build_progress_path, get_chunk_metric, normalize_path, request_stop, run_round
from app_config import normalize_model_config
from chunking import build_manifest, load_manifest, split_text_to_paragraphs
from docx_pipeline import _split_text_into_blocks, write_docx_text
from llm_client import llm_completion, test_llm_connection
from managed_sources import get_display_name_for_source
from skill_round_helper import build_execution_context, build_round_context, ensure_skill_input_text, get_document_round_state


ROOT_DIR = Path(__file__).resolve().parents[1]
ProgressCallback = Callable[[dict[str, Any]], None]


def _derive_history_status(
    record_status: str,
    progress_status: str,
    *,
    completed_chunk_count: int,
    total_chunk_count: int,
) -> str:
    normalized_record_status = normalize_record_status(record_status)
    normalized_progress_status = str(progress_status or "").strip().lower()
    if normalized_record_status == "completed":
        return "completed"
    if normalized_progress_status == "completed":
        return "completed"
    if normalized_record_status == "in_progress":
        if normalized_progress_status in {"paused", "stopped"}:
            return "interrupted"
        if total_chunk_count > 0 and completed_chunk_count >= total_chunk_count:
            return "completed"
        return "in_progress"
    return "interrupted"


def _can_resume(
    status: str,
    progress_path: str,
    completed_chunk_count: int,
    total_chunk_count: int,
) -> bool:
    return (
        status == "interrupted"
        and bool(progress_path)
        and total_chunk_count > 0
        and completed_chunk_count < total_chunk_count
    )


def _build_record_progress_state(
    *,
    progress_path: str,
    progress_status: str,
    completed_chunk_count: int,
    total_chunk_count: int,
    last_error: str,
    last_error_chunk_id: str,
    stop_reason: str,
) -> dict[str, Any]:
    status = _derive_history_status(
        "completed" if progress_status == "completed" else "in_progress",
        progress_status,
        completed_chunk_count=completed_chunk_count,
        total_chunk_count=total_chunk_count,
    )
    return {
        "status": status,
        "progressPath": progress_path,
        "progressStatus": progress_status,
        "completedChunkCount": completed_chunk_count,
        "totalChunkCount": total_chunk_count,
        "lastError": last_error,
        "lastErrorChunkId": last_error_chunk_id,
        "stopReason": stop_reason,
        "canResume": _can_resume(status, progress_path, completed_chunk_count, total_chunk_count),
    }


def _upsert_history_record(
    *,
    doc_id: str,
    prompt_profile: str,
    round_number: int,
    prompt: str,
    input_path: str,
    output_path: str,
    manifest_path: str,
    progress_path: str,
    status: str,
    chunk_limit: int | None = None,
    input_segment_count: int | None = None,
    output_segment_count: int | None = None,
    is_partial: bool = False,
    target_paragraph_indexes: list[int] | None = None,
    based_on_output_path: str | None = None,
    based_on_manifest_path: str | None = None,
    source_round: int | None = None,
    target_round: int | None = None,
    revision_number: int | None = None,
    last_error: str | None = None,
    last_error_chunk_id: str | None = None,
    completed_chunk_count: int | None = None,
    total_chunk_count: int | None = None,
    stop_reason: str | None = None,
) -> dict[str, Any]:
    if revision_number is not None:
        return update_revision(
            doc_id=doc_id,
            round_number=round_number,
            revision_number=revision_number,
            prompt=prompt,
            prompt_profile=prompt_profile,
            input_path=input_path,
            output_path=output_path,
            chunk_limit=chunk_limit,
            input_segment_count=input_segment_count,
            output_segment_count=output_segment_count,
            manifest_path=manifest_path,
            target_paragraph_indexes=list(target_paragraph_indexes or []),
            based_on_output_path=based_on_output_path,
            based_on_manifest_path=based_on_manifest_path,
            source_round=source_round,
            target_round=target_round,
            status=status,
            progress_path=progress_path,
            last_error=last_error,
            last_error_chunk_id=last_error_chunk_id,
            completed_chunk_count=completed_chunk_count,
            total_chunk_count=total_chunk_count,
            stop_reason=stop_reason,
        )
    return update_round(
        doc_id=doc_id,
        round_number=round_number,
        prompt=prompt,
        prompt_profile=prompt_profile,
        input_path=input_path,
        output_path=output_path,
        chunk_limit=chunk_limit,
        input_segment_count=input_segment_count,
        output_segment_count=output_segment_count,
        manifest_path=manifest_path,
        is_partial=is_partial,
        target_paragraph_indexes=list(target_paragraph_indexes or []),
        based_on_output_path=based_on_output_path,
        based_on_manifest_path=based_on_manifest_path,
        source_round=source_round,
        target_round=target_round,
        status=status,
        progress_path=progress_path,
        last_error=last_error,
        last_error_chunk_id=last_error_chunk_id,
        completed_chunk_count=completed_chunk_count,
        total_chunk_count=total_chunk_count,
        stop_reason=stop_reason,
    )


def _read_progress_summary(manifest_path: str) -> dict[str, Any]:
    if not manifest_path:
        return {
            "progressPath": "",
            "progressStatus": "",
            "completedChunkCount": 0,
            "totalChunkCount": 0,
            "lastError": "",
            "lastErrorChunkId": "",
            "stopRequested": False,
            "stopReason": "",
            "applyMode": "",
            "targetParagraphIndexes": [],
            "sourceRound": None,
            "targetRound": None,
            "revisionNumber": None,
            "basedOnOutputPath": "",
            "basedOnManifestPath": "",
        }

    progress_path = build_progress_path(normalize_path(Path(manifest_path)))
    if not progress_path.exists():
        return {
            "progressPath": str(progress_path),
            "progressStatus": "",
            "completedChunkCount": 0,
            "totalChunkCount": 0,
            "lastError": "",
            "lastErrorChunkId": "",
            "stopRequested": False,
            "stopReason": "",
            "applyMode": "",
            "targetParagraphIndexes": [],
            "sourceRound": None,
            "targetRound": None,
            "revisionNumber": None,
            "basedOnOutputPath": "",
            "basedOnManifestPath": "",
        }

    data = json.loads(progress_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {
            "progressPath": str(progress_path),
            "progressStatus": "",
            "completedChunkCount": 0,
            "totalChunkCount": 0,
            "lastError": "",
            "lastErrorChunkId": "",
            "stopRequested": False,
            "stopReason": "",
            "applyMode": "",
            "targetParagraphIndexes": [],
            "sourceRound": None,
            "targetRound": None,
            "revisionNumber": None,
            "basedOnOutputPath": "",
            "basedOnManifestPath": "",
        }

    return {
        "progressPath": str(progress_path),
        "progressStatus": str(data.get("status", "") or ""),
        "completedChunkCount": int(data.get("completed_chunks", 0) or 0),
        "totalChunkCount": int(data.get("total_chunks", 0) or 0),
        "lastError": str(data.get("last_error", "") or ""),
        "lastErrorChunkId": str(data.get("last_error_chunk_id", "") or ""),
        "stopRequested": bool(data.get("stop_requested")),
        "stopReason": str(data.get("stop_reason", "") or ""),
        "applyMode": str(data.get("apply_mode", "") or ""),
        "targetParagraphIndexes": [int(item) for item in data.get("target_paragraph_indexes", []) if isinstance(item, int)],
        "sourceRound": data.get("source_round"),
        "targetRound": data.get("target_round"),
        "revisionNumber": data.get("revision_number"),
        "basedOnOutputPath": str(data.get("based_on_output_path", "") or ""),
        "basedOnManifestPath": str(data.get("based_on_manifest_path", "") or ""),
    }


def _map_history_round(item: dict[str, Any]) -> dict[str, Any]:
    manifest_path = str(item.get("manifest_path", ""))
    progress = _read_progress_summary(manifest_path)
    progress_path = str(item.get("progress_path", "") or progress["progressPath"])
    completed_chunk_count = int(item.get("completed_chunk_count", progress["completedChunkCount"]) or 0)
    total_chunk_count = int(item.get("total_chunk_count", progress["totalChunkCount"]) or 0)
    last_error = str(item.get("last_error", "") or progress["lastError"])
    last_error_chunk_id = str(item.get("last_error_chunk_id", "") or progress["lastErrorChunkId"])
    stop_reason = str(item.get("stop_reason", "") or progress["stopReason"])
    status = _derive_history_status(
        str(item.get("status", "completed") or "completed"),
        str(progress["progressStatus"]),
        completed_chunk_count=completed_chunk_count,
        total_chunk_count=total_chunk_count,
    )
    return {
        "round": int(item.get("round", 0)),
        "prompt": str(item.get("prompt", "")),
        "inputPath": str(item.get("input_path", "")),
        "outputPath": str(item.get("output_path", "")),
        "manifestPath": manifest_path,
        "progressPath": progress_path,
        "progressStatus": progress["progressStatus"],
        "status": status,
        "canResume": _can_resume(status, progress_path, completed_chunk_count, total_chunk_count),
        "completedChunkCount": completed_chunk_count,
        "totalChunkCount": total_chunk_count,
        "lastError": last_error,
        "lastErrorChunkId": last_error_chunk_id,
        "stopRequested": progress["stopRequested"],
        "stopReason": stop_reason,
        "scoreTotal": item.get("score_total"),
        "chunkLimit": item.get("chunk_limit"),
        "inputSegmentCount": item.get("input_segment_count"),
        "outputSegmentCount": item.get("output_segment_count"),
        "timestamp": str(item.get("timestamp", "")),
        "kind": str(item.get("kind", "round") or "round"),
        "isPartial": bool(item.get("is_partial")),
        "targetParagraphIndexes": list(item.get("target_paragraph_indexes", []) or []),
        "basedOnOutputPath": str(item.get("based_on_output_path", "") or ""),
        "basedOnManifestPath": str(item.get("based_on_manifest_path", "") or ""),
        "sourceRound": item.get("source_round"),
        "targetRound": item.get("target_round"),
        "revisionNumber": item.get("revision_number"),
        "revisions": [_map_history_revision(revision) for revision in item.get("revisions", []) if isinstance(revision, dict)],
    }


def _map_history_revision(item: dict[str, Any]) -> dict[str, Any]:
    manifest_path = str(item.get("manifest_path", ""))
    progress = _read_progress_summary(manifest_path)
    progress_path = str(item.get("progress_path", "") or progress["progressPath"])
    completed_chunk_count = int(item.get("completed_chunk_count", progress["completedChunkCount"]) or 0)
    total_chunk_count = int(item.get("total_chunk_count", progress["totalChunkCount"]) or 0)
    last_error = str(item.get("last_error", "") or progress["lastError"])
    last_error_chunk_id = str(item.get("last_error_chunk_id", "") or progress["lastErrorChunkId"])
    stop_reason = str(item.get("stop_reason", "") or progress["stopReason"])
    status = _derive_history_status(
        str(item.get("status", "completed") or "completed"),
        str(progress["progressStatus"]),
        completed_chunk_count=completed_chunk_count,
        total_chunk_count=total_chunk_count,
    )
    return {
        "revisionNumber": int(item.get("revision_number", 0)),
        "prompt": str(item.get("prompt", "")),
        "inputPath": str(item.get("input_path", "")),
        "outputPath": str(item.get("output_path", "")),
        "manifestPath": manifest_path,
        "progressPath": progress_path,
        "progressStatus": progress["progressStatus"],
        "status": status,
        "canResume": _can_resume(status, progress_path, completed_chunk_count, total_chunk_count),
        "completedChunkCount": completed_chunk_count,
        "totalChunkCount": total_chunk_count,
        "lastError": last_error,
        "lastErrorChunkId": last_error_chunk_id,
        "stopRequested": progress["stopRequested"],
        "stopReason": stop_reason,
        "scoreTotal": item.get("score_total"),
        "chunkLimit": item.get("chunk_limit"),
        "inputSegmentCount": item.get("input_segment_count"),
        "outputSegmentCount": item.get("output_segment_count"),
        "timestamp": str(item.get("timestamp", "")),
        "kind": str(item.get("kind", "revision") or "revision"),
        "isPartial": bool(item.get("is_partial", True)),
        "targetParagraphIndexes": list(item.get("target_paragraph_indexes", []) or []),
        "basedOnOutputPath": str(item.get("based_on_output_path", "") or ""),
        "basedOnManifestPath": str(item.get("based_on_manifest_path", "") or ""),
        "sourceRound": item.get("source_round"),
        "targetRound": item.get("target_round"),
    }


def _record_entry_to_history(doc_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    rounds = entry.get("rounds") if isinstance(entry.get("rounds"), list) else []
    history_rounds = [_map_history_round(item) for item in rounds if isinstance(item, dict)]
    history_rounds.sort(key=lambda item: item["round"], reverse=True)
    completed_rounds = sorted(item["round"] for item in history_rounds if item.get("status") == "completed")
    latest_round = history_rounds[0] if history_rounds else None
    latest_version_output = latest_round.get("outputPath", "") if latest_round else ""
    latest_timestamp = latest_round.get("timestamp", "") if latest_round else ""
    for round_item in history_rounds:
        revisions = round_item.get("revisions", [])
        for revision in revisions:
            revision_timestamp = str(revision.get("timestamp", ""))
            if revision_timestamp >= latest_timestamp:
                latest_timestamp = revision_timestamp
                latest_version_output = str(revision.get("outputPath", "") or "")
    origin_path = str(entry.get("origin_path", doc_id))
    display_name = str(entry.get("display_name", "") or "").strip() or get_display_name_for_source(origin_path)

    return {
        "docId": doc_id,
        "sourcePath": origin_path,
        "originPath": origin_path,
        "displayName": display_name,
        "completedRounds": completed_rounds,
        "latestOutputPath": latest_version_output,
        "lastTimestamp": latest_timestamp,
        "rounds": history_rounds,
    }


def _build_paragraph_preview(output_path: str, manifest_path: str) -> dict[str, Any]:
    normalized_output_path = normalize_path(Path(output_path))
    normalized_manifest_path = normalize_path(Path(manifest_path))
    text = normalized_output_path.read_text(encoding="utf-8")
    manifest = load_manifest(normalized_manifest_path)
    paragraphs = split_text_to_paragraphs(text)
    preview_items: list[dict[str, Any]] = []
    for paragraph in manifest.paragraphs:
        paragraph_index = int(paragraph.paragraph_index)
        preview_items.append(
            {
                "paragraphIndex": paragraph_index,
                "text": paragraphs[paragraph_index] if paragraph_index < len(paragraphs) else "",
                "chunkIds": list(paragraph.chunk_ids),
                "chunkCount": len(paragraph.chunk_ids),
            }
        )
    return {
        "path": str(normalized_output_path),
        "text": text,
        "paragraphs": preview_items,
    }


def emit_progress_event(event: dict[str, Any]) -> None:
    payload = {"event": "round-progress", "payload": event}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def emit_result_payload(payload: dict[str, Any]) -> None:
    print(json.dumps({"event": "result", "payload": payload}, ensure_ascii=False), flush=True)


def emit_error_payload(message: str) -> None:
    print(json.dumps({"event": "error", "payload": {"message": message}}, ensure_ascii=False), flush=True)


def import_document(source_path: str) -> dict[str, Any]:
    normalized_source = normalize_path(Path(source_path))
    try:
        relative_doc_id = normalized_source.relative_to(ROOT_DIR)
        doc_id = normalize_doc_id(str(relative_doc_id).replace("\\", "/"))
    except ValueError:
        doc_id = normalize_doc_id(str(normalized_source))

    round_state = get_document_round_state(doc_id)
    input_text_path, extracted_from_docx = ensure_skill_input_text(normalized_source)
    output_text_path = ""
    manifest_path = ""

    if round_state.next_round is not None:
        context = build_round_context(normalized_source, round_number=round_state.next_round)
        output_text_path = str(context.output_text_path)
        manifest_path = str(context.manifest_path)

    return {
        "docId": doc_id,
        "sourcePath": str(normalized_source),
        "displayName": get_display_name_for_source(normalized_source),
        "sourceKind": normalized_source.suffix.lower() or ".txt",
        "completedRounds": round_state.completed_rounds,
        "nextRound": round_state.next_round,
        "maxRounds": MAX_ROUNDS,
        "hasNextRound": round_state.next_round is not None,
        "isComplete": round_state.is_complete,
        "inputTextPath": str(input_text_path),
        "outputTextPath": output_text_path,
        "manifestPath": manifest_path,
        "extractedFromDocx": extracted_from_docx,
    }


def get_document_status(source_path: str, prompt_profile: str = "cn") -> dict[str, Any]:
    normalized_source = normalize_path(Path(source_path))
    try:
        relative_doc_id = normalized_source.relative_to(ROOT_DIR)
        doc_id = normalize_doc_id(str(relative_doc_id).replace("\\", "/"))
    except ValueError:
        doc_id = normalize_doc_id(str(normalized_source))

    round_state = get_document_round_state(doc_id, prompt_profile=prompt_profile)
    records = list_records()
    entry = records.get(doc_id, {}) if isinstance(records, dict) else {}
    rounds = entry.get("rounds", []) if isinstance(entry, dict) else []
    normalized_prompt_profile = round_state.prompt_profile
    completed_rounds = [
        item.get("round")
        for item in rounds
        if isinstance(item, dict)
        and isinstance(item.get("round"), int)
        and str(item.get("prompt_profile", "cn") or "cn").strip().lower() == normalized_prompt_profile
        and normalize_record_status(item.get("status")) == "completed"
    ]
    completed_rounds.sort()
    latest_output_path = ""
    current_input_path, extracted_from_docx = ensure_skill_input_text(normalized_source)
    current_output_path = ""
    manifest_path = ""
    progress_path = ""
    progress_status = ""
    completed_chunk_count = 0
    total_chunk_count = 0
    last_error = ""
    last_error_chunk_id = ""
    stop_requested = False
    stop_reason = ""
    apply_mode = ""
    target_paragraph_indexes: list[int] = []
    source_round: int | None = None
    target_round: int | None = None
    revision_number: int | None = None
    based_on_output_path = ""
    based_on_manifest_path = ""
    status_value = "completed" if round_state.is_complete else "in_progress"
    can_resume = False

    if round_state.next_round is not None:
        context = build_round_context(
            normalized_source,
            round_number=round_state.next_round,
            prompt_profile=normalized_prompt_profile,
        )
        current_input_path = context.input_text_path
        current_output_path = str(context.output_text_path)
        manifest_path = str(context.manifest_path)
        progress = _read_progress_summary(manifest_path)
        progress_path = str(progress["progressPath"])
        progress_status = str(progress["progressStatus"])
        completed_chunk_count = int(progress["completedChunkCount"])
        total_chunk_count = int(progress["totalChunkCount"])
        last_error = str(progress["lastError"])
        last_error_chunk_id = str(progress["lastErrorChunkId"])
        stop_requested = bool(progress["stopRequested"])
        stop_reason = str(progress["stopReason"])
        apply_mode = str(progress["applyMode"])
        target_paragraph_indexes = list(progress["targetParagraphIndexes"])
        source_round = progress["sourceRound"] if isinstance(progress["sourceRound"], int) else None
        target_round = progress["targetRound"] if isinstance(progress["targetRound"], int) else None
        revision_number = progress["revisionNumber"] if isinstance(progress["revisionNumber"], int) else None
        based_on_output_path = str(progress["basedOnOutputPath"])
        based_on_manifest_path = str(progress["basedOnManifestPath"])
        if based_on_output_path:
            current_input_path = based_on_output_path
        status_value = _derive_history_status(
            "in_progress",
            progress_status,
            completed_chunk_count=completed_chunk_count,
            total_chunk_count=total_chunk_count,
        )
        can_resume = _can_resume(status_value, progress_path, completed_chunk_count, total_chunk_count)
    elif round_state.is_complete:
        status_value = "completed"

    if rounds:
        latest_round = max(
            (
                item
                for item in rounds
                if isinstance(item, dict)
                and isinstance(item.get("round"), int)
                and str(item.get("prompt_profile", "cn") or "cn").strip().lower() == normalized_prompt_profile
            ),
            key=lambda item: item["round"],
            default=None,
        )
        if latest_round:
            latest_output_path = str(normalize_path(Path(str(latest_round.get("output_path", ""))))) if latest_round.get("output_path") else ""
    return {
        "docId": doc_id,
        "promptProfile": normalized_prompt_profile,
        "sourcePath": str(normalized_source),
        "displayName": get_display_name_for_source(normalized_source),
        "sourceKind": normalized_source.suffix.lower() or ".txt",
        "completedRounds": completed_rounds,
        "nextRound": round_state.next_round,
        "maxRounds": MAX_ROUNDS,
        "hasNextRound": round_state.next_round is not None,
        "isComplete": round_state.is_complete,
        "currentInputPath": str(current_input_path),
        "currentOutputPath": current_output_path,
        "manifestPath": manifest_path,
        "progressPath": progress_path,
        "progressStatus": progress_status,
        "status": status_value,
        "canResume": can_resume,
        "completedChunkCount": completed_chunk_count,
        "totalChunkCount": total_chunk_count,
        "lastError": last_error,
        "lastErrorChunkId": last_error_chunk_id,
        "stopRequested": stop_requested,
        "stopReason": stop_reason,
        "latestOutputPath": latest_output_path,
        "extractedFromDocx": extracted_from_docx,
        "applyMode": apply_mode,
        "targetParagraphIndexes": target_paragraph_indexes,
        "sourceRound": source_round,
        "targetRound": target_round,
        "revisionNumber": revision_number,
        "basedOnOutputPath": based_on_output_path,
        "basedOnManifestPath": based_on_manifest_path,
    }


def request_stop_for_app(source_path: str, prompt_profile: str = "cn") -> dict[str, Any]:
    status = get_document_status(source_path, prompt_profile=prompt_profile)
    progress_path = str(status.get("progressPath", "") or "")
    if not progress_path:
        raise ValueError("Current document has no active round progress to stop.")
    request_stop(Path(progress_path))
    return get_document_status(source_path, prompt_profile=prompt_profile)


def get_document_history(source_path: str) -> dict[str, Any]:
    normalized_source = normalize_path(Path(source_path))
    try:
        relative_doc_id = normalized_source.relative_to(ROOT_DIR)
        doc_id = normalize_doc_id(str(relative_doc_id).replace("\\", "/"))
    except ValueError:
        doc_id = normalize_doc_id(str(normalized_source))
    records = list_records()
    entry = records.get(doc_id, {}) if isinstance(records, dict) else {}
    rounds = entry.get("rounds", []) if isinstance(entry, dict) else []

    history_rounds = [_map_history_round(item) for item in rounds if isinstance(item, dict)]

    history_rounds.sort(key=lambda item: item["round"], reverse=True)

    return {
        "docId": doc_id,
        "sourcePath": str(normalized_source),
        "displayName": get_display_name_for_source(normalized_source),
        "rounds": history_rounds,
    }


def list_document_histories() -> dict[str, Any]:
    records = list_records()
    items = [
        _record_entry_to_history(doc_id, entry)
        for doc_id, entry in records.items()
        if isinstance(entry, dict)
    ]
    items.sort(key=lambda item: (item.get("lastTimestamp", ""), item.get("docId", "")), reverse=True)
    return {
        "items": items,
        "total": len(items),
    }


def delete_document_history(doc_id: str, from_round: int | None = None) -> dict[str, Any]:
    normalized_doc_id = normalize_doc_id(doc_id)
    if from_round is None:
        return delete_document(normalized_doc_id)
    return delete_rounds(normalized_doc_id, from_round)


def run_round_for_app(
    source_path: str,
    model_config: dict[str, Any],
    round_number: int | None = None,
    progress_callback: ProgressCallback | None = None,
    execution_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_config = normalize_model_config(model_config)
    base_url = str(normalized_config["baseUrl"])
    api_key = str(normalized_config["apiKey"])
    model = str(normalized_config["model"])
    api_type = str(normalized_config["apiType"])
    temperature = float(normalized_config["temperature"])
    concurrency = int(normalized_config["concurrency"])
    offline_mode = bool(normalized_config["offlineMode"])
    prompt_profile = str(normalized_config["promptProfile"])

    if not offline_mode and (not base_url or not api_key or not model):
        raise ValueError("Model configuration is incomplete.")

    if offline_mode:
        def transform(chunk_text: str, _: str, __: int, ___: str) -> str:
            return chunk_text
    else:
        def transform(_: str, prompt_input: str, __: int, chunk_id: str) -> str:
            try:
                return llm_completion(
                    prompt_input,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    api_type=api_type,
                    temperature=temperature,
                )
            except Exception as exc:
                raise RuntimeError(f"LLM request failed for chunk {chunk_id}: {exc}") from exc

    requested_apply_mode = str((execution_options or {}).get("applyMode", "") or "").strip()
    status = get_document_status(source_path, prompt_profile=prompt_profile)
    if bool(status.get("isComplete")) and requested_apply_mode != "current_round_revision":
        raise ValueError(f"Document already completed all {MAX_ROUNDS} rounds.")

    active_progress_callback = progress_callback or emit_progress_event
    context = build_execution_context(
        source_path,
        round_number=round_number,
        prompt_profile=prompt_profile,
        execution_options=execution_options,
    )

    relative_input_path = relative_to_workspace_path(str(context.input_text_path))
    relative_output_path = relative_to_workspace_path(str(context.output_text_path))
    relative_manifest_path = relative_to_workspace_path(str(context.manifest_path))
    relative_progress_path = relative_to_workspace_path(str(build_progress_path(context.manifest_path)))
    relative_based_on_output_path = relative_to_workspace_path(context.based_on_output_path or "")
    relative_based_on_manifest_path = relative_to_workspace_path(context.based_on_manifest_path or "")

    _upsert_history_record(
        doc_id=context.doc_id,
        prompt_profile=context.prompt_profile,
        round_number=context.round_number,
        prompt=context.prompt_path,
        input_path=relative_input_path,
        output_path=relative_output_path,
        manifest_path=relative_manifest_path,
        progress_path=relative_progress_path,
        status="in_progress",
        is_partial=bool(context.is_partial),
        target_paragraph_indexes=list(context.target_paragraph_indexes or []),
        based_on_output_path=relative_based_on_output_path or None,
        based_on_manifest_path=relative_based_on_manifest_path or None,
        source_round=context.source_round,
        target_round=context.target_round,
        revision_number=context.revision_number,
    )

    try:
        result = run_round(
            doc_id=context.doc_id,
            round_number=context.round_number,
            input_path=context.input_text_path,
            output_path=context.output_text_path,
            manifest_path=context.manifest_path,
            transform=transform,
            prompt_profile=context.prompt_profile,
            progress_callback=active_progress_callback,
            apply_mode=context.apply_mode,
            source_round=context.source_round,
            target_round=context.target_round,
            revision_number=context.revision_number,
            target_paragraph_indexes=context.target_paragraph_indexes,
            based_on_output_path=context.based_on_output_path,
            based_on_manifest_path=context.based_on_manifest_path,
            concurrency=concurrency,
        )
    except (RoundPausedError, RoundStoppedError):
        progress = _read_progress_summary(str(context.manifest_path))
        _upsert_history_record(
            doc_id=context.doc_id,
            prompt_profile=context.prompt_profile,
            round_number=context.round_number,
            prompt=context.prompt_path,
            input_path=relative_input_path,
            output_path=relative_output_path,
            manifest_path=relative_manifest_path,
            progress_path=relative_progress_path,
            status="interrupted",
            is_partial=bool(context.is_partial),
            target_paragraph_indexes=list(context.target_paragraph_indexes or []),
            based_on_output_path=relative_based_on_output_path or None,
            based_on_manifest_path=relative_based_on_manifest_path or None,
            source_round=context.source_round,
            target_round=context.target_round,
            revision_number=context.revision_number,
            last_error=str(progress["lastError"]),
            last_error_chunk_id=str(progress["lastErrorChunkId"]),
            completed_chunk_count=int(progress["completedChunkCount"]),
            total_chunk_count=int(progress["totalChunkCount"]),
            stop_reason=str(progress["stopReason"]),
        )
        raise

    result["skill_context"] = context.to_dict()
    if result["skill_context"].get("is_revision"):
        doc_entry = _upsert_history_record(
            doc_id=result["skill_context"]["doc_id"],
            round_number=int(result["round"]),
            revision_number=int(result["skill_context"]["revision_number"]),
            prompt=result["skill_context"]["prompt_path"],
            prompt_profile=prompt_profile,
            input_path=relative_to_workspace_path(result["skill_context"]["input_text_path"]),
            output_path=relative_to_workspace_path(result["output_path"]),
            chunk_limit=int(result["chunk_limit"]),
            input_segment_count=int(result["input_segment_count"]),
            output_segment_count=int(result["output_segment_count"]),
            manifest_path=relative_to_workspace_path(result["manifest_path"]),
            progress_path=relative_to_workspace_path(result["progress_path"]),
            target_paragraph_indexes=list(result.get("target_paragraph_indexes", []) or []),
            based_on_output_path=relative_to_workspace_path(result.get("based_on_output_path", "")),
            based_on_manifest_path=relative_to_workspace_path(result.get("based_on_manifest_path", "")),
            source_round=result.get("source_round"),
            target_round=result.get("target_round"),
            status="completed",
            completed_chunk_count=int(result["completed_chunk_count"]),
            total_chunk_count=int(result["input_segment_count"]),
        )
    else:
        doc_entry = _upsert_history_record(
            doc_id=result["skill_context"]["doc_id"],
            round_number=int(result["round"]),
            prompt=result["skill_context"]["prompt_path"],
            prompt_profile=prompt_profile,
            input_path=relative_to_workspace_path(result["skill_context"]["input_text_path"]),
            output_path=relative_to_workspace_path(result["output_path"]),
            chunk_limit=int(result["chunk_limit"]),
            input_segment_count=int(result["input_segment_count"]),
            output_segment_count=int(result["output_segment_count"]),
            manifest_path=relative_to_workspace_path(result["manifest_path"]),
            progress_path=relative_to_workspace_path(result["progress_path"]),
            is_partial=bool(result.get("is_partial")),
            target_paragraph_indexes=list(result.get("target_paragraph_indexes", []) or []),
            based_on_output_path=relative_to_workspace_path(result.get("based_on_output_path", "")),
            based_on_manifest_path=relative_to_workspace_path(result.get("based_on_manifest_path", "")),
            source_round=result.get("source_round"),
            target_round=result.get("target_round"),
            status="completed",
            completed_chunk_count=int(result["completed_chunk_count"]),
            total_chunk_count=int(result["input_segment_count"]),
        )

    return {
        "round": int(result["round"]),
        "outputPath": str(result["output_path"]),
        "manifestPath": str(result["manifest_path"]),
        "progressPath": str(result["progress_path"]),
        "chunkLimit": int(result["chunk_limit"]),
        "concurrency": int(result["concurrency"]),
        "inputSegmentCount": int(result["input_segment_count"]),
        "outputSegmentCount": int(result["output_segment_count"]),
        "completedChunkCount": int(result["completed_chunk_count"]),
        "paragraphCount": int(result["paragraph_count"]),
        "resumed": bool(result["resumed"]),
        "offlineMode": offline_mode,
        "docEntry": doc_entry,
        "skillContext": result["skill_context"],
        "paragraphs": _build_paragraph_preview(str(result["output_path"]), str(result["manifest_path"]))["paragraphs"],
        "isPartial": bool(result.get("is_partial")),
        "targetParagraphIndexes": list(result.get("target_paragraph_indexes", []) or []),
        "applyMode": str(result.get("apply_mode", "") or ""),
        "sourceRound": result.get("source_round"),
        "targetRound": result.get("target_round"),
        "revisionNumber": result.get("revision_number"),
    }


def test_model_connection(model_config: dict[str, Any]) -> dict[str, Any]:
    normalized_config = normalize_model_config(model_config)
    base_url = str(normalized_config["baseUrl"])
    api_key = str(normalized_config["apiKey"])
    model = str(normalized_config["model"])
    api_type = str(normalized_config["apiType"])
    offline_mode = bool(normalized_config["offlineMode"])

    if offline_mode:
        return {
            "ok": True,
            "offlineMode": True,
            "message": "当前为离线模式，无需测试远程连通性。",
            "endpoint": "",
            "model": model,
            "apiType": api_type,
        }

    if not base_url or not api_key or not model:
        raise ValueError("Model configuration is incomplete.")

    result = test_llm_connection(model=model, api_key=api_key, base_url=base_url, api_type=api_type)
    return {
        "ok": True,
        "offlineMode": False,
        "message": "接口连通性测试成功。",
        **result,
    }


def export_round_output(output_path: str, export_path: str, target_format: str) -> dict[str, Any]:
    normalized_output_path = normalize_path(Path(output_path))
    normalized_export_path = Path(export_path).resolve()
    normalized_export_path.parent.mkdir(parents=True, exist_ok=True)

    if target_format == "txt":
        shutil.copyfile(normalized_output_path, normalized_export_path)
        return {
            "format": "txt",
            "path": str(normalized_export_path),
        }

    if target_format == "docx":
        text = normalized_output_path.read_text(encoding="utf-8")
        blocks = _split_text_into_blocks(text)
        write_docx_text(blocks, normalized_export_path)
        return {
            "format": "docx",
            "path": str(normalized_export_path),
        }

    raise ValueError(f"Unsupported export format: {target_format}")


def read_output_text(output_path: str) -> dict[str, Any]:
    normalized_output_path = normalize_path(Path(output_path))
    return {
        "path": str(normalized_output_path),
        "text": normalized_output_path.read_text(encoding="utf-8"),
    }


def read_output_preview(output_path: str, manifest_path: str) -> dict[str, Any]:
    return _build_paragraph_preview(output_path, manifest_path)


def read_source_preview(input_path: str, manifest_path: str, prompt_profile: str = "cn") -> dict[str, Any]:
    normalized_input_path = normalize_path(Path(input_path))
    normalized_manifest_path = normalize_path(Path(manifest_path))
    text = normalized_input_path.read_text(encoding="utf-8")
    manifest = build_manifest(text, chunk_metric=get_chunk_metric(prompt_profile))
    normalized_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return _build_paragraph_preview(str(normalized_input_path), str(normalized_manifest_path))


def relative_to_workspace_path(path_value: str) -> str:
    if not path_value:
        return ""
    normalized = normalize_path(Path(path_value))
    try:
        return str(normalized.relative_to(ROOT_DIR)).replace("\\", "/")
    except ValueError:
        return str(normalized)


def load_model_config_payload(model_config_json: str | None = None, model_config_file: str | None = None) -> dict[str, Any]:
    if model_config_file:
        config_path = Path(model_config_file).resolve()
        return normalize_model_config(json.loads(config_path.read_text(encoding="utf-8")))
    if model_config_json:
        return normalize_model_config(json.loads(model_config_json))
    raise ValueError("Either model_config_json or model_config_file must be provided.")


def cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Desktop app service bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-document")
    import_parser.add_argument("source_path")

    status_parser = subparsers.add_parser("document-status")
    status_parser.add_argument("source_path")
    status_parser.add_argument("prompt_profile", nargs="?", default="cn")

    history_parser = subparsers.add_parser("document-history")
    history_parser.add_argument("source_path")

    list_history_parser = subparsers.add_parser("document-history-list")

    delete_history_parser = subparsers.add_parser("delete-document-history")
    delete_history_parser.add_argument("doc_id")
    delete_history_parser.add_argument("--from-round", type=int, default=None)

    stop_parser = subparsers.add_parser("request-stop")
    stop_parser.add_argument("source_path")
    stop_parser.add_argument("prompt_profile", nargs="?", default="cn")

    run_parser = subparsers.add_parser("run-round")
    run_parser.add_argument("source_path")
    run_parser.add_argument("model_config_json", nargs="?", default=None)
    run_parser.add_argument("--config-file", default=None)
    run_parser.add_argument("--round", type=int, default=None)
    run_parser.add_argument("--execution-options-json", default=None)

    test_parser = subparsers.add_parser("test-connection")
    test_parser.add_argument("model_config_json", nargs="?", default=None)
    test_parser.add_argument("--config-file", default=None)

    export_parser = subparsers.add_parser("export-round")
    export_parser.add_argument("output_path")
    export_parser.add_argument("export_path")
    export_parser.add_argument("target_format", choices=["txt", "docx"])

    preview_parser = subparsers.add_parser("read-output")
    preview_parser.add_argument("output_path")

    preview_detail_parser = subparsers.add_parser("read-output-preview")
    preview_detail_parser.add_argument("output_path")
    preview_detail_parser.add_argument("manifest_path")

    source_preview_parser = subparsers.add_parser("read-source-preview")
    source_preview_parser.add_argument("input_path")
    source_preview_parser.add_argument("manifest_path")
    source_preview_parser.add_argument("prompt_profile", nargs="?", default="cn")

    args = parser.parse_args()

    try:
        if args.command == "import-document":
            payload = import_document(args.source_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "document-status":
            payload = get_document_status(args.source_path, prompt_profile=args.prompt_profile)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "document-history":
            payload = get_document_history(args.source_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "document-history-list":
            payload = list_document_histories()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "delete-document-history":
            payload = delete_document_history(args.doc_id, args.from_round)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "request-stop":
            payload = request_stop_for_app(args.source_path, prompt_profile=args.prompt_profile)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "run-round":
            payload = run_round_for_app(
                args.source_path,
                load_model_config_payload(args.model_config_json, args.config_file),
                args.round,
                execution_options=json.loads(args.execution_options_json) if args.execution_options_json else None,
            )
            emit_result_payload(payload)
        elif args.command == "test-connection":
            payload = test_model_connection(load_model_config_payload(args.model_config_json, args.config_file))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "export-round":
            payload = export_round_output(args.output_path, args.export_path, args.target_format)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "read-output":
            payload = read_output_text(args.output_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "read-output-preview":
            payload = read_output_preview(args.output_path, args.manifest_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "read-source-preview":
            payload = read_source_preview(args.input_path, args.manifest_path, args.prompt_profile)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        if args.command == "run-round":
            emit_error_payload(str(exc))
        raise


if __name__ == "__main__":
    cli_main()
