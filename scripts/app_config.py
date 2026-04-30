from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aigc_round_service import normalize_prompt_profile
from llm_client import normalize_api_type

APP_DIR_NAME = "BaibaiAIGC"
CONFIG_FILE_NAME = "config.json"
DEFAULT_MODEL_CONFIG = {
    "baseUrl": "",
    "apiKey": "",
    "model": "",
    "apiType": "chat_completions",
    "temperature": 0.7,
    "offlineMode": False,
    "promptProfile": "cn",
}


def get_app_config_dir() -> Path:
    base_dir = os.getenv("APPDATA")
    if base_dir:
        return Path(base_dir) / APP_DIR_NAME
    return Path.home() / ".baibaiaigc"


def get_app_config_path() -> Path:
    return get_app_config_dir() / CONFIG_FILE_NAME


def normalize_model_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = config or {}
    base_url = str(payload.get("baseUrl", DEFAULT_MODEL_CONFIG["baseUrl"])).strip()
    api_key = str(payload.get("apiKey", DEFAULT_MODEL_CONFIG["apiKey"])).strip()
    model = str(payload.get("model", DEFAULT_MODEL_CONFIG["model"])).strip()
    try:
        temperature = float(payload.get("temperature", DEFAULT_MODEL_CONFIG["temperature"]))
    except (TypeError, ValueError):
        temperature = float(DEFAULT_MODEL_CONFIG["temperature"])

    return {
        "baseUrl": base_url,
        "apiKey": api_key,
        "model": model,
        "apiType": normalize_api_type(str(payload.get("apiType", "") or ""), base_url),
        "temperature": temperature,
        "offlineMode": bool(payload.get("offlineMode", DEFAULT_MODEL_CONFIG["offlineMode"])),
        "promptProfile": normalize_prompt_profile(payload.get("promptProfile", DEFAULT_MODEL_CONFIG["promptProfile"])),
    }


def load_app_config() -> dict[str, Any]:
    path = get_app_config_path()
    if not path.exists():
        return dict(DEFAULT_MODEL_CONFIG)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return dict(DEFAULT_MODEL_CONFIG)
    if not raw.strip():
        return dict(DEFAULT_MODEL_CONFIG)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return dict(DEFAULT_MODEL_CONFIG)
    if not isinstance(data, dict):
        return dict(DEFAULT_MODEL_CONFIG)
    return normalize_model_config(data)


def save_app_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_model_config(config)
    path = get_app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized