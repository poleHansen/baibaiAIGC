from __future__ import annotations

import json
import sys
import shutil
from pathlib import Path
from typing import Any

from aigc_records import delete_document, delete_rounds, list_records, normalize_doc_id
from aigc_round_service import MAX_ROUNDS, normalize_path
from docx_pipeline import _split_text_into_blocks, write_docx_text
from llm_client import llm_completion, test_llm_connection
from skill_round_helper import build_round_context, ensure_skill_input_text, get_document_round_state


ROOT_DIR = Path(__file__).resolve().parents[1]


def _map_history_round(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": int(item.get("round", 0)),
        "prompt": str(item.get("prompt", "")),
        "inputPath": str(item.get("input_path", "")),
        "outputPath": str(item.get("output_path", "")),
        "manifestPath": str(item.get("manifest_path", "")),
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


def get_document_status(source_path: str) -> dict[str, Any]:
    normalized_source = normalize_path(Path(source_path))
    try:
        relative_doc_id = normalized_source.relative_to(ROOT_DIR)
        doc_id = normalize_doc_id(str(relative_doc_id).replace("\\", "/"))
    except ValueError:
        doc_id = normalize_doc_id(str(normalized_source))

    round_state = get_document_round_state(doc_id)
    records = list_records()
    entry = records.get(doc_id, {}) if isinstance(records, dict) else {}
    rounds = entry.get("rounds", []) if isinstance(entry, dict) else []
    completed_rounds = [item.get("round") for item in rounds if isinstance(item, dict) and isinstance(item.get("round"), int)]
    completed_rounds.sort()
    latest_output_path = ""
    current_input_path, extracted_from_docx = ensure_skill_input_text(normalized_source)
    current_output_path = ""
    manifest_path = ""

    if round_state.next_round is not None:
        context = build_round_context(normalized_source, round_number=round_state.next_round)
        current_input_path = context.input_text_path
        current_output_path = str(context.output_text_path)
        manifest_path = str(context.manifest_path)

    if rounds:
        latest_round = max((item for item in rounds if isinstance(item, dict) and isinstance(item.get("round"), int)), key=lambda item: item["round"], default=None)
        if latest_round:
            latest_output_path = str(normalize_path(Path(str(latest_round.get("output_path", ""))))) if latest_round.get("output_path") else ""
    return {
        "docId": doc_id,
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
        "latestOutputPath": latest_output_path,
        "extractedFromDocx": extracted_from_docx,
    }


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


def run_round_for_app(source_path: str, model_config: dict[str, Any], round_number: int | None = None) -> dict[str, Any]:
    from skill_round_helper import run_skill_round

    base_url = str(model_config.get("baseUrl", "")).strip()
    api_key = str(model_config.get("apiKey", "")).strip()
    model = str(model_config.get("model", "")).strip()
    api_type = str(model_config.get("apiType", "chat_completions")).strip()
    temperature = float(model_config.get("temperature", 0.7))
    offline_mode = bool(model_config.get("offlineMode", False))

    if not offline_mode and (not base_url or not api_key or not model):
        raise ValueError("Model configuration is incomplete.")

    if offline_mode:
        def transform(chunk_text: str, _: str, __: int, ___: str) -> str:
            return chunk_text
    else:
        def transform(_: str, prompt_input: str, __: int, ___: str) -> str:
            return llm_completion(
                prompt_input,
                model=model,
                api_key=api_key,
                base_url=base_url,
                api_type=api_type,
                temperature=temperature,
            )

    status = get_document_status(source_path)
    if bool(status.get("isComplete")):
        raise ValueError(f"Document already completed all {MAX_ROUNDS} rounds.")

    result = run_skill_round(
        source_path,
        transform=transform,
        round_number=round_number,
        progress_callback=emit_progress_event,
    )
    return {
        "round": int(result["round"]),
        "outputPath": str(result["output_path"]),
        "manifestPath": str(result["manifest_path"]),
        "chunkLimit": int(result["chunk_limit"]),
        "inputSegmentCount": int(result["input_segment_count"]),
        "outputSegmentCount": int(result["output_segment_count"]),
        "paragraphCount": int(result["paragraph_count"]),
        "offlineMode": offline_mode,
        "docEntry": result["doc_entry"],
        "skillContext": result["skill_context"],
    }


def test_model_connection(model_config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(model_config.get("baseUrl", "")).strip()
    api_key = str(model_config.get("apiKey", "")).strip()
    model = str(model_config.get("model", "")).strip()
    api_type = str(model_config.get("apiType", "chat_completions")).strip()
    offline_mode = bool(model_config.get("offlineMode", False))

    if offline_mode:
        return {
            "ok": True,
            "offlineMode": True,
            "message": "当前为离线模式，无需测试远程连通性。",
            "endpoint": "",
            "model": model,
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
        return json.loads(config_path.read_text(encoding="utf-8"))
    if model_config_json:
        return json.loads(model_config_json)
    raise ValueError("Either model_config_json or model_config_file must be provided.")


def cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Desktop app service bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-document")
    import_parser.add_argument("source_path")

    status_parser = subparsers.add_parser("document-status")
    status_parser.add_argument("source_path")

    history_parser = subparsers.add_parser("document-history")
    history_parser.add_argument("source_path")

    list_history_parser = subparsers.add_parser("document-history-list")

    delete_history_parser = subparsers.add_parser("delete-document-history")
    delete_history_parser.add_argument("doc_id")
    delete_history_parser.add_argument("--from-round", type=int, default=None)

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
            payload = get_document_status(args.source_path)
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
