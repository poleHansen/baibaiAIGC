from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, stream_with_context

from aigc_round_service import MAX_ROUNDS, normalize_path
from app_config import load_app_config, save_app_config
from app_service import (
    delete_document_history,
    export_round_output,
    get_document_history,
    get_document_status,
    list_document_histories,
    read_output_text,
    read_output_preview,
    read_source_preview,
    request_stop_for_app,
    run_round_for_app,
    test_model_connection,
)
from managed_sources import (
    ORIGIN_DIR,
    ensure_managed_source_dirs,
    find_latest_matching_chat_upload,
    get_display_name_for_source,
    import_chat_base64_attachment,
    import_chat_text_attachment,
    sanitize_filename,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
FINISH_DIR = ROOT_DIR / "finish"
EXPORT_DIR = FINISH_DIR / "web_exports"
ALLOWED_WEB_ORIGINS = {
    "http://localhost:1420",
    "http://127.0.0.1:1420",
}


@dataclass
class ProgressState:
    completed: bool = False
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    condition: threading.Condition = field(default_factory=threading.Condition)


RUN_STATES: dict[str, ProgressState] = {}
app = Flask(__name__)


def ensure_workspace_dirs() -> None:
    ensure_managed_source_dirs()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def error_response(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"message": message}), status
def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def require_managed_source_path(path_value: str) -> str:
    normalized_path = normalize_path(Path(path_value))
    if not _is_within(normalized_path, ORIGIN_DIR):
        raise ValueError("sourcePath must stay within the managed origin directory.")
    return str(normalized_path)


def require_managed_preview_input_path(path_value: str) -> str:
    normalized_path = normalize_path(Path(path_value))
    if _is_within(normalized_path, ORIGIN_DIR) or _is_within(normalized_path, FINISH_DIR):
        return str(normalized_path)
    raise ValueError("inputPath must stay within the managed origin or finish directory.")


def require_managed_output_path(path_value: str) -> str:
    normalized_path = normalize_path(Path(path_value))
    if not _is_within(normalized_path, FINISH_DIR):
        raise ValueError("outputPath must stay within the managed finish directory.")
    return str(normalized_path)


def write_uploaded_file(filename: str, content: str) -> Path:
    return import_chat_text_attachment(filename, content)


def write_uploaded_binary_file(filename: str, content_base64: str) -> Path:
    return import_chat_base64_attachment(filename, content_base64)


def build_upload_response(
    source_path: Path,
    *,
    conflict: bool,
    reused: bool,
) -> dict[str, Any]:
    return {
        "sourcePath": str(source_path),
        "filename": source_path.name,
        "displayName": get_display_name_for_source(source_path),
        "conflict": conflict,
        "reused": reused,
    }


def append_progress_event(run_id: str, event: dict[str, Any]) -> None:
    state = RUN_STATES.get(run_id)
    if not state:
        return
    with state.condition:
        state.events.append(event)
        state.condition.notify_all()


