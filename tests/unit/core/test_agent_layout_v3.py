# -*- coding: utf-8 -*-
"""agent 数据布局 v3（2026-11-24 拍板）：`data/agent/<属主桶>/<agent_id>/`。

- 有属主 agent → `data/agent/<user_id>/<agent_id>/`；
- 共享（管理员指定/无属主）→ `data/agent/share/<agent_id>/`；
- 未迁移的 v2 遗留（`data/<agent_id>/`）继续可解析（兼容，直到被扫描迁走）；
- agent_id→桶 的持久化索引是文件系统分区的判据单源（data/agent/index.json）；
- 隔离根（NEUROVA_AGENT_WORKSPACES_DIR 注入）保持平铺——隔离边界即注入本身。
"""
from __future__ import annotations

import json

import pytest

from neurova.core.agent_workspaces import (
    SHARE_BUCKET,
    agent_exists,
    get_agent_root,
    get_agent_root_dir,
    set_agent_owner,
    clear_agent_owner,
    agent_owner_index_path,
)


@pytest.fixture()
def prodRoot(tmp_path, monkeypatch):
    """生产形态：无任何注入，数据根=tmp/data（v3 分区在此之下）。"""
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)
    monkeypatch.delenv("NEUROVA_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _register(prodRoot, agent_id: str, owner: str = "") -> None:
    reg = prodRoot / "agents" / "agents.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if reg.exists():
        raw = json.loads(reg.read_text(encoding="utf-8")) or {}
    raw[agent_id] = {"name": agent_id}
    reg.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    if owner:
        set_agent_owner(agent_id, owner)


def test_owned_agent_root_lands_under_user_bucket(prodRoot):
    _register(prodRoot, "kai", owner="u1")
    assert get_agent_root_dir("kai") == prodRoot / "agent" / "u1" / "kai"


def test_shared_agent_root_lands_in_share_bucket(prodRoot):
    _register(prodRoot, "pub", owner="share")
    assert get_agent_root_dir("pub") == prodRoot / "agent" / "share" / "pub"
    assert SHARE_BUCKET == "share"


def test_default_agent_lives_in_share_bucket(prodRoot):
    """default 入 share 桶：索引写入后按 v3 解析；未写入前保持 v2 位（兼容）。"""
    legacy = prodRoot / "default"
    legacy.mkdir(parents=True)
    assert get_agent_root_dir("default") == legacy
    set_agent_owner("default", "share")
    assert get_agent_root_dir("default") == prodRoot / "agent" / "share" / "default"


def test_legacy_v2_dir_still_resolves_until_migrated(prodRoot):
    """未迁移的 v2 平铺目录继续可解析（兼容），迁移扫走后才切 v3。"""
    legacy = prodRoot / "old_agent"
    legacy.mkdir(parents=True)
    (legacy / "agent_config.json").write_text("{}", encoding="utf-8")
    assert get_agent_root_dir("old_agent") == legacy


def test_new_agent_without_index_entry_goes_to_share_bucket(prodRoot):
    """登记在册但索引尚无条目（且无 v2 目录）→ 兜底进 share 桶，绝不回顶层。"""
    _register(prodRoot, "fresh", owner="")
    root = get_agent_root_dir("fresh")
    assert root == prodRoot / "agent" / "share" / "fresh"


def test_unknown_agent_stays_rejected_by_write_gate(prodRoot, tmp_path):
    """未知 id：路径候选保持旧位，但写路径门依旧拒绝（顶层零新增）。"""
    from neurova.session_manager import SessionManager

    assert agent_exists("ghost") is False
    assert get_agent_root_dir("ghost") == prodRoot / "ghost"
    sm = SessionManager()
    with pytest.raises(Exception):
        sm.save_message("ghost", "s1", "user", "hi", user_id="u1")
    assert not (prodRoot / "ghost").exists()


def test_index_updates_and_persists(prodRoot):
    _register(prodRoot, "kai", owner="u1")
    path = agent_owner_index_path()
    assert path == prodRoot / "agent" / "index.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["agents"]["kai"]["bucket"] == "u1"

    clear_agent_owner("kai")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "kai" not in raw["agents"]
    # 清掉索引后：登记在册、无 v2 目录 → 兜底 share 桶
    assert get_agent_root_dir("kai") == prodRoot / "agent" / "share" / "kai"


def test_index_rejects_reserved_and_bad_ids():
    with pytest.raises(ValueError):
        set_agent_owner("knowledge", "u1")
    with pytest.raises(ValueError):
        set_agent_owner("../escape", "u1")
