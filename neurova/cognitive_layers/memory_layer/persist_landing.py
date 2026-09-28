# -*- coding: utf-8 -*-
"""记忆持久层的落点**配对**：主库与它的持久库是一对，落点只在这里推导。

## 为什么收这一处（Issue #290 未闭环项④ 的根因）

记忆持久层不是单个文件：`MemoryManager` 拿 `db_path` 当**主库**，另在同目录
配一个持久库，而真行写进的是后者（`_persist_memory` → `_persist_db_path`；
`_load_from_db` 也只读它）。主库因此更像一个"壳"。

配对关系原先只写在 `manager._init_persistence_db()` 里（装配时才拼一次）。
换锚救济（`dataLanding` 一族的收养）按**单文件**语义工作，于是只搬走了壳，
真存量留在旧锚点 —— 症状与"没搬"逐字相同（种子记忆不可见），
而所有"旧物已搬走"的断言都还是绿的。

故把"配对"本身收成这里的单点：写入端与收养端共用，谁都不许再拼一遍文件名。
"""

from __future__ import annotations

from pathlib import Path

#: 持久库的法定名字（与主库同目录）。写入端与收养端共用这一份。
PERSIST_COMPANION_NAME = "neurova_memories_persist.db"


def persistCompanionPath(mainDbPath: "str | Path") -> Path:
    """主库 → 同目录持久库的落点（配对规则的唯一推导）。"""
    return Path(mainDbPath).with_name(PERSIST_COMPANION_NAME)
