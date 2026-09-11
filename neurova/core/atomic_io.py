# -*- coding: utf-8 -*-
"""原子文本落盘（审计 2026-09-11 DATA-P1-2）。

tmp + ``os.replace`` 语义：写盘中途崩溃/断电不会留下半截 JSON——
半截文件会让 ``_load`` 静默清空内存态并在下次保存时覆盖真数据（整库丢失）。
同损坏隔离（``quarantine_corrupt_file``）配套使用。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Union


def atomic_write_text(path: Union[str, Path], text: str, *, encoding: str = "utf-8") -> None:
    """先写同目录 .tmp 再原子替换；同一文件系统内 replace 是原子的。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(str(tmp), str(p))


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
