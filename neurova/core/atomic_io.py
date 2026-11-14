# -*- coding: utf-8 -*-
"""原子文本落盘（审计 2026-09-11 DATA-P1-2）。

tmp + ``os.replace`` 语义：写盘中途崩溃/断电不会留下半截 JSON——
半截文件会让 ``_load`` 静默清空内存态并在下次保存时覆盖真数据（整库丢失）。
同损坏隔离（``quarantine_corrupt_file``）配套使用。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def atomic_write_text(path: Union[str, Path], text: str, *, encoding: str = "utf-8") -> None:
    """先写同目录 .tmp 再原子替换；同一文件系统内 replace 是原子的。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(str(tmp), str(p))


def loadJsonStore(path: Union[str, Path], default: Any) -> Any:
    """读取 JSON 持久化库文件；缺失/损坏/顶层非对象一律返回 ``default``。

    全仓 JSON 库文件读口径单源（P2-26）：文件不存在按"还没有数据"返回默认值；
    解析失败以 warning 点名文件与原因（不静默装作没配过），也返回默认值，
    是否把损坏文件隔离交由调用方结合 :func:`quarantine_corrupt_file` 决定。
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as exc:  # noqa: BLE001
        logger.warning("JSON store unreadable, fallback to default: %s (%s)", p, exc)
        return default
    if isinstance(raw, dict):
        return raw
    logger.warning("JSON store top-level is not an object, fallback to default: %s", p)
    return default


def saveJsonStore(path: Union[str, Path], data: Any) -> None:
    """原子写 JSON 持久化库文件（同目录 .tmp 中转 + ``os.replace`` 原子替换）。

    全仓 JSON 库文件写口径单源（P2-26）：序列化格式统一
    ``ensure_ascii=False, indent=2``，落盘语义与 :func:`atomic_write_text` 一致。
    """
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def quarantine_corrupt_file(path: Union[str, Path]) -> str:
    """把解析失败的文件改名隔离（保留现场供人工恢复），返回隔离路径。

    防线语义：损坏文件绝不能留在原路径——否则下次成功加载前的任何
    ``_save`` 都会用内存空态覆盖它。
    """
    p = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    quarantined = p.with_name(f"{p.name}.corrupt-{stamp}")
    try:
        os.replace(str(p), str(quarantined))
    except OSError:
        # 改名失败（被占用等）只能原地保留；调用方日志会带上下文
        return str(p)
    return str(quarantined)
