# -*- coding: utf-8 -*-
"""AgentFirewall 的渠道维度额度（外部 Agent 接入专用档）

背景：`check_rate_limit` 今天生产侧零调用（只有本模块自己的测试在用），而
被退役的 communication_protocol.py 自带一把无界、不可配置、不清理的 60 秒滑窗。
选定的收口方式是**把 firewall 这把尺子接进请求链**，而不是再添第三把。

语义约定：
- 额度按渠道分档：internal（默认）沿用现有 rate_limit_per_minute/hour；
  externalAgent 走专用档（默认更宽，因外部 Agent 批量同步的量级远高于人用）。
- 计数器按 (user_id, channel, window) 分桶：不同渠道互不扣额。
- 键域仍是 user_id —— 同一用户下的多个外部 Agent **共享**一份额度，这是有意语义，
  本文件把它钉死，防止后续"按 agent_id 分桶"的无声放宽。
- 默认渠道行为不变（现有调用方与被本批接线的请求链都不得因加参数而变严格）。
"""

import pytest

from neurova.core.firewall import (
    CHANNEL_EXTERNAL_AGENT,
    CHANNEL_INTERNAL,
    AgentFirewall,
)


@pytest.fixture()
def firewall(tmp_path):
    return AgentFirewall(config_path=str(tmp_path / "firewall.json"))


def _set_external_minute_quota(firewall: AgentFirewall, quota: int) -> None:
    firewall.update_global_rules({"external_rate_limit_per_minute": quota})


def test_external_channel_uses_its_own_dedicated_quota(firewall):
    """外部渠道按专用档拦，且不影响同用户的内部渠道计数。"""
    _set_external_minute_quota(firewall, 2)

    results = [firewall.check_rate_limit("u1", CHANNEL_EXTERNAL_AGENT) for _ in range(3)]

    assert results[0][0] is True
    assert results[1][0] is True
    assert results[2][0] is False
    assert "external" in results[2][1].lower() or "External" in results[2][1]

    # 同用户内部渠道仍有大量额度 → 证明计数器分桶而非共桶
    ok, _ = firewall.check_rate_limit("u1", CHANNEL_INTERNAL)
    assert ok is True


def test_agents_under_one_user_share_the_external_quota(firewall):
    """键域是 user_id：同用户多 Agent 共享额度，不得按 agent_id 放宽。"""
    _set_external_minute_quota(firewall, 2)

    firewall.check_rate_limit("u1", CHANNEL_EXTERNAL_AGENT)
    firewall.check_rate_limit("u1", CHANNEL_EXTERNAL_AGENT)

    ok, _ = firewall.check_rate_limit("u1", CHANNEL_EXTERNAL_AGENT)
    assert ok is False, "第三请求（即便来自不同 agent_id）必须仍被拒"


def test_default_channel_argument_stays_optional(firewall):
    """不带 channel 的旧调用形态行为不变（默认档取中间件实际在执行的 120/分）。"""
    for _ in range(120):
        ok, _ = firewall.check_rate_limit("u2")
        assert ok is True

    ok, reason = firewall.check_rate_limit("u2")
    assert ok is False
    assert "minute" in reason


def test_effective_rules_expose_both_channels(firewall):
    """两档额度都必须是可配置事实源，不得把额度硬编码回调用侧。

    internal 默认 120 是被退役的中间件硬编码值——收口时若沿 firewall 里那个从未
    被调用过的 60，等于把人用流量当场收紧一半，属行为劣化。
    """
    rules = firewall.get_effective_rules("u3")
    assert rules["rate_limit_per_minute"] == 120
    assert rules["external_rate_limit_per_minute"] > rules["rate_limit_per_minute"]
