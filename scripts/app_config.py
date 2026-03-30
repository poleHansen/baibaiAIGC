from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_DIR_NAME = "BaibaiAIGC"
CONFIG_FILE_NAME = "config.json"


def get_app_config_dir() -> Path:
    base_dir = os.getenv("APPDATA")
    if base_dir:
        return Path(base_dir) / APP_DIR_NAME
    return Path.home() / ".baibaiaigc"


def get_app_config_path() -> Path:
    return get_app_config_dir() / CONFIG_FILE_NAME


def load_app_config() -> dict[str, Any]:
    path = get_app_config_path()
    if not path.exists():
        return {
            "baseUrl": "",
            "apiKey": "",
            "model": "",
            "apiMode": "responses",
            "temperature": 0.7,
            "offlineMode": False,
            "promptProfile": "cn",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "baseUrl": str(data.get("baseUrl", "")),
        "apiKey": str(data.get("apiKey", "")),
        "model": str(data.get("model", "")),
        "apiMode": str(data.get("apiMode", "responses") or "responses").strip().lower(),
        "temperature": float(data.get("temperature", 0.7)),
        "offlineMode": bool(data.get("offlineMode", False)),
        "promptProfile": str(data.get("promptProfile", "cn") or "cn"),
    }


def save_app_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "baseUrl": str(config.get("baseUrl", "")).strip(),
        "apiKey": str(config.get("apiKey", "")).strip(),
        "model": str(config.get("model", "")).strip(),
        "apiMode": str(config.get("apiMode", "responses") or "responses").strip().lower(),
        "temperature": float(config.get("temperature", 0.7)),
        "offlineMode": bool(config.get("offlineMode", False)),
        "promptProfile": str(config.get("promptProfile", "cn") or "cn").strip().lower(),
    }
    path = get_app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized
