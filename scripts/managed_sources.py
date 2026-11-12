from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path

from workspace_paths import origin_dir


SUPPORTED_MANAGED_SOURCE_SUFFIXES = {".txt", ".docx"}
CHAT_UPLOAD_NAME_PATTERN = re.compile(r"^(?P<stem>.+?)_(?P<stamp>\d{8}_\d{6})(?:_(?P<counter>\d+))?$")


def chat_uploads_dir() -> Path:
    return origin_dir() / "chat-uploads"


def ensure_managed_source_dirs() -> None:
    origin_dir().mkdir(parents=True, exist_ok=True)
    chat_uploads_dir().mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename).name.strip()
    if not candidate:
        raise ValueError("Filename is required.")
    return candidate


def validate_managed_source_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_MANAGED_SOURCE_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_MANAGED_SOURCE_SUFFIXES))
        raise ValueError(f"Unsupported file type: {suffix or '(none)'}. Supported types: {supported}.")
    return suffix


def build_chat_upload_path(filename: str, *, now: datetime | None = None) -> Path:
    ensure_managed_source_dirs()
    safe_name = sanitize_filename(filename)
    suffix = validate_managed_source_suffix(safe_name)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    stem = Path(safe_name).stem
    candidate = chat_uploads_dir() / f"{stem}_{stamp}{suffix}"

    counter = 2
    while candidate.exists():
        candidate = chat_uploads_dir() / f"{stem}_{stamp}_{counter}{suffix}"
        counter += 1
    return candidate


def get_original_filename_from_managed_name(filename: str) -> str:
    safe_name = sanitize_filename(filename)
    suffix = validate_managed_source_suffix(safe_name)
    stem = Path(safe_name).stem
    match = CHAT_UPLOAD_NAME_PATTERN.fullmatch(stem)
    if not match:
        return safe_name
    original_stem = str(match.group("stem") or "").strip()
    if not original_stem:
        return safe_name
    return f"{original_stem}{suffix}"


def get_display_name_for_source(path: Path | str) -> str:
    return get_original_filename_from_managed_name(Path(path).name)


def list_matching_chat_uploads(filename: str) -> list[Path]:
    ensure_managed_source_dirs()
    target_name = sanitize_filename(filename)
    validate_managed_source_suffix(target_name)
    matches = [
        candidate
        for candidate in chat_uploads_dir().iterdir()
        if candidate.is_file() and get_display_name_for_source(candidate) == target_name
    ]
    matches.sort(key=lambda candidate: (candidate.stat().st_mtime, candidate.name), reverse=True)
    return matches


def find_latest_matching_chat_upload(filename: str) -> Path | None:
    matches = list_matching_chat_uploads(filename)
    return matches[0] if matches else None


def import_chat_text_attachment(filename: str, content: str) -> Path:
    if not str(content).strip():
        raise ValueError("Uploaded text content is empty. Please re-upload the file.")

    target_path = build_chat_upload_path(filename)
    target_path.write_text(content, encoding="utf-8")
    return target_path


def import_chat_binary_attachment(filename: str, content: bytes) -> Path:
    if not content:
        raise ValueError("Uploaded file content is empty. Please re-upload the file.")

    target_path = build_chat_upload_path(filename)
    target_path.write_bytes(content)
    return target_path


def import_chat_base64_attachment(filename: str, content_base64: str) -> Path:
    if not str(content_base64).strip():
        raise ValueError("Uploaded file content is empty. Please re-upload the file.")

    try:
        payload = base64.b64decode(content_base64, validate=True)
    except Exception as exc:  # pragma: no cover - exact exception type depends on decoder
        raise ValueError("Uploaded file content is invalid base64.") from exc
    return import_chat_binary_attachment(filename, payload)
