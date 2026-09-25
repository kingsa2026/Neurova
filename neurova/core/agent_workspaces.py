# -*- coding: utf-8 -*-
"""agent 工作区根目录的唯一装配点。

此前 13 处各自拼这个根（__file__ 反推 / CWD 相对 / 字面 ".." 三派口径），而
neurova/api/app.py 据此建默认 Agent——测试用 TestClient 起 app 就会打开并写入
真实 agent_workspaces/。一律经本模块取根，NEUROVA_AGENT_WORKSPACES_DIR 可注入
（测试期由 tests/conftest.py 指向临时目录，桌面部署可指向用户数据目录）。
"""
from __future__ import annotations

import os
from pathlib import Path

AGENT_WORKSPACES_ENV = "NEUROVA_AGENT_WORKSPACES_DIR"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_AGENT_ID = "default"


def get_agent_workspaces_root() -> Path:
    """agent 工作区根目录（调用时解析，注入才对子线程与延迟装配生效）"""
    injected = os.environ.get(AGENT_WORKSPACES_ENV)
    return Path(injected) if injected else _PROJECT_ROOT / "agent_workspaces"


def get_agent_workspace_dir(agent_id: str = "") -> Path:
    """单个 agent 的工作区目录（agent_id 空值回落 default）"""
    return get_agent_workspaces_root() / (agent_id or _DEFAULT_AGENT_ID)
