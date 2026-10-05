"""MCP 会话生命周期关停接线（lifespan 卡死的根因侧）。

缺陷档案（2026-10-05 实测）：`_schedule_mcp_bootstrap` 起的 stdio 会话在关停时无人
disconnect。anyio blocking portal 退出时只能去 `_cancel_all_tasks` 取消这些任务，而
stdio reader 阻塞在子进程管道上、取消不收敛，portal 线程因此不结束，
`TestClient.__exit__` 的 `thread.join()` 永久阻塞。

对照实验（同一份代码，只切换 bootstrap_mcp 是否建会话）：
- 建会话：同一单例 app 第 3 轮 lifespan 退出即卡死，faulthandler 栈停在
  `asyncio/runners.py:206 _cancel_all_tasks`；
- 不建会话：5 轮启停全部 `teardown ok`，单轮 <0.5s，进程正常退出。

本文件钉两件事，都不依赖真实子进程（会话生命周期是 mcp_client.py 自述的 mock 接缝）：
1. 关停必须经 bootstrap 注册表与进程单例两个发现口把会话关掉——由真实
   startup/shutdown 事件链触发，不手工调关停函数代替装配；
2. 同一进程内重复 bootstrap 不得为同一 server 再建一条会话——`_bootstrapped` 此前
   只写不读，重复启动会把上一轮的活会话顶掉泄漏。
"""

import asyncio
import typing

import pytest
from fastapi.testclient import TestClient

import neurova.shared_config as shared_config_mod
import neurova.tool_layers.mcp_bootstrap as mcp_bootstrap
import neurova.tool_layers.mcp_client as mcp_client
from neurova.api.app import create_app


class _RecordingClient:
    """记录 disconnect 次数的 MCPToolClient 替身"""

    instances: typing.List["_RecordingClient"] = []

    def __init__(self, user_id: typing.Optional[str] = None, *args, **kwargs):
        self.user_id = user_id
        self.disconnect_all_calls = 0
        _RecordingClient.instances.append(self)

    async def connect_server(self, server_id: str, config: typing.Dict[str, typing.Any]) -> bool:
        return True

    async def disconnect_all(self) -> None:
        self.disconnect_all_calls += 1

    def get_server_status(self, server_id: str) -> typing.Dict[str, typing.Any]:
        return {"last_error": None}


class _EmptyConfigManager:
    """让 bootstrap 一个服务器都不连：待关关停的会话由测试显式登记，不靠真实配置竞态"""

    def list_mcp_servers(self) -> typing.List[typing.Dict[str, typing.Any]]:
        return []


class _OneServerConfigManager:
    """同一个 server id 反复被请求连接——重复 bootstrap 的复现面"""

    def list_mcp_servers(self) -> typing.List[typing.Dict[str, typing.Any]]:
        return [{"id": "filesystem", "enabled": True, "transport": "stdio", "command": "true"}]


@pytest.fixture(autouse=True)
def isolateMcpState(monkeypatch):
    """干净注册表 + 干净单例 + 替身客户端（即用即复位，不跨用例泄漏）"""
    _RecordingClient.instances = []
    monkeypatch.setattr(mcp_bootstrap, "MCPToolClient", _RecordingClient)
    monkeypatch.setattr(shared_config_mod, "get_shared_config_manager", _EmptyConfigManager)
    mcp_bootstrap.reset_bootstrap()
    mcp_client.reset_mcp_client()
    yield
    mcp_bootstrap.reset_bootstrap()
    mcp_client.reset_mcp_client()


@pytest.fixture(autouse=True)
def restoreProcessAppState():
    """真实 startup 会向进程级 agents 表写入一个真 Agent，并把 endpoints 的状态字典换成
    新的一份；同进程后续用例（nerf / semantic-search 端点按 `get_app_state()["agents"]`
    判定，见 enhanced_memory_search_api.py:24 的根因注释）会因此看到多出来的 agent。
    本文件动了什么就按原样回填什么——不留"谁先跑谁决定结果"的耦合。"""
    import neurova.api.app as app_mod
    import neurova.api.endpoints as endpoints_mod

    savedInstance = app_mod._app_instance
    savedState = app_mod._app_state
    savedEndpointsDict = endpoints_mod.get_app_state()
    savedAgents = dict(savedState.agents) if savedState is not None else None
    yield
    if savedState is not None and savedAgents is not None:
        savedState.agents.clear()
        savedState.agents.update(savedAgents)
    app_mod._app_instance = savedInstance
    app_mod._app_state = savedState
    endpoints_mod.set_app_state(savedEndpointsDict)


def test_appShutdownDisconnectsBootstrappedMcpSessions():
    """真实 lifespan 关停必须 disconnect bootstrap 注册表里的会话"""
    app = create_app()
    sessionClient = _RecordingClient()
    mcp_bootstrap._clients["filesystem"] = sessionClient

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert sessionClient.disconnect_all_calls == 1, (
        f"关停未 disconnect MCP 会话（calls={sessionClient.disconnect_all_calls}）"
    )
    assert mcp_bootstrap.get_bootstrapped_clients() == {}, "关停后注册表应清空"


def test_appShutdownDisconnectsProcessSingletonMcpClient():
    """REST 侧连接走进程单例：关停必须同时覆盖这个发现口，否则同一根因留半边"""
    app = create_app()
    singletonClient = _RecordingClient()
    mcp_client._mcp_client_instance = singletonClient

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert singletonClient.disconnect_all_calls == 1, (
        f"进程单例 MCP 客户端未被 disconnect（calls={singletonClient.disconnect_all_calls}）"
    )


def test_startupKeepsMcpBootstrapTaskHandle():
    """startup 必须留下 bootstrap 任务句柄——关停要先收敛在途任务，无句柄即无从收敛"""
    import neurova.api.app as app_mod

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app_mod._app_state.mcp_bootstrap_task is not None, (
            "bootstrap 后台任务句柄未被保存（只活在 create_task 的返回值里，关停拿不到）"
        )


def test_repeatedBootstrapDoesNotReconnectSameServer():
    """同一进程内二次 bootstrap 不得为同一 server 再建会话（顶掉即泄漏）"""

    async def _twice():
        # 两次调用共用一个事件循环：mcp_bootstrap._lock 是模块级 asyncio.Lock，
        # 跨 asyncio.run 复用会先撞上"bound to a different event loop"，
        # 那是测试装配噪声而不是行为缺陷。
        first = await mcp_bootstrap.bootstrap_mcp(config_manager=_OneServerConfigManager())
        firstIds = set(mcp_bootstrap.get_bootstrapped_clients())
        createdAfterFirst = len(_RecordingClient.instances)
        second = await mcp_bootstrap.bootstrap_mcp(config_manager=_OneServerConfigManager())
        return first, second, firstIds, createdAfterFirst

    first, second, firstIds, createdAfterFirst = asyncio.run(_twice())

    assert first == {"filesystem": True}
    # 第二次一条都不连：docstring 口径"仅包含实际尝试连接的服务器"，空结果即诚实回报
    assert second == {}
    assert createdAfterFirst == 1, f"首轮应只建 1 条会话，实建 {createdAfterFirst}"
    assert len(_RecordingClient.instances) == 1, (
        f"重复 bootstrap 又建了一条会话：{len(_RecordingClient.instances)}"
    )
    assert firstIds == set(mcp_bootstrap.get_bootstrapped_clients())
