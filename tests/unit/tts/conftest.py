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


@pytest.fixture()
def heavy_manager(monkeypatch):
    """预注入假引擎的 manager：缓存与**构造**两条支路都留在假引擎里。

    轻引擎那一支同样要桩：`release_idle_engines()` 的重引擎换班走 `_initialize_engine("edge-tts")`，
    它对 `self._engines` 只做「有就复用」，而真 `EdgeTTS.initialize()` 会去连在线服务——
    CI 无网时返回 False、换班失败，夹具「释放→换班」这条前置因此在这类机器上根本不成立。
    桩构造接缝的同时也把 `_engines` 里那只换成假轻引擎，缓存与构造两条支路都留在替身里。
    """
    monkeypatch.setattr(tts_manager_mod, "MOSSNanTTS", fakeHeavyFactory)
    monkeypatch.setattr(tts_manager_mod, "EdgeTTS", lambda **_kwargs: _FakeLightEngine())
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


#: 合成时钟必须**大于**上一步合成时记下的 `time.monotonic()` 读数，否则
#: `release_idle_engines` 里 `now - _last_used_monotonic` 是负数，恒小于 TTL ⇒ 永不释放。
#: 常量的 1_000_000 只在与 `_last_used_monotonic = 0.0`（手工置 0）并存时成立；
#: 走真合成链的用例要用这个函数取"现在 + 远超 TTL"。
IDLE_TTL_SECONDS = 60
SUPER_IDLE_AHEAD_SECONDS = 10_000


def superIdleClock() -> float:
    """当前单调时钟 + 远超 TTL 的偏移（走真合成链的用例用它，不写死常量）。"""
    return time.monotonic() + SUPER_IDLE_AHEAD_SECONDS
