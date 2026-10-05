# -*- coding: utf-8 -*-
"""组档位接入 firewall 后的额度语义（并钉死"每分钟额度只有一处定义"）

背景：每分钟额度此前在仓里有三份定义，只有一份真执行——
`core/firewall`（上一批接进中间件，120/300）、`admin/resource_quota_manager` 的
`max_api_calls_per_minute: 60`（`check_api_call_quota` 零生产调用方）、
`auth/user_group_model` 的组档（只写不读）。
本批把组档接成**人用渠道的权威额度**，并退役账本里那维没人执行的限额。

语义约定：
- 组档经 resolver 注入 firewall（`core` 不得 import `auth`：user_group_model 反向
  依赖 core.logger/data_root，模块级引入即成环）。
- 组档作用于 internal 渠道；externalAgent 档保持独立（那是接入面容量决策，不由
  用户组决定）。
- 解析不出身份或 resolver 抛错 → 回落全局默认，**不得**因此拒绝请求。
- resolver 结果带 TTL 缓存：限流在每请求路径上，不能每次都查库。
- 退役要留痕：仓内不得再出现第二份"每分钟 API 额度"定义。
"""

import pytest

from neurova.admin import resource_quota_manager as rq
from neurova.core.firewall import CHANNEL_EXTERNAL_AGENT, CHANNEL_INTERNAL, AgentFirewall


@pytest.fixture()
def firewall(tmp_path):
    fw = AgentFirewall(config_path=str(tmp_path / "fw.json"))
    yield fw


def _drain(firewall, channel, user_id, attempts):
    return [firewall.check_rate_limit(user_id, channel)[0] for _ in range(attempts)]


def test_group_tier_governs_the_internal_channel(firewall):
    """访客档 30 生效后，第 31 次请求必须被拒——档位不再是装饰。"""
    firewall.setRateQuotaResolver(lambda user_id: 30)

    allowed = _drain(firewall, CHANNEL_INTERNAL, "guest-user", 31)
    assert allowed[:30] == [True] * 30
    assert allowed[30] is False


def test_group_tier_does_not_move_the_external_channel(firewall):
    """外部 Agent 档不由用户组决定：组档给 1，externalAgent 仍按自己的额度放行。"""
    firewall.setRateQuotaResolver(lambda user_id: 1)

    assert _drain(firewall, CHANNEL_EXTERNAL_AGENT, "u1", 5) == [True] * 5


def test_resolver_failure_falls_back_to_global_default(firewall):
    """解析炸了不得把请求拒掉：回落全局默认 120，且不向上抛异常。"""

    def boom(user_id):
        raise RuntimeError("group store unavailable")

    firewall.setRateQuotaResolver(boom)

    allowed = _drain(firewall, CHANNEL_INTERNAL, "u2", 121)
    assert allowed[:120] == [True] * 120
    assert allowed[120] is False


def test_unknown_group_falls_back_to_global_default(firewall):
    """resolver 返回 None（用户无组）→ 用全局默认，而不是当成 0 全拒。"""
    firewall.setRateQuotaResolver(lambda user_id: None)

    assert firewall.check_rate_limit("no-group-user", CHANNEL_INTERNAL)[0] is True


def test_resolver_result_is_cached_within_ttl(firewall):
    """每请求路径不能每次查库：同键在 TTL 内只解析一次。"""
    calls = []

    def countingResolver(user_id):
        calls.append(user_id)
        return 2

    firewall.setRateQuotaResolver(countingResolver, ttlSeconds=60)
    _drain(firewall, CHANNEL_INTERNAL, "u3", 3)

    assert len(calls) == 1


def test_no_second_per_minute_api_quota_definition():
    """退役留痕：账本里那维没人执行的每分钟限额必须整条消失。"""
    assert "max_api_calls_per_minute" not in rq.DEFAULT_LIMITS
    assert "api_call_count" not in rq._USAGE_TO_LIMIT
    assert not hasattr(rq.ResourceQuotaManager, "check_api_call_quota")
    assert not hasattr(rq.ResourceQuotaManager, "increment_api_call")
    assert not hasattr(rq.ResourceUsage, "api_call_count")
