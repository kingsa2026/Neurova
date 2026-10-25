# -*- coding: utf-8 -*-
"""tests/unit/tts 域夹具。

`heavy_manager` 原先住在 `test_tts_lazy_release.py` 里，只被那一个文件请求；
本目录的判据档（`test_unitTierNeverPaysForRealWeights.py`）要复用同一条
「释放 → 换班 → 预热」链，故夹具与假引擎上收到本目录＝一处定义。

夹具把 manager 构造重引擎的那处接缝一并桩掉：往 `_engines` 里塞假引擎只挡得住
「命中缓存」支路，而 TTL 释放恰好把链顶从 `_engines` 丢掉，随后的后台预热改走
**构造**支路——那里读的是 `neurova.tts.manager` 的模块级 `MOSSNanTTS`，假引擎
拦不住它，单元档因此在载 670MB 真权重（§6-201 登记的跑测环境缺陷，实测单格
19.32s；干净仓外 worktree 里还要先发真 HTTPS 下载，全局 timeout=30 被打断即整场
无汇总行）。判据见 `test_unitTierNeverPaysForRealWeights.py`。
"""

import time

import pytest

from neurova.tts import manager as tts_manager_mod
from neurova.tts.manager import TTSConfig, TTSManager
from tests.unit.tts._fakeEngines import _FakeHeavyEngine, _FakeLightEngine, fakeHeavyFactory


#: 「很久没用过」的时间锚。**必须相对当前时钟算**，不能写死一个绝对数：
#: `synthesize()` 收尾会把握时器推成 `time.monotonic()`，而进程已跑了一段时间的机器上
#: 那个读数早超过一百六十万秒 ⇒ 写死 `1_000_000` 反而成了"刚刚用过"，TTL 格因此红成
#: "释放没换班到轻引擎"（判据与环境耦合，与实现无关）。
IDLE_ANCHOR_OFFSET_SEC = 10_000.0


def idleNow() -> float:
    """比"现在"晚 `IDLE_ANCHOR_OFFSET_SEC` 的合成时钟读数——任何 TTL 都早已超时。"""
    return time.monotonic() + IDLE_ANCHOR_OFFSET_SEC


@pytest.fixture()
def heavy_manager(monkeypatch):
    """预注入假引擎的 manager：缓存与**构造**两条支路都留在假引擎里。"""
    monkeypatch.setattr(tts_manager_mod, "MOSSNanTTS", fakeHeavyFactory)
    cfg = TTSConfig(
        engine="auto",
        fallback_chain=["moss-nano", "edge-tts", "mock"],
        fallback_enabled=True,
        lazy_release=True,
        release_ttl_sec=60,
    )
    mgr = TTSManager(config=cfg)
    heavy, light = _FakeHeavyEngine(), _FakeLightEngine()
    mgr._engines = {"moss-nano": heavy, "edge-tts": light}
    return mgr, heavy, light
