"""删除 Agent 彻底性回归测试

背景（用户报告）：通过前端 UI 删除 agent 后，agent_workspaces/{id} 与 data/{id}
存在残留，服务重启后 _load_saved_agents 自动重建配置，幽灵 agent 复活且加载异常。

根因：
1. Agent.shutdown 是 async def，但 delete_agent 端点同步调用——协程被丢弃，
   Agent 资源（SQLite/引擎句柄）从不释放；
2. 随后 shutil.rmtree(..., ignore_errors=True) 在 Windows 上对被锁文件静默失败，
   工作目录只剩一半；
3. agent_core._init_cognitive_graph 在 data/{agent_id} 创建的认知图谱目录
   （memory.db）从不被清理。

本测试固定三条行为：协程必须真正执行；工作目录必须删干净（含重试）；
data/{agent_id} 必须一并清理（但共享目录 data/agents 受保护）。
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fastapi import Request

from neurova.agent_config import reset_config_manager
from neurova.api.endpoints import agent as agent_module
from neurova.api.endpoints import set_app_state


class _FakeAgentConfig:
    def __init__(self, agent_id: str, workspace_path: str):
        self.agent_id = agent_id
        self.workspace_path = workspace_path
        self.name = "ghost"


class FakeAgent:
    """模拟真实 Agent：agent_core.Agent.shutdown 是 async def，调用返回协程。"""

    def __init__(self, agent_id: str, workspace_path: str):
        self.config = _FakeAgentConfig(agent_id, workspace_path)
        self.shutdown_awaited = False

    def shutdown(self):
        async def _shutdown():
            self.shutdown_awaited = True

        return _shutdown()


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """CWD 切到临时目录：生产代码中 data/{agent_id} 与 data/agents 均为 CWD 相对路径，
    测试据此把副作用隔离在 tmp_path，绝不触碰真实 data/。"""
    monkeypatch.chdir(tmp_path)
    reset_config_manager()
    set_app_state(None)
    yield tmp_path
    set_app_state(None)
    reset_config_manager()


def _make_ghost(isolated_env: Path, agent_id: str) -> tuple[FakeAgent, Path, Path]:
    """构造一个带完整落盘痕迹的 agent：workspace（含 memory 子树）+ data/{id} 认知图谱目录"""
    tmp = isolated_env
    workspace = tmp / "agent_workspaces" / agent_id
    (workspace / "memory" / "attachments").mkdir(parents=True)
    (workspace / "agent_config.json").write_text(
        json.dumps({"name": "ghost"}), encoding="utf-8"
    )
    (workspace / "memory" / "memory.db").write_bytes(b"SQLite format 3")
    (workspace / "memory" / "attachments" / "a.txt").write_text("x", encoding="utf-8")

    data_dir = tmp / "data" / agent_id
    data_dir.mkdir(parents=True)
    (data_dir / "memory.db").write_bytes(b"SQLite format 3")

    agent = FakeAgent(agent_id, str(workspace))
    set_app_state({"agents": {agent_id: agent}, "default_agent_id": "default"})
    return agent, workspace, data_dir


def _call_delete(agent_id: str):
    request = Request(scope={"type": "http", "method": "DELETE"})
    return asyncio.run(agent_module.delete_agent(request=request, agent_id=agent_id))


def test_delete_agent_actually_awaits_async_shutdown(isolated_env):
    """shutdown 协程必须被 await 执行，而不是被静默丢弃。"""
    agent, workspace, data_dir = _make_ghost(isolated_env, "ghost1")
    _call_delete("ghost1")
    assert agent.shutdown_awaited is True, (
        "delete_agent 同步调用了 async shutdown，协程未执行，Agent 资源未释放"
    )


def test_delete_agent_removes_workspace_completely(isolated_env):
    """工作目录（含 memory/attachments 子树）必须整体删除，否则重启后幽灵复活。"""
    _make_ghost(isolated_env, "ghost2")
    _call_delete("ghost2")
    assert not (isolated_env / "agent_workspaces" / "ghost2").exists()


def test_delete_agent_removes_cognitive_data_dir(isolated_env):
    """data/{agent_id}（认知图谱 memory.db）必须一并清理。"""
    _make_ghost(isolated_env, "ghost3")
    _call_delete("ghost3")
    assert not (isolated_env / "data" / "ghost3").exists()


def test_delete_agent_protects_shared_agents_data_dir(isolated_env):
    """agent_id 恰为 'agents' 时，绝不能删掉 AgentConfigManager 的 data/agents。"""
    tmp = isolated_env
    workspace = tmp / "agent_workspaces" / "agents"
    workspace.mkdir(parents=True)
    agents_json = tmp / "data" / "agents" / "agents.json"
    agents_json.parent.mkdir(parents=True)
    agents_json.write_text("{}", encoding="utf-8")

    agent = FakeAgent("agents", str(workspace))
    set_app_state({"agents": {"agents": agent}, "default_agent_id": "default"})
    _call_delete("agents")

    assert agents_json.exists(), "data/agents 是共享配置目录，不得随 agent 删除"


def test_workspace_removal_retries_on_transient_error(isolated_env, monkeypatch):
    """句柄释放滞后时（Windows 常见），删除应短暂重试而非 ignore_errors 静默放弃。"""
    _make_ghost(isolated_env, "ghost5")
    real_rmtree = shutil.rmtree
    calls = {"n": 0}

    def flaky_rmtree(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(f"first attempt locked: {path}")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(agent_module, "shutil", shutil)
    monkeypatch.setattr(shutil, "rmtree", flaky_rmtree)
    _call_delete("ghost5")
    assert not (isolated_env / "agent_workspaces" / "ghost5").exists()
    assert calls["n"] >= 2, "首次删除失败后应重试"


def test_delete_agent_reports_cleanup_status(isolated_env):
    """响应中应报告清理结果，前端/运维能感知半失败（文件被锁）的情况。"""
    _make_ghost(isolated_env, "ghost6")
    resp = _call_delete("ghost6")
    assert resp.get("code") == 0
    data = resp.get("data") or {}
    assert data.get("workspace_removed") is True
    assert data.get("agent_data_removed") is True
