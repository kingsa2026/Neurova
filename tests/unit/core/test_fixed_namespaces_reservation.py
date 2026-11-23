# -*- coding: utf-8 -*-
"""数据根固定命名空间保留名判据（2026-11-23 拍板）。

`data/` 下由各子系统占用的顶层目录名（collaboration / training_datasets /
archive / benchmark / swarm_runs / logs / anchors / constitution /
injection_ledgers 等）一律**保留**：

- agent id 不得与之同名（创建即拒绝）；
- agent 布局迁移**不得**把它们当 agent 根扫描/搬移/重写——启动迁移的
  全量重扫只允许落在真实 agent 根上。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from neurova.core.agent_layout_migration import migrate_legacy_agent_layout
from neurova.core.agent_workspaces import (
    RESERVED_AGENT_ROOT_NAMES,
    get_agent_root_dir,
    is_agent_root,
    is_reserved_agent_id,
)

#: 本批新钉的固定命名空间（含既有的 collaboration 作回归锚）。
FIXED_NAMESPACES = [
    "collaboration",
    "training_datasets",
    "archive",
    "benchmark",
    "swarm_runs",
    "logs",
    "anchors",
    "constitution",
    "injection_ledgers",
    "knowledge_ingest",
    "quality",
    "request_archives",
    "shutdown",
]


@pytest.mark.parametrize("name", FIXED_NAMESPACES)
def test_fixed_namespace_is_reserved(name):
    assert name in RESERVED_AGENT_ROOT_NAMES
    assert is_reserved_agent_id(name)
    with pytest.raises(ValueError):
        get_agent_root_dir(name)


@pytest.mark.parametrize("name", FIXED_NAMESPACES)
def test_discovery_never_treats_fixed_namespace_as_agent_root(tmp_path, monkeypatch, name):
    """即便固定命名空间里出现 agent 根标记（如 sessions/），发现侧也必须拒绝。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    markerDir = tmp_path / "data" / name
    (markerDir / "sessions").mkdir(parents=True)
    (markerDir / "sessions" / "session_x.json").write_text("{}", encoding="utf-8")
    assert is_agent_root(markerDir) is False


def test_migration_never_scans_fixed_namespaces(tmp_path, monkeypatch):
    """启动迁移的全量重扫不得进入固定命名空间；真实 agent 旧面照常迁移。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    data = tmp_path / "data"

    # 固定命名空间里放"长得像待迁移旧物"的文件：迁移前后必须一字不动。
    trainingSession = data / "training_datasets" / "ds1" / "sessions" / "session_s.json"
    trainingSession.parent.mkdir(parents=True)
    trainingSession.write_text('{"legacy": "E:\\\\old\\\\agent_workspaces\\\\kai"}', encoding="utf-8")
    roomLog = data / "collaboration" / "rooms" / "project_x" / "messages.jsonl"
    roomLog.parent.mkdir(parents=True)
    roomLog.write_text('{"content": "hi"}\n', encoding="utf-8")

    # 真实 agent 旧面（照常迁移，证明迁移本身没被关掉）。
    legacyWs = tmp_path / "legacy_ws"
    (legacyWs / "kai").mkdir(parents=True)
    (legacyWs / "kai" / "agent_config.json").write_text('{"name": "Kai"}', encoding="utf-8")
    (data / "sessions" / "kai").mkdir(parents=True)
    (data / "sessions" / "kai" / "session_s1_2026-01-01.json").write_text("{}", encoding="utf-8")

    report = migrate_legacy_agent_layout(legacy_workspace_root=legacyWs)

    assert trainingSession.read_text(encoding="utf-8") == '{"legacy": "E:\\\\old\\\\agent_workspaces\\\\kai"}'
    assert roomLog.read_text(encoding="utf-8") == '{"content": "hi"}\n'
    touched = {m["source"] for m in report["moved"]} | {m["source"] for m in report["conflicts"]}
    assert not any("training_datasets" in s or "collaboration" in s for s in touched)
    assert (data / "kai" / "sessions" / "session_s1_2026-01-01.json").exists(), (
        "真实 agent 的旧会话必须照常迁入新布局"
    )
