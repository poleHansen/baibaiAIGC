"""原子写 JSON 文件，以及读不出来时不炸的读取。

运行中的任务会持续改写进度文件（progress / records），前端同时在轮询历史接口。
直接 `Path.write_text()` 会先把文件截断成 0 字节再写，并发读取正好落在截断窗口里，
`json.loads("")` 就抛 `Expecting value: line 1 column 1 (char 0)`，接口变成 400。

这里的做法：写到同目录的临时文件，`os.replace` 覆盖。同一文件系统上 rename 是原子的，
读取方看到的要么是旧内容，要么是新内容，不会是空文件。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

# Windows 上目标文件被别的句柄打开时 os.replace 会失败（Linux 上不会，
# 因为 rename 只换目录项，已打开的读句柄仍读旧 inode）。退避重试，
# 实在抢不到就直接写：宁可退回旧行为，也不要让一次保存失败把整轮跑挂。
_REPLACE_RETRIES = 10
_REPLACE_RETRY_DELAY = 0.05


def atomic_write_text(path: Path, text: str) -> None:
    """原子覆盖写入文本，中途失败不会留下半截文件。"""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp 建的是 0600，恢复成普通文件权限，方便宿主机排查数据。
        try:
            os.chmod(tmp_path, 0o644)
        except OSError:
            pass
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    # 只有 Windows 会走到这里；退回直接写，保证调用方不失败。
                    path.write_text(text, encoding="utf-8")
                    tmp_path.unlink(missing_ok=True)
                    return
                time.sleep(_REPLACE_RETRY_DELAY)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """按项目现有格式（UTF-8、缩进 2、不转义中文）原子写入 JSON。"""

    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json_or_none(path: Path) -> Any | None:
    """读取 JSON；文件不存在、为空、内容损坏一律返回 None。

    用于“读不到就当没有”的场景（历史列表、进度摘要），不要用于必须报错的地方。
    """

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
