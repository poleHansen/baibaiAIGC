from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

# 代码与静态资源（prompts、SKILL.md）永远在代码仓库里。
CODE_ROOT = Path(__file__).resolve().parents[1]

# 用户数据根。Web 多租户模式下由私有认证层在请求开始时设置；
# 桌面 / CLI 模式下不设置，回退到代码根，保持原有行为。
_data_root: ContextVar[Path | None] = ContextVar("baibaiaigc_data_root", default=None)


def set_data_root(root: str | Path):
    return _data_root.set(Path(root).resolve())


def reset_data_root(token) -> None:
    _data_root.reset(token)


def has_data_root() -> bool:
    """当前是否显式设置了数据根。桌面端和 CLI 永远为 False。"""
    return _data_root.get() is not None


def get_data_root() -> Path:
    root = _data_root.get()
    if root is None:
        return CODE_ROOT
    return root


def get_code_root() -> Path:
    return CODE_ROOT


def origin_dir() -> Path:
    return get_data_root() / "origin"


def finish_dir() -> Path:
    return get_data_root() / "finish"


def records_path() -> Path:
    return finish_dir() / "aigc_records.json"


def intermediate_dir() -> Path:
    return finish_dir() / "intermediate"


def web_export_dir() -> Path:
    return finish_dir() / "web_exports"
