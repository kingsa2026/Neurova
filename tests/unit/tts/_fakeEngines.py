# -*- coding: utf-8 -*-
"""TTS 管理器单测用的假引擎（真 moss-nano 权重 670MB，单元层不该碰）。

`test_tts_lazy_release.py` 与 `tests/unit/tts/conftest.py` 的 `heavy_manager`
夹具共用这两只——夹具要能被同目录其它判据档请求，故类和夹具一起搬出测试档，
不在两处各写一份。
"""

import asyncio
from unittest.mock import AsyncMock


class _FakeHeavyEngine:
    """模拟 moss-nano：重模型 + is_initialized 生命周期。"""

    name = "moss-nano"
    audio_media_type = "audio/wav"

    def __init__(self):
        self._initialized = False
        self.released = False
        self.synthesize = AsyncMock(return_value=b"RIFFheavy-audio")
        self.calls = 0

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> bool:
        # 模拟加载耗时但可控
        await asyncio.sleep(0)
        self._initialized = True
        return True

    async def shutdown(self) -> None:
        self.released = True
        self._initialized = False


class _FakeLightEngine:
    """模拟 edge-tts：轻量、秒级就绪。"""

    name = "edge-tts"
    audio_media_type = "audio/mpeg"

    def __init__(self):
        self._initialized = False
        self.synthesize = AsyncMock(return_value=b"\xff\xfblight-audio")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> bool:
        await asyncio.sleep(0)
        self._initialized = True
        return True

    async def shutdown(self) -> None:
        self._initialized = False


def fakeHeavyFactory(**_weightDirs):
    """顶替 `neurova.tts.manager` 模块级 `MOSSNanTTS` 的构造接缝。

    manager 那侧按 `MOSSNanTTS(model_dir=…, tokenizer_dir=…, auto_download=…)`
    构造重引擎，故替身必须吃下这组权重目录参数——类的严格签名留给测试直接
    构造时用，两条各有各的形状，不为了桩而把假引擎的签名放宽。
    """
    return _FakeHeavyEngine()


def fakeLightFactory(**_engineOptions):
    """顶替 `neurova.tts.manager` 模块级 `EdgeTTS` 的构造接缝（重引擎那侧的同形）。

    为什么轻引擎也要桩：`_engines` 里那只假实例只挡得住「命中缓存」，而 TTL 释放
    **正是**把它从缓存里丢掉、改走 `_initialize_engine("edge-tts")` 去构造一个新的
    `EdgeTTS`。真类 `initialize()` 里 `import edge_tts`，而精简锁按设计不含它 ⇒ 释放
    当场返回 False，本组判据在 CI 上红、在装过 edge-tts 的开发机上绿。判据不该由
    「这台机器装了什么」决定读数（同一口径见重引擎那侧 `fakeHeavyFactory`）。
    """
    return _FakeLightEngine()
