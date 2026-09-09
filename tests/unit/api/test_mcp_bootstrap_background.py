"""
MCP bootstrap 后台化测试

背景（启动性能 2026-09-09）：_on_startup 同步 await bootstrap_mcp()，npx 拉起
filesystem server 实测 13.6s，把 /health 就绪时间整体拖后。修复：改为
create_task 后台连接；完成后把已连接客户端补挂到启动期已存在 agent 的
ToolRouter（后台化后若不补挂，默认 agent 将永远拿不到 MCP 工具——原同步路径
同样存在此断链：agent init_tools 先于 bootstrap 完成，attach 时 _clients 为空）。
"""
import asyncio
import types

import pytest

import neurova.tool_layers.mcp_bootstrap as mcp_bootstrap_mod
from neurova.api.app import AppState, _schedule_mcp_bootstrap


class FakeRouter:
    def __init__(self):
        self.registered = []

    def register_mcp_client(self, server_id, client):
        self.registered.append((server_id, client))


@pytest.fixture
def fake_clients(monkeypatch):
    clients = {"filesystem": object()}
    monkeypatch.setattr(mcp_bootstrap_mod, "_clients", clients)
    monkeypatch.setattr(mcp_bootstrap_mod, "_bootstrapped", False)
    return clients


def test_bootstrap_does_not_block_startup(monkeypatch, fake_clients):
    """bootstrap_mcp 未完成时 _schedule_mcp_bootstrap 已返回，不阻塞事件循环"""
    release = asyncio.Event()
    calls = []

    async def fake_bootstrap():
        calls.append(1)
        await release.wait()
        return {"filesystem": True}

    monkeypatch.setattr(mcp_bootstrap_mod, "bootstrap_mcp", fake_bootstrap)

    state = AppState()

    async def scenario():
        task = _schedule_mcp_bootstrap(state)
        await asyncio.sleep(0.05)
        assert calls == [1]          # 已在后台启动
        assert not task.done()       # 未阻塞等待连接完成
        release.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())


def test_bootstrap_attaches_clients_to_existing_agents(monkeypatch, fake_clients):
    """连接完成后：把客户端补挂到启动期已存在的 agent ToolRouter"""
    async def fake_bootstrap():
        return {"filesystem": True}

    monkeypatch.setattr(mcp_bootstrap_mod, "bootstrap_mcp", fake_bootstrap)

    state = AppState()
    router = FakeRouter()
    state.agents["default"] = types.SimpleNamespace(tool_router=router)

    async def scenario():
        task = _schedule_mcp_bootstrap(state)
        await asyncio.wait_for(task, timeout=2)
        assert ("filesystem", fake_clients["filesystem"]) in router.registered

    asyncio.run(scenario())


def test_bootstrap_skips_agents_without_router(monkeypatch, fake_clients):
    """无 tool_router 的 agent 不炸（getattr 守卫只对缺失能力降级，非吞根因）"""
    async def fake_bootstrap():
        return {"filesystem": True}

    monkeypatch.setattr(mcp_bootstrap_mod, "bootstrap_mcp", fake_bootstrap)

    state = AppState()
    state.agents["bare"] = types.SimpleNamespace()  # 没有 tool_router

    async def scenario():
        task = _schedule_mcp_bootstrap(state)
        await asyncio.wait_for(task, timeout=2)  # 不抛异常即通过

    asyncio.run(scenario())


def test_bootstrap_failure_is_logged_not_raised(monkeypatch, fake_clients):
    """连接失败只告警，不让后台任务抛未处理异常"""
    async def fake_bootstrap():
        raise RuntimeError("npx not found")

    monkeypatch.setattr(mcp_bootstrap_mod, "bootstrap_mcp", fake_bootstrap)

    state = AppState()

    async def scenario():
        task = _schedule_mcp_bootstrap(state)
        await asyncio.wait_for(task, timeout=2)  # 异常被内层捕获，任务正常结束

    asyncio.run(scenario())
