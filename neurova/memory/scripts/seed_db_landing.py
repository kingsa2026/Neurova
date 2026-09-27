# -*- coding: utf-8 -*-
"""种子记忆库（`yi_ling_memory.db`）的落点单点。

## 为什么单开这一处

数据根换锚（`721ef038`）之后，本目录八个脚本各自把落点写成
`get_data_root() / "yi_ling_memory.db"` —— 新落点是对的，但**换锚前的存量
没被搬**：旧锚点是 `neurova/memory/data/yi_ling_memory.db`（`Path(__file__)
.parent.parent / "data"`），换锚后无人再读它，于是 `init_db.py` / `init_memories.py`
一跑就新建一个空库，"种子记忆不可见"。

八个脚本若各写一遍 `legacy=(...)`，就是八份旧锚点定义（AGENTS.md 第 6 条禁的
第二份源）；故收口到本模块一处，八个脚本一律经 `seedDbPath()` 取落点。
"""

from __future__ import annotations

from pathlib import Path

#: 换锚前的落点（相对仓库根）：八个种子脚本按 `__file__` 反推出的那个 `data/`。
LEGACY_SEED_PARTS = ("neurova", "memory", "data", "yi_ling_memory.db")


def seedDbPath() -> Path:
    """种子记忆库落点：数据根下，空缺时收养换锚前的包内旧物一次。

    收养语义与全仓一致（见 `core/data_root.py::adoptLegacyLanding`）：
    新落点已在则不覆盖、旧物不存在则无操作、搬迁失败只告警不抛。
    """
    from neurova.core.data_root import dataLanding

    return dataLanding("yi_ling_memory.db", legacy=LEGACY_SEED_PARTS)
