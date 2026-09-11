"""RES-P0-2 回归测试：渠道适配器创建/测试连接不得阻塞事件循环。

背景（docs/资源型Bug扫描报告_2026-09-11.md P0-2）：
channel_config.py 两个 async 端点在事件循环上同步调用 _create_adapter；
iLink 微信模式（mode 默认即 ilink）的 authenticate → _wait_for_scan 内为
`requests.get + time.sleep(3)` 的 300 秒同步轮询——一次保存/测试即冻结
全站 HTTP/SSE/WS 最长 5 分钟。

验收：
1. _create_adapter 的同步阻塞工作必须下沉线程池（并发请求期间事件循环保持响应）；
2. 修复不得破坏真实 iLink 扫码认证链路（工厂在线程内完成认证并落 token 文件）。
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
    manager = MagicMock()
    monkeypatch.setattr(cc, "get_channel_manager", lambda: manager)
    return manager


def _req(channel_type: str = "wechat", extra: dict = None):
    """注意：extra 必须直接作为请求体的 extra 字段，不得二次包裹。"""
    return cc.ChannelConfigRequest(
        channel_type=channel_type, enabled=True,
        app_id="", app_secret="", use_stream=True, extra=extra or {},
    )


@pytest.mark.asyncio
async def test_create_config_does_not_block_event_loop(isolated_env, monkeypatch):
    """两个并发保存请求期间，事件循环必须保持调度（同步工厂须下沉线程池）。"""

    def fake_create(channel_type, config):
        time.sleep(0.4)  # 模拟 iLink 同步认证/轮询等阻塞工作
        return MagicMock()

    monkeypatch.setattr(cc, "_create_adapter", fake_create)

    ticks = 0
    stop = asyncio.Event()

    async def probe():
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.02)
            ticks += 1

    probe_task = asyncio.create_task(probe())
    t0 = time.monotonic()
    await asyncio.gather(
        cc.create_or_update_config(_req(extra={"mode": "ilink", "private_strategy": "open"})),
        cc.create_or_update_config(_req(extra={"mode": "ilink", "group_strategy": "closed"})),
    )
    elapsed = time.monotonic() - t0
    stop.set()
    await probe_task

    assert elapsed < 0.75, (
        f"两次并发创建耗时 {elapsed:.2f}s（≥串行下限 0.8s 量级），"
        "事件循环被 _create_adapter 同步阻塞（RES-P0-2）"
    )
    assert ticks > 5, (
        f"阻塞窗口内事件循环仅调度 {ticks} 次，疑似被独占（RES-P0-2）"
    )


@pytest.mark.asyncio
async def test_test_connection_does_not_block_event_loop(isolated_env, monkeypatch):
    """测试连接端点同样不得在事件循环上执行同步工厂。"""

    def fake_create(channel_type, config):
        time.sleep(0.4)
        return SimpleNamespace(
            connect=AsyncMock(return_value=True),
            health_check=AsyncMock(return_value={"ok": True}),
            disconnect=AsyncMock(),
        )

    monkeypatch.setattr(cc, "_create_adapter", fake_create)

    ticks = 0
    stop = asyncio.Event()

    async def probe():
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.02)
            ticks += 1

    probe_task = asyncio.create_task(probe())
    result = await cc.test_connection("wechat", _req(extra={"mode": "ilink"}))
    stop.set()
    await probe_task

    assert result.success is True
    assert ticks > 5, (
        f"test_connection 同步工厂期间事件循环仅调度 {ticks} 次（RES-P0-2）"
    )


@pytest.mark.asyncio
async def test_wechat_ilink_flow_still_works_offloop(isolated_env, monkeypatch, tmp_path):
    """修复不得破坏真实 iLink 链路：扫码认证在线程内完成并落 token 文件。

    环境隔离：USERPROFILE/HOME 指向 tmp——即使 token_file 参数流转回归，
    默认路径 ~/.Neurova/weixin_bot_token 也只会落进临时目录（严禁触碰真实文件）。
    """
    from neurova.channels import wechat_auth

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_post(url, timeout=None, **kw):
        return FakeResp({"success": True, "qr_code_url": "https://x/qr", "qr_id": "qr-1"})

    def fake_get(url, timeout=None, params=None, **kw):
        return FakeResp({"status": "confirmed", "bot_token": "tok-123"})

    fake_requests = SimpleNamespace(get=fake_get, post=fake_post, RequestException=Exception)
    monkeypatch.setattr(wechat_auth, "requests", fake_requests)

    token_file = tmp_path / "ilink_token"
    result = await cc.test_connection(
        "wechat", _req(extra={"mode": "ilink", "token_file": str(token_file)}),
    )

    assert result.success is True, f"iLink 链路被修复破坏: {result.message} / {result.details}"
    assert token_file.exists(), "扫码确认后 token 未落盘"
