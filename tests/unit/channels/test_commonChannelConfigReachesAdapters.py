# -*- coding: utf-8 -*-
"""CHAN-03：公共渠道配置必须从创建 DTO 贯通到 Gen2 适配器。

审计证据（docs/05-reports/全仓逐文件审计报告_2026-11-25.md §8 CHAN-03）：
UI 把 private/group 策略、require_mention、whitelist 等公共字段写进 extra，
但 `channel_config._create_adapter` 创建 Discord/Telegram/QQBot（以及
QClaw/XiaoYi 两个同根因兄弟）时把 extra 丢掉；适配器 authenticate 只看到
bot_token，公共配置全部回落默认——UI 里选了 closed/whitelist，路由层按
open 放行，策略形同未配置。

判据（从真实创建入口 `_create_adapter` 出发，不手工传策略）：
1. 五个 Gen2 工厂创建的适配器，公共策略都落在其配置视图上；
2. `channel_router._channel_cfg`（路由层唯一读取口）能读到同一组策略；
3. UI 形态的 JSON 布尔（true/false）与字符串形态同一口径，不再因
   `True.lower()` 炸掉创建。
"""
from __future__ import annotations

import pytest

from neurova.api.endpoints import channel_config
from neurova.channels.base import ChannelConfig


_COMMON = {
    "bot_prefix": "@nv",
    "show_tool_messages": True,
    "show_thinking": False,
    "stream_mode": True,
    "private_chat_strategy": "closed",
    "group_chat_strategy": "whitelist",
    "require_mention": True,
    "whitelist_users": "u1,u2",
}

_BOT = {"bot_token": "tok-1", "access_token": "acc-1"}


def _extra(**overrides):
    merged = {**_COMMON, **_BOT}
    merged.update(overrides)
    return merged


def _stubManager(adapter):
    class _Manager:
        def get_adapter(self, channel_type, agent_id="default"):
            return adapter if channel_type == adapter.channel_type else None

    return _Manager()


def _routeView(adapter):
    from neurova.channels.channel_router import _channel_cfg

    return _channel_cfg(_stubManager(adapter), adapter.channel_type, "default")


def _assertPolicies(adapter):
    view = _routeView(adapter)
    assert view.get("private_chat_strategy") == "closed", (
        f"{adapter.channel_type}: private_chat_strategy 未到达路由层（实得 {view.get('private_chat_strategy')!r}）"
    )
    assert view.get("group_chat_strategy") == "whitelist", (
        f"{adapter.channel_type}: group_chat_strategy 未到达路由层（实得 {view.get('group_chat_strategy')!r}）"
    )
    assert view.get("require_mention") is True, (
        f"{adapter.channel_type}: require_mention 未到达路由层（实得 {view.get('require_mention')!r}）"
    )


def test_discordReceivesCommonExtra(monkeypatch):
    from neurova.channels.discord import DiscordAdapter

    monkeypatch.setattr(DiscordAdapter, "_verify_token", lambda self: True)
    adapter = channel_config._create_adapter(
        "discord", ChannelConfig(channel_type="discord", extra=_extra())
    )
    assert adapter.private_chat_strategy == "closed"
    assert adapter.group_chat_strategy == "whitelist"
    assert adapter.require_mention is True
    assert adapter.whitelist_users == ["u1", "u2"]
    _assertPolicies(adapter)


def test_telegramReceivesCommonExtra(monkeypatch):
    from neurova.channels.telegram_adapter import TelegramAdapter

    monkeypatch.setattr(TelegramAdapter, "_verify_token", lambda self: True)
    adapter = channel_config._create_adapter(
        "telegram", ChannelConfig(channel_type="telegram", extra=_extra())
    )
    assert adapter.private_chat_strategy == "closed"
    assert adapter.group_chat_strategy == "whitelist"
    assert adapter.require_mention is True
    assert adapter.whitelist_users == ["u1", "u2"]
    _assertPolicies(adapter)


def test_qqbotReceivesCommonExtra(monkeypatch):
    from neurova.channels.qqbot import QQBotAdapter

    monkeypatch.setattr(QQBotAdapter, "_verify_connection", lambda self: True)
    adapter = channel_config._create_adapter(
        "qqbot",
        ChannelConfig(
            channel_type="qqbot",
            extra=_extra(http_api_url="http://127.0.0.1:3000"),
        ),
    )
    assert adapter.private_chat_strategy == "closed"
    assert adapter.group_chat_strategy == "whitelist"
    assert adapter.require_mention is True
    assert adapter.whitelist_users == ["u1", "u2"]
    _assertPolicies(adapter)


def test_qclawReceivesCommonExtra(monkeypatch):
    from neurova.channels.qclaw import QClawAdapter

    monkeypatch.setattr(QClawAdapter, "authenticate", lambda self, config=None: True)
    adapter = channel_config._create_adapter(
        "qclaw",
        ChannelConfig(
            channel_type="qclaw",
            app_id="app-1",
            app_secret="sec-1",
            extra=_extra(),
        ),
    )
    assert adapter.config.extra.get("private_chat_strategy") == "closed"
    _assertPolicies(adapter)


def test_xiaoyiMergesCommonExtra(monkeypatch):
    adapter = channel_config._create_adapter(
        "xiaoyi",
        ChannelConfig(
            channel_type="xiaoyi",
            extra=_extra(
                access_key="ak",
                secret_key="sk",
                agent_id="agent-1",
                ws_url="wss://example.com/ws",
            ),
        ),
    )
    assert adapter.config.extra.get("ws_url") == "wss://example.com/ws", (
        "小艺工厂只保留了三个凭据键，ws_url 等公共配置被丢掉"
    )
    assert adapter.config.extra.get("private_chat_strategy") == "closed"
    _assertPolicies(adapter)


def test_jsonBooleanExtraDoesNotBreakAdapterCreation(monkeypatch):
    """UI 表单的 toggle 是 JSON 布尔：authenticate 不得再假定字符串。"""
    from neurova.channels.discord import DiscordAdapter

    monkeypatch.setattr(DiscordAdapter, "_verify_token", lambda self: True)
    adapter = channel_config._create_adapter(
        "discord",
        ChannelConfig(
            channel_type="discord",
            extra=_extra(show_tool_messages=False, show_thinking=True),
        ),
    )
    assert adapter.show_tool_messages is False
    assert adapter.show_thinking is True