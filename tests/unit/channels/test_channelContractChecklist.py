# -*- coding: utf-8 -*-
"""新增渠道的最小契约清单（D-5）。

本盘要堵的失败方向：工厂里加了渠道分支，但出站长度预算没登记——于是它悄悄落
默认 4000；平台真实上限更小时，长回复整条被拒而没人发现（Discord 就是这么漏的）。
判据把「工厂支持的渠道」与「长度预算的两种登记」钉在一起：

- 显式上限：`CHANNEL_TEXT_LIMITS` 有该渠道；
- 默认上限：`DEFAULT_TEXT_LIMIT_CHANNELS` 有该渠道**并写明理由**。

两条都没有 = 红。反向也钉：登记表里不许有工厂不支持的渠道（防死登记）。
缺省方向（未知策略拒绝）由 `test_channelAccessPolicy.py` 承担，不在此重复。
"""
from __future__ import annotations

import inspect
import re

from neurova.api.endpoints import channel_config
from neurova.channels.message_chunker import (
    CHANNEL_TEXT_LIMITS,
    DEFAULT_TEXT_LIMIT_CHANNELS,
    text_limit_for,
)


def _factoryChannelTypes() -> set:
    source = inspect.getsource(channel_config._create_adapter)
    return set(re.findall(r'channel_type == "([a-z_]+)"', source))


def test_factorySurfaceIsNotVacuous():
    types = _factoryChannelTypes()
    assert len(types) >= 10, f"只解析到 {len(types)} 个渠道分支——解析口径写窄了"


def test_everyFactoryChannelDeclaresItsTextBudget():
    supported = _factoryChannelTypes()
    undeclared = supported - set(CHANNEL_TEXT_LIMITS) - set(DEFAULT_TEXT_LIMIT_CHANNELS)
    assert not undeclared, (
        f"这些渠道既没有显式上限也没登记默认上限：{sorted(undeclared)}；"
        "新增渠道必须二选一并写明理由，否则长回复会按 4000 悄悄发出"
    )
    for channelType in supported:
        assert text_limit_for(channelType) > 0


def test_defaultLimitRegistryHasNoDeadEntries():
    supported = _factoryChannelTypes()
    dead = set(DEFAULT_TEXT_LIMIT_CHANNELS) - supported
    assert not dead, f"登记表里有工厂已不支持的渠道：{sorted(dead)}"


def test_defaultLimitReasonsAreWritten():
    empty = [k for k, v in DEFAULT_TEXT_LIMIT_CHANNELS.items() if not str(v).strip()]
    assert not empty, f"默认上限登记缺少理由：{empty}"
