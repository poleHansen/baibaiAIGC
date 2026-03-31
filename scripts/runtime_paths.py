from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "BaibaiAIGC"
ENV_RESOURCE_ROOT = "BAIBAIAIGC_RESOURCE_ROOT"
ENV_DATA_ROOT = "BAIBAIAIGC_DATA_ROOT"


def _normalize_windows_extended_path(path: str) -> str:
    if os.name != "nt":
        return path

    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]

    if path.startswith("\\\\?\\"):
        return path[4:]

    return path


def _resolve_path(path: Path) -> Path:
    normalized = Path(_normalize_windows_extended_path(str(path)))
    return normalized.resolve()


def _script_root() -> Path:
    return _resolve_path(Path(__file__)).parents[1]


def _looks_like_resource_root(path: Path) -> bool:
    return (
        (path / "prompts").exists()
        or (path / "scripts").exists()
        or (path / "references").exists()
    )


def default_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        parent_dir = executable_dir.parent
        grand_parent_dir = parent_dir.parent if parent_dir else None
        candidates = [
            executable_dir / "_up_" / "_up_",
            executable_dir / "_up_",
            executable_dir,
            executable_dir / "resources",
            parent_dir / "resources",
            parent_dir / "_up_" / "_up_",
            parent_dir / "_up_",
            parent_dir,
        ]
        if grand_parent_dir is not None:
            candidates.append(grand_parent_dir / "_up_")
            candidates.append(grand_parent_dir / "resources")

        for candidate in candidates:
            if _looks_like_resource_root(candidate):
                return _resolve_path(candidate)
        return executable_dir
    return _script_root()


def get_resource_root() -> Path:
    configured = os.getenv(ENV_RESOURCE_ROOT, "").strip()
    if configured:
        return _resolve_path(Path(configured))
    return default_resource_root()


def default_data_root() -> Path:
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".baibaiaigc"


def get_data_root() -> Path:
    configured = os.getenv(ENV_DATA_ROOT, "").strip()
    if configured:
        return _resolve_path(Path(configured))
    return default_data_root()


def get_origin_dir() -> Path:
    return get_data_root() / "origin"


def get_finish_dir() -> Path:
    return get_data_root() / "finish"


def get_intermediate_dir() -> Path:
    return get_finish_dir() / "intermediate"


def get_web_exports_dir() -> Path:
    return get_finish_dir() / "web_exports"


def get_prompt_path(relative_path: str) -> Path:
    return get_resource_root() / relative_path


def ensure_app_dirs() -> None:
    for path in (get_data_root(), get_origin_dir(), get_finish_dir(), get_intermediate_dir(), get_web_exports_dir()):
        path.mkdir(parents=True, exist_ok=True)