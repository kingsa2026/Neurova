# -*- coding: utf-8 -*-
"""agent 工作区根目录的单源解析器（NEUROVA_AGENT_WORKSPACES_DIR）。

此前 13 处生产代码各自用 __file__ 反推 / CWD 相对 / 字面 ".." 拼同一个根，
其中 neurova/api/app.py 用它建默认 Agent——于是 tests/unit/api 里用 TestClient
起 app 的用例会打开并写入真实 agent_workspaces/default（实测该库行数在跑测
期间从 301 涨到 306）。收成唯一装配点后，测试期由 conftest 注入临时根。
"""
import os
from pathlib import Path

from neurova.core.agent_workspaces import (
    AGENT_WORKSPACES_ENV,
    get_agent_workspace_dir,
    get_agent_workspaces_root,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_AGENT_WORKSPACES = PROJECT_ROOT / "agent_workspaces"


def test_root_honors_injected_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(AGENT_WORKSPACES_ENV, str(tmp_path / "agentWs"))
    assert get_agent_workspaces_root() == tmp_path / "agentWs"


def test_root_defaults_to_repo_agent_workspaces(monkeypatch):
    monkeypatch.delenv(AGENT_WORKSPACES_ENV, raising=False)
    assert get_agent_workspaces_root() == REPO_AGENT_WORKSPACES


def test_agent_workspace_dir_joins_agent_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(AGENT_WORKSPACES_ENV, str(tmp_path))
    assert get_agent_workspace_dir("kai") == tmp_path / "kai"
    assert get_agent_workspace_dir("") == tmp_path / "default"


def test_root_pinned_out_of_repo_during_tests(tmp_path: Path):
    """防再污染：autouse 隔离失效时，app 级测试会打开真实 agent_workspaces。"""
    root = get_agent_workspaces_root()
    assert root != REPO_AGENT_WORKSPACES
    assert PROJECT_ROOT not in root.parents


def test_memory_manager_default_db_follows_injected_root(tmp_path: Path, monkeypatch):
    """记忆库默认路径由同一解析器供给：注入根之后不得再落到仓库工作区。"""
    from neurova.cognitive_layers.memory_layer.manager import _default_db_path_for

    ws_root = tmp_path / "agentWs"
    monkeypatch.setenv(AGENT_WORKSPACES_ENV, str(ws_root))

    db_path = Path(_default_db_path_for("scope_probe"))

    assert db_path == ws_root / "scope_probe" / "memory" / "memory.db"
    assert db_path.parent.is_dir()
