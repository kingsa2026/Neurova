# -*- coding: utf-8 -*-
"""时间戳单源（P2-27）。

全仓 ISO 时间戳只允许从这里取：``nowIso()`` = 当前 UTC 时间的
``datetime.isoformat()``。各模块此前自抄的 ``_now``/``_now_iso`` 两行实现，
凡与本项目标逐字相同者一律改为 ``from neurova.core.time_utils import nowIso as _now``
委托；格式或语义有差异者（``timespec="seconds"``、``time.monotonic()``、
``time.time()`` 浮点 epoch 等）保留原地，不强行归一。
"""
from __future__ import annotations

from datetime import datetime, timezone


def nowIso() -> str:
    """当前 UTC 时间的 ISO-8601 字符串（与历史 ``_now``/``_now_iso`` 同语义）。"""
    return datetime.now(timezone.utc).isoformat()
