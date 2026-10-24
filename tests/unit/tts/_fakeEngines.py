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



def afterTtl(mgr) -> float:
    """「已过 TTL」的那个时刻，按**本进程真实单调时钟**给——同域唯一取法。

    `release_idle_engines` 拿传入值与 `_last_used_monotonic`（`time.monotonic()`
    写入）相减判 TTL。写死一个绝对数（原先是 `1_000_000`）只在开机不足 11.6 天的
    机器上像未来；Linux 的单调时钟从开机算起，超过那个数后 `now - last` 变负，
    释放条件永不成立，用例全红在「重引擎没被释放」，读的人会去查 TTS 释放逻辑。

    两个判据档（`test_tts_lazy_release.py` 九处、`test_unitTierNeverPaysForRealWeights.py`
    一处）都要这个时刻：口径写成两份时改一份另一份静默失效，故收在这里。
    """
    import time

    return time.monotonic() + mgr._config.release_ttl_sec + 1
