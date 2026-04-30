from __future__ import annotations

import json
import sys
import shutil
from pathlib import Path
from typing import Any, Callable

from aigc_records import delete_document, delete_rounds, list_records, normalize_doc_id
from aigc_round_service import MAX_ROUNDS, build_progress_path, normalize_path, request_stop
from app_config import normalize_model_config
from docx_pipeline import _split_text_into_blocks, write_docx_text
from llm_client import llm_completion, test_llm_connection
from skill_round_helper import build_round_context, ensure_skill_input_text, get_document_round_state


ROOT_DIR = Path(__file__).resolve().parents[1]
ProgressCallback = Callable[[dict[str, Any]], None]


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
    }


def _map_history_round(item: dict[str, Any]) -> dict[str, Any]:
    manifest_path = str(item.get("manifest_path", ""))
    progress = _read_progress_summary(manifest_path)
    return {
        "round": int(item.get("round", 0)),
        "prompt": str(item.get("prompt", "")),
        "inputPath": str(item.get("input_path", "")),
        "outputPath": str(item.get("output_path", "")),
        "manifestPath": manifest_path,
        "progressPath": progress["progressPath"],
        "progressStatus": progress["progressStatus"],
        "completedChunkCount": progress["completedChunkCount"],
        "totalChunkCount": progress["totalChunkCount"],
        "lastError": progress["lastError"],
        "lastErrorChunkId": progress["lastErrorChunkId"],
        "stopRequested": progress["stopRequested"],
        "stopReason": progress["stopReason"],
        "scoreTotal": item.get("score_total"),
        "chunkLimit": item.get("chunk_limit"),
        "inputSegmentCount": item.get("input_segment_count"),
        "outputSegmentCount": item.get("output_segment_count"),
        "timestamp": str(item.get("timestamp", "")),
    }


def _record_entry_to_history(doc_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    rounds = entry.get("rounds") if isinstance(entry.get("rounds"), list) else []
    history_rounds = [_map_history_round(item) for item in rounds if isinstance(item, dict)]
    history_rounds.sort(key=lambda item: item["round"], reverse=True)
    completed_rounds = sorted(item["round"] for item in history_rounds)
    latest_round = history_rounds[0] if history_rounds else None
    origin_path = str(entry.get("origin_path", doc_id))

    return {
        "docId": doc_id,
        "sourcePath": origin_path,
        "originPath": origin_path,
        "completedRounds": completed_rounds,
        "latestOutputPath": latest_round.get("outputPath", "") if latest_round else "",
        "lastTimestamp": latest_round.get("timestamp", "") if latest_round else "",
        "rounds": history_rounds,
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
        "completedChunkCount": completed_chunk_count,
        "totalChunkCount": total_chunk_count,
        "lastError": last_error,
        "lastErrorChunkId": last_error_chunk_id,
        "stopRequested": stop_requested,
        "stopReason": stop_reason,
        "latestOutputPath": latest_output_path,
        "extractedFromDocx": extracted_from_docx,
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
) -> dict[str, Any]:
    from skill_round_helper import run_skill_round

    normalized_config = normalize_model_config(model_config)
    base_url = str(normalized_config["baseUrl"])
    api_key = str(normalized_config["apiKey"])
    model = str(normalized_config["model"])
    api_type = str(normalized_config["apiType"])
    temperature = float(normalized_config["temperature"])
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

    status = get_document_status(source_path, prompt_profile=prompt_profile)
    if bool(status.get("isComplete")):
        raise ValueError(f"Document already completed all {MAX_ROUNDS} rounds.")

    active_progress_callback = progress_callback or emit_progress_event
    result = run_skill_round(
        source_path,
        transform=transform,
        round_number=round_number,
        prompt_profile=prompt_profile,
        progress_callback=active_progress_callback,
    )
    return {
        "round": int(result["round"]),
        "outputPath": str(result["output_path"]),
        "manifestPath": str(result["manifest_path"]),
        "progressPath": str(result["progress_path"]),
        "chunkLimit": int(result["chunk_limit"]),
        "inputSegmentCount": int(result["input_segment_count"]),
        "outputSegmentCount": int(result["output_segment_count"]),
        "completedChunkCount": int(result["completed_chunk_count"]),
        "paragraphCount": int(result["paragraph_count"]),
        "resumed": bool(result["resumed"]),
        "offlineMode": offline_mode,
        "docEntry": result["doc_entry"],
        "skillContext": result["skill_context"],
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

    test_parser = subparsers.add_parser("test-connection")
    test_parser.add_argument("model_config_json", nargs="?", default=None)
    test_parser.add_argument("--config-file", default=None)

    export_parser = subparsers.add_parser("export-round")
    export_parser.add_argument("output_path")
    export_parser.add_argument("export_path")
    export_parser.add_argument("target_format", choices=["txt", "docx"])

    preview_parser = subparsers.add_parser("read-output")
    preview_parser.add_argument("output_path")

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
        else:
            raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        if args.command == "run-round":
            emit_error_payload(str(exc))
        raise


if __name__ == "__main__":
    cli_main()