def finalize_progress(run_id: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    state = RUN_STATES.get(run_id)
    if not state:
        return
    with state.condition:
        state.result = result
        state.error = error
        state.completed = True
        state.condition.notify_all()


def run_round_async(run_id: str, source_path: str, model_config: dict[str, Any], execution_options: dict[str, Any] | None) -> None:
    try:
        def capture_progress(event: dict[str, Any]) -> None:
            append_progress_event(run_id, event)

        result = run_round_for_app(
            source_path,
            model_config,
            progress_callback=capture_progress,
            execution_options=execution_options,
        )
        finalize_progress(run_id, result=result)
    except Exception as exc:
        finalize_progress(run_id, error=str(exc))


def reduce_text_async(run_id: str, source_path: str, model_config: dict[str, Any]) -> None:
    try:
        def capture_progress(event: dict[str, Any]) -> None:
            append_progress_event(run_id, event)

        prompt_profile = str(model_config.get("promptProfile", "cn") or "cn")
        max_rounds = MAX_ROUNDS if prompt_profile == "cn" else 1
        last_output_text = ""

        for round_num in range(1, max_rounds + 1):
            append_progress_event(run_id, {
                "phase": "reduce-round-start",
                "round": round_num,
                "totalRounds": max_rounds,
                "message": f"开始第 {round_num}/{max_rounds} 轮降 AIGC 处理",
            })
            result = run_round_for_app(
                source_path,
                model_config,
                progress_callback=capture_progress,
            )
            output_path = Path(str(result["outputPath"]))
            last_output_text = output_path.read_text(encoding="utf-8")

        finalize_progress(run_id, result={
            "reduceText": last_output_text,
            "outputPath": str(result.get("outputPath", "")),
        })
    except Exception as exc:
        finalize_progress(run_id, error=str(exc))


def require_query_value(key: str) -> str:
    value = request.args.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


@app.before_request
def validate_origin() -> tuple[Response, int] | None:
    origin = request.headers.get("Origin", "").strip()
    if origin and origin not in ALLOWED_WEB_ORIGINS:
        return error_response("Origin not allowed.", 403)
    return None


@app.route("/api/<path:_path>", methods=["OPTIONS"])
@app.route("/api", methods=["OPTIONS"])
def options_api(_path: str | None = None) -> Response:
    return Response(status=204)


@app.after_request
def add_cors_headers(response: Response) -> Response:
    origin = request.headers.get("Origin", "").strip()
    if origin in ALLOWED_WEB_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


@app.route("/api/model-config", methods=["GET"])
def get_model_config() -> Response:
    return jsonify(load_app_config())


@app.route("/api/model-config", methods=["POST"])
def post_model_config() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(save_app_config(payload))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/test-connection", methods=["POST"])
def post_test_connection() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(test_model_connection(payload))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/upload-document", methods=["POST"])
def post_upload_document() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        filename = sanitize_filename(str(payload.get("filename", "")).strip())
        duplicate_action = str(payload.get("duplicateAction", "") or "").strip().lower()
        encoding = str(payload.get("encoding", "text")).strip().lower()
        existing_path = find_latest_matching_chat_upload(filename)

        if existing_path is not None and duplicate_action not in {"reuse_existing", "replace_with_new"}:
            return jsonify(build_upload_response(existing_path, conflict=True, reused=False)), 200

        if existing_path is not None and duplicate_action == "reuse_existing":
            return jsonify(build_upload_response(existing_path, conflict=False, reused=True)), 200

        if encoding == "base64":
            content_base64 = str(payload.get("contentBase64", ""))
            target_path = write_uploaded_binary_file(filename, content_base64)
        else:
            content = str(payload.get("content", ""))
            target_path = write_uploaded_file(filename, content)
        return jsonify(build_upload_response(target_path, conflict=False, reused=False)), 201
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/document-status", methods=["GET"])
def get_status() -> tuple[Response, int] | Response:
    try:
        prompt_profile = request.args.get("promptProfile", "cn")
        source_path = require_managed_source_path(require_query_value("sourcePath"))
        return jsonify(get_document_status(source_path, prompt_profile=prompt_profile))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/document-history", methods=["GET"])
def get_history() -> tuple[Response, int] | Response:
    try:
        source_path = require_managed_source_path(require_query_value("sourcePath"))
        return jsonify(get_document_history(source_path))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/history-documents", methods=["GET"])
def get_history_list() -> tuple[Response, int] | Response:
    try:
        return jsonify(list_document_histories())
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/document-history", methods=["DELETE"])
def delete_history() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        doc_id = str(payload.get("docId", "")).strip()
        from_round = payload.get("fromRound")
        if not doc_id:
            raise ValueError("docId is required.")
        if from_round is not None and not isinstance(from_round, int):
            raise ValueError("fromRound must be an integer when provided.")
        return jsonify(delete_document_history(doc_id, from_round))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/read-output", methods=["GET"])
def get_read_output() -> tuple[Response, int] | Response:
    try:
        output_path = require_managed_output_path(require_query_value("outputPath"))
        return jsonify(read_output_text(output_path))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/read-output-preview", methods=["GET"])
def get_read_output_preview() -> tuple[Response, int] | Response:
    try:
        output_path = require_managed_output_path(require_query_value("outputPath"))
        manifest_path = require_managed_output_path(require_query_value("manifestPath"))
        return jsonify(read_output_preview(output_path, manifest_path))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/read-source-preview", methods=["GET"])
def get_read_source_preview() -> tuple[Response, int] | Response:
    try:
        input_path = require_managed_preview_input_path(require_query_value("inputPath"))
        manifest_path = require_managed_output_path(require_query_value("manifestPath"))
        prompt_profile = request.args.get("promptProfile", "cn")
        return jsonify(read_source_preview(input_path, manifest_path, prompt_profile))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/run-round", methods=["POST"])
def post_run_round() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        source_path = require_managed_source_path(str(payload.get("sourcePath", "")).strip())
        model_config = payload.get("modelConfig")
        execution_options = payload.get("executionOptions")
        if not isinstance(model_config, dict):
            raise ValueError("modelConfig is required.")
        if execution_options is not None and not isinstance(execution_options, dict):
            raise ValueError("executionOptions must be an object when provided.")
        run_id = uuid.uuid4().hex
        RUN_STATES[run_id] = ProgressState()
        worker = threading.Thread(
            target=run_round_async,
            args=(run_id, source_path, model_config, execution_options),
            daemon=True,
        )
        worker.start()
        return jsonify({"runId": run_id}), 202
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/request-stop", methods=["POST"])
def post_request_stop() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        source_path = require_managed_source_path(str(payload.get("sourcePath", "")).strip())
        prompt_profile = str(payload.get("promptProfile", "cn") or "cn")
        return jsonify(request_stop_for_app(source_path, prompt_profile=prompt_profile))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/reduce-text", methods=["POST"])
def post_reduce_text() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("text is required.")
        model_config = payload.get("modelConfig")
        if not isinstance(model_config, dict):
            raise ValueError("modelConfig is required.")
        source_path = import_chat_text_attachment("paste_input.txt", text)
        run_id = uuid.uuid4().hex
        RUN_STATES[run_id] = ProgressState()
        worker = threading.Thread(
            target=reduce_text_async,
            args=(run_id, str(source_path), model_config),
            daemon=True,
        )
        worker.start()
        return jsonify({"runId": run_id}), 202
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/export-round", methods=["GET"])
def get_export_round() -> tuple[Response, int] | Response:
    try:
        output_path = require_managed_output_path(require_query_value("outputPath"))
        target_format = require_query_value("targetFormat")
        stem = Path(output_path).stem or "current-round"
        export_path = EXPORT_DIR / f"{stem}.{target_format}"
        result = export_round_output(output_path, str(export_path), target_format)
        file_path = Path(result["path"])
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if target_format == "txt":
            mimetype = "text/plain; charset=utf-8"
        return send_file(file_path, mimetype=mimetype, as_attachment=True, download_name=file_path.name)
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/run-round-events/<run_id>", methods=["GET"])
def get_run_round_events(run_id: str) -> tuple[Response, int] | Response:
    state = RUN_STATES.get(run_id)
    if not state:
        return error_response("Unknown run id.")

    def generate() -> Any:
        cursor = 0
        while True:
            with state.condition:
                while cursor >= len(state.events) and not state.completed:
                    state.condition.wait(timeout=1)
                while cursor < len(state.events):
                    event = state.events[cursor]
                    payload = json.dumps(event, ensure_ascii=False)
                    yield f"event: progress\ndata: {payload}\n\n"
                    cursor += 1
                if state.completed:
                    if state.error:
                        payload = json.dumps({"message": state.error}, ensure_ascii=False)
                        yield f"event: error\ndata: {payload}\n\n"
                    else:
                        payload = json.dumps(state.result or {}, ensure_ascii=False)
                        yield f"event: result\ndata: {payload}\n\n"
                    RUN_STATES.pop(run_id, None)
                    return

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.errorhandler(404)
def not_found_api(_: Any) -> tuple[Response, int]:
    return error_response("Unknown route", 404)


def main() -> None:
    ensure_workspace_dirs()
    print("BaibaiAIGC Web API running at http://127.0.0.1:8765")
    app.run(host="127.0.0.1", port=8765, threaded=True)


if __name__ == "__main__":
    main()
