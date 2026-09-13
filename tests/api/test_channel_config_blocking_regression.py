"""RES-P0-2 回归测试：渠道适配器创建/测试不得阻塞事件循环。

背景（docs/资源型Bug扫描报告_2026-09-11.md P0-2）：
channel_config.py 两个 async 端点曾在事件循环上同步调用 _create_adapter；
iLink 微信模式的 authenticate 含最长 300s 的 requests+sleep 轮询——
一次保存/测试即冻结全站。根修=to_thread 下沉；F-2/F-3 后续将无 token
的扫码流程拆为两段式非阻塞端点（needs_scan 契约）。

⚠️ 契约版本：本文件 2026-09-11 按 needs_scan 契约重写——
- 防阻塞断言改走"有 bot_token"路径（needs_scan=False，真正触达 _create_adapter）；
- 无 token 的 save/test 不再创建适配器（诚实 needs_scan），单独锁定。

验收：
1. _create_adapter 的同步阻塞工作必须下沉线程池（并发请求期间事件循环保持响应）；
2. 无 token 的 wechat ilink save/test 诚实短路 needs_scan，不创建适配器；
3. 有 token 的 test 链路端到端可用（真实 verify 有界 10s，非轮询）。
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.api.endpoints import channel_config as cc


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """隔离配置文件与渠道管理器单例（单测零副作用）。"""
    monkeypatch.setattr(cc, "CONFIG_FILE", tmp_path / "channels.json")
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path)
    # 真实默认 token 路径永不触达（本日有测试改写真实用户文件的事故）
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = MagicMock()
    monkeypatch.setattr(cc, "get_channel_manager", lambda: manager)
    return manager


def _req(channel_type: str = "wechat", extra: dict = None):
    """注意：extra 必须直接作为请求体 extra 字段，不得二次包裹。"""
    return cc.ChannelConfigRequest(
        channel_type=channel_type, enabled=True,
        app_id="", app_secret="", use_stream=True, extra=extra or {},
    )


async def _gather_with_probe(coros):
    """并发跑 coros，期间事件循环探针计数（阻塞会饿死探针）。"""
    ticks = 0
    stop = asyncio.Event()

    async def probe():
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.02)
            ticks += 1

    probe_task = asyncio.create_task(probe())
    t0 = time.monotonic()
    results = await asyncio.gather(*coros)
    elapsed = time.monotonic() - t0
    stop.set()
    await probe_task
    return results, elapsed, ticks


@pytest.mark.asyncio
async def test_create_config_does_not_block_event_loop(isolated_env, monkeypatch):
    """有 token 的并发保存期间，事件循环必须保持调度（同步工厂须下沉线程池）。"""

    def fake_create(channel_type, config):
        time.sleep(0.4)  # 模拟同步认证/轮询等阻塞工作
        return MagicMock()

    monkeypatch.setattr(cc, "_create_adapter", fake_create)

    results, elapsed, ticks = await _gather_with_probe([
        cc.create_or_update_config(_req(extra={"mode": "ilink", "bot_token": "t1", "private_strategy": "open"})),
        cc.create_or_update_config(_req(extra={"mode": "ilink", "bot_token": "t2", "group_strategy": "closed"})),
    ])
    assert all(r["success"] for r in results)
    assert not any(r.get("needs_scan") for r in results), "带 token 不得短路 needs_scan"
    assert elapsed < 0.75, (
        f"两次并发创建耗时 {elapsed:.2f}s（≥串行下限 0.8s 量级），"
        "事件循环被 _create_adapter 同步阻塞（RES-P0-2）"
    )
    assert ticks > 5, f"阻塞窗口内事件循环仅调度 {ticks} 次，疑似被独占（RES-P0-2）"


@pytest.mark.asyncio
async def test_test_connection_does_not_block_event_loop(isolated_env, monkeypatch):
    """测试连接端点同样不得在事件循环上执行同步工厂。"""

    def fake_create(channel_type, config):
        time.sleep(0.4)
        return SimpleNamespace(
            mode="ilink",
            _ilink_initialized=True,
            connect=AsyncMock(return_value=True),
            health_check=AsyncMock(return_value={"ok": True}),
            disconnect=AsyncMock(),
        )

    monkeypatch.setattr(cc, "_create_adapter", fake_create)

    (result,), elapsed, ticks = await _gather_with_probe(
        [cc.test_connection("wechat", _req(extra={"mode": "ilink", "bot_token": "t1"}))]
    )
    assert result.success is True, f"{result.message} / {result.details}"
    assert elapsed < 0.75
    assert ticks > 5, f"test_connection 同步工厂期间事件循环仅调度 {ticks} 次（RES-P0-2）"


@pytest.mark.asyncio
async def test_wechat_ilink_without_token_honest_needs_scan(isolated_env, monkeypatch):
    """F-2/F-3 契约：无 token 的 save/test 诚实 needs_scan，不创建适配器（消灭 300s 线程阻塞）。"""
    calls = []
    monkeypatch.setattr(cc, "_create_adapter", lambda *a, **k: calls.append(a) or MagicMock())

    save = await cc.create_or_update_config(_req(extra={"mode": "ilink"}))
    assert save["success"] is True and save["needs_scan"] is True
    assert len(calls) == 0, "needs_scan 路径不得创建适配器"

    result = await cc.test_connection("wechat", _req(extra={"mode": "ilink"}))
    assert result.success is False, "无 token 必须诚实失败，绝不假阳性（F-2）"
    assert getattr(result, "needs_scan", False) is True
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_wechat_ilink_verify_flow_offloop(isolated_env, monkeypatch, tmp_path):
    """有 token 的真实链路不被破坏：test_connection 走新 WeChatILinkAdapter，
    connect() 以有界 getconfig 校验凭据（非轮询、非旧 /auth/verify seam）。

    2026-09-13 ilink 端到端移植后，test_connection 的 wechat(ilink) 不再经
    WeChatAdapter._verify_ilink_token（requests /auth/verify），而是
    WeChatILinkAdapter.connect() → ILinkClient.getconfig（httpx，有界单次）。
    """
    from neurova.channels.wechat_ilink_client import ILinkClient

    getconfig = AsyncMock(return_value={"ret": 0})
    monkeypatch.setattr(ILinkClient, "getconfig", getconfig)
    # start/stop 不真建 httpx 连接；getupdates 立即取消避免后台轮询真发网络
    monkeypatch.setattr(ILinkClient, "start", AsyncMock())
    monkeypatch.setattr(ILinkClient, "stop", AsyncMock())
    monkeypatch.setattr(ILinkClient, "getupdates", AsyncMock(side_effect=asyncio.CancelledError))

    token_file = tmp_path / "ilink_token"
    result = await cc.test_connection(
        "wechat", _req(extra={"mode": "ilink", "bot_token": "tok-123", "token_file": str(token_file)}),
    )

    assert result.success is True, f"iLink 校验链路被破坏: {result.message} / {result.details}"
    assert getconfig.await_count == 1, "凭据校验必须恰一次有界请求（零轮询，RES-P0-2 红线）"
    assert not token_file.exists(), "test 路径不得写 token 文件"
