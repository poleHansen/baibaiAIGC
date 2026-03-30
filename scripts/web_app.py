from __future__ import annotations

import base64
import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, stream_with_context

from app_config import load_app_config, save_app_config
from app_service import (
    delete_document_history,
    export_round_output,
    get_document_history,
    get_document_status,
    list_document_histories,
    read_output_text,
    run_round_for_app,
    test_model_connection,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
ORIGIN_DIR = ROOT_DIR / "origin"
EXPORT_DIR = ROOT_DIR / "finish" / "web_exports"


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
    ORIGIN_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def error_response(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"message": message}), status


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename).name.strip()
    if not candidate:
        raise ValueError("Filename is required.")
    return candidate


def write_uploaded_file(filename: str, content: str) -> Path:
    ensure_workspace_dirs()
    safe_name = sanitize_filename(filename)
    target_path = ORIGIN_DIR / safe_name
    target_path.write_text(content, encoding="utf-8")
    return target_path


def write_uploaded_binary_file(filename: str, content_base64: str) -> Path:
    ensure_workspace_dirs()
    safe_name = sanitize_filename(filename)
    target_path = ORIGIN_DIR / safe_name
    target_path.write_bytes(base64.b64decode(content_base64))
    return target_path


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


def run_round_async(run_id: str, source_path: str, model_config: dict[str, Any]) -> None:
    try:
        from app_service import emit_progress_event as original_emit_progress_event
        import app_service

        def capture_progress(event: dict[str, Any]) -> None:
            append_progress_event(run_id, event)

        app_service.emit_progress_event = capture_progress
        try:
            result = run_round_for_app(source_path, model_config)
        finally:
            app_service.emit_progress_event = original_emit_progress_event
        finalize_progress(run_id, result=result)
    except Exception as exc:
        finalize_progress(run_id, error=str(exc))


def require_query_value(key: str) -> str:
    value = request.args.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


@app.route("/api/<path:_path>", methods=["OPTIONS"])
@app.route("/api", methods=["OPTIONS"])
def options_api(_path: str | None = None) -> Response:
    return Response(status=204)


@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
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
        filename = str(payload.get("filename", "")).strip()
        encoding = str(payload.get("encoding", "text")).strip().lower()
        if encoding == "base64":
            content_base64 = str(payload.get("contentBase64", ""))
            target_path = write_uploaded_binary_file(filename, content_base64)
        else:
            content = str(payload.get("content", ""))
            target_path = write_uploaded_file(filename, content)
        return jsonify({"sourcePath": str(target_path), "filename": target_path.name}), 201
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/document-status", methods=["GET"])
def get_status() -> tuple[Response, int] | Response:
    try:
        prompt_profile = request.args.get("promptProfile", "cn")
        return jsonify(get_document_status(require_query_value("sourcePath"), prompt_profile=prompt_profile))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/document-history", methods=["GET"])
def get_history() -> tuple[Response, int] | Response:
    try:
        return jsonify(get_document_history(require_query_value("sourcePath")))
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
        return jsonify(read_output_text(require_query_value("outputPath")))
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/run-round", methods=["POST"])
def post_run_round() -> tuple[Response, int] | Response:
    try:
        payload = request.get_json(silent=True) or {}
        source_path = str(payload.get("sourcePath", "")).strip()
        model_config = payload.get("modelConfig")
        if not source_path:
            raise ValueError("sourcePath is required.")
        if not isinstance(model_config, dict):
            raise ValueError("modelConfig is required.")
        run_id = uuid.uuid4().hex
        RUN_STATES[run_id] = ProgressState()
        worker = threading.Thread(
            target=run_round_async,
            args=(run_id, source_path, model_config),
            daemon=True,
        )
        worker.start()
        return jsonify({"runId": run_id}), 202
    except Exception as exc:
        return error_response(str(exc))


@app.route("/api/export-round", methods=["GET"])
def get_export_round() -> tuple[Response, int] | Response:
    try:
        output_path = require_query_value("outputPath")
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
                    return

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.errorhandler(404)
def not_found_api(_: Any) -> tuple[Response, int]:
    return error_response("Unknown route", 404)


def main() -> None:
    ensure_workspace_dirs()
    print("BaibaiAIGC Web API running at http://127.0.0.1:8765")
    app.run(host="127.0.0.1", port=8765, threaded=True)


if __name__ == "__main__":
    main()