from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from aigc_round_service import normalize_prompt_profile
from workspace_paths import get_data_root, has_data_root

APP_DIR_NAME = "BaibaiAIGC"
CONFIG_FILE_NAME = "config.json"
DEFAULT_MODEL_CONFIG = {
    "baseUrl": "",
    "apiKey": "",
    "model": "",
    "temperature": 0.7,
    "offlineMode": False,
    "promptProfile": "cn",
}


def get_app_config_dir() -> Path:
    if has_data_root():
        return get_data_root()
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
        "temperature": temperature,
        "offlineMode": bool(payload.get("offlineMode", DEFAULT_MODEL_CONFIG["offlineMode"])),
        "promptProfile": normalize_prompt_profile(payload.get("promptProfile", DEFAULT_MODEL_CONFIG["promptProfile"])),
    }


def _load_raw_config() -> dict[str, Any]:
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


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def load_app_config() -> dict[str, Any]:
    config = _load_raw_config()
    return {**config, "apiKey": mask_api_key(config["apiKey"])}


def resolve_model_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_model_config(config)
    if "****" in normalized["apiKey"]:
        saved_key = _load_raw_config()["apiKey"]
        if not saved_key or normalized["apiKey"] != mask_api_key(saved_key):
            raise ValueError("保存的模型密钥已变化，请重新加载设置或输入新的密钥。")
        normalized["apiKey"] = saved_key
    return normalized


def save_app_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = dict(config)
    if not str(payload.get("apiKey", "")).strip():
        payload["apiKey"] = _load_raw_config()["apiKey"]
    normalized = resolve_model_config(payload)
    path = get_app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**normalized, "apiKey": mask_api_key(normalized["apiKey"])}
