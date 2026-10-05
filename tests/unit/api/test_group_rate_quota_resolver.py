# -*- coding: utf-8 -*-
"""组档 → firewall 人用渠道额度的适配器语义

`get_groups_for_user(username)` 返回该用户所属的全部组，一个用户可能同时在
开发者与普通用户两档里，取**最宽**（ entitlement 语义：就高不就低）。
解析不出任何组时返回 None，由 firewall 回落全局默认——不得当成 0 把人全拒。
"""

from types import SimpleNamespace

from neurova.api.group_rate_quota import groupRatePerMinute


def _group(minutes):
    return SimpleNamespace(resource_quota=SimpleNamespace(max_requests_per_minute=minutes))


def test_widest_group_wins(monkeypatch):
    fake = SimpleNamespace(get_groups_for_user=lambda name: [_group(60), _group(300), _group(120)])
    monkeypatch.setattr("neurova.api.group_rate_quota._manager", lambda: fake)

    assert groupRatePerMinute("dev-ish") == 300


def test_no_group_returns_none_so_default_applies(monkeypatch):
    fake = SimpleNamespace(get_groups_for_user=lambda name: [])
    monkeypatch.setattr("neurova.api.group_rate_quota._manager", lambda: fake)

    assert groupRatePerMinute("nobody") is None


def test_blank_username_short_circuits(monkeypatch):
    def boom():
        raise AssertionError("空身份不该去查库")

    monkeypatch.setattr("neurova.api.group_rate_quota._manager", boom)

    assert groupRatePerMinute("") is None
    assert groupRatePerMinute(None) is None
