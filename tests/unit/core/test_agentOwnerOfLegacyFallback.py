# -*- coding: utf-8 -*-
"""CORE-01：旧 agent（无 agent_config.json）的属主回退必须走索引单源。

根因：`agent_owner_of()` 的回退分支调用 `load_agent_owner_index()`，而该名字只出现在
`migrate_agent_layout_v3()` 的局部 import 里——模块顶层从未导入它。旧 agent 无配置
owner 时，管理员布局扫描、取消共享、CLI 定向迁移都会直接抛 NameError。
"""
from __future__ import annotations

from neurova.core.agent_workspaces import save_agent_owner_index


def testLegacyAgentWithoutConfigFallsBackToOwnerIndex(tmp_path, monkeypatch):
    """旧 agent 仅登记在索引里（无 agent_config.json）→ 属主取索引值，不抛 NameError。"""
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    save_agent_owner_index({"oldone": {"bucket": "u7", "owner": "u7"}})

    from neurova.core.agent_layout_migration import agent_owner_of

    assert agent_owner_of("oldone") == "u7"