# -*- coding: utf-8 -*-
"""工作区文件面建目录门（2026-11-24 审计 RISK 1）：未知 agent 一律 404，
**先校验后建目录**——旧实现 mkdir 在鉴权之前，任意登录用户拿任意 id 即使
被 403 也已把 data/<agent_id>/workspaces/ 建出来了。

conftest 把 agent 根隔离到 NEUROVA_AGENT_WORKSPACES_DIR（生产形态=数据根），
故断言以 `get_agent_root()` 为准。
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from neurova.api.endpoints.workspace_files import _workspace_root
from neurova.core.agent_workspaces import get_agent_root


def _register(agent_id: str) -> None:
    reg = get_agent_root() / "agents" / "agents.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if reg.exists():
        raw = json.loads(reg.read_text(encoding="utf-8")) or {}
    raw[agent_id] = {"name": agent_id}
    reg.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def test_unknown_agent_404_and_no_dir():
    with pytest.raises(HTTPException) as ei:
        _workspace_root("ghost", {"user_id": "u1", "role": "user"})
    assert ei.value.status_code == 404
    assert not (get_agent_root() / "ghost").exists(), "未知 agent 不得建出工作区目录"


def test_registered_agent_returns_workspace_dir():
    _register("kai")
    root = _workspace_root("kai", {"user_id": "u1", "role": "user"})
    assert root == get_agent_root() / "kai" / "workspaces"


def test_default_agent_allowed():
    root = _workspace_root("default", {"user_id": "u1", "role": "user"})
    assert root == get_agent_root() / "default" / "workspaces"
