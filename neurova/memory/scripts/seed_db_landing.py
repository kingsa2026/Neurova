# -*- coding: utf-8 -*-
"""种子记忆库（`yi_ling_memory.db`）的落点单点 —— 它是**一对文件**，整对搬。

## 为什么单开这一处

数据根换锚（`721ef038`）之后，本目录八个脚本各自把落点写成
`get_data_root() / "yi_ling_memory.db"` —— 新落点是对的，但**换锚前的存量
没被搬**：旧锚点是 `neurova/memory/data/yi_ling_memory.db`（`Path(__file__)
.parent.parent / "data"`），换锚后无人再读它，于是 `init_db.py` / `init_memories.py`
一跑就新建一个空库，"种子记忆不可见"。

八个脚本若各写一遍 `legacy=(...)`，就是八份旧锚点定义（AGENTS.md 第 6 条禁的
第二份源）；故收口到本模块一处，八个脚本一律经 `seedDbPath()` 取落点。

## 一对文件，不是单个（2026-09-28 实测补齐）

`MemoryManager` 拿这个路径当**主库**，另在同目录配一个持久库，而真行写进的是
后者（`_persist_memory` → `_persist_db_path`）。只搬主库等于搬了个空壳：
新锚点看着有文件、`_load_from_db()` 读到 0 行，症状与"完全没搬"一模一样。
故 `seedDbPath()` 按**配对**收养：主库空缺时收养主库，持久库空缺时收养持久库，
两份各自独立判"空缺才收养"（任一份已有就不动它，冲突按既有口径点名）。
"""

from __future__ import annotations

from pathlib import Path

from neurova.core.data_root import adoptLandingFrom, dataLanding, legacyLanding
from neurova.cognitive_layers.memory_layer.persist_landing import (
    PERSIST_COMPANION_NAME,
    persistCompanionPath,
)

#: 换锚前的落点（相对仓库根）：八个种子脚本按 `__file__` 反推出的那个 `data/`。
#: 主库名也在这里给一次，供配对推导与八个脚本引用同一份（不许各自抄一遍）。
SEED_DB_NAME = "yi_ling_memory.db"
LEGACY_SEED_PARTS = ("neurova", "memory", "data", SEED_DB_NAME)

__all__ = [
    "LEGACY_SEED_PARTS",
    "PERSIST_COMPANION_NAME",
    "SEED_DB_NAME",
    "legacySeedDir",
    "seedDbPath",
]


def legacySeedDir() -> Path:
    """换锚前的目录（旧主库与旧持久库都在这里）。

    经 `legacyLanding()` 取（**不是** `from ... import repoRoot` 再自己拼）：
    后者拿到的是绑定在导入时刻的函数引用，仓库根被替换时它照样指向老地方。
    """
    return legacyLanding(*LEGACY_SEED_PARTS[:-1])


def seedDbPath() -> Path:
    """种子记忆库落点：数据根下，空缺时收养换锚前的**一对**包内旧物。

    收养语义与全仓一致（见 `core/data_root.py::adoptLegacyLanding`）：
    新落点已在则不覆盖、旧物不存在则无操作、搬迁失败只告警不抛。
    配对的两半各自独立判空缺 —— 只到了一份的情况在真实机器上会遇见
    （旧版本只写过主库），此时搬到的就是一份、不凭空补齐另一半。
    """
    target = dataLanding(SEED_DB_NAME, legacy=LEGACY_SEED_PARTS)
    legacy_dir = legacySeedDir()
    adoptLandingFrom(
        persistCompanionPath(target),
        legacy_dir / PERSIST_COMPANION_NAME,
    )
    return target
