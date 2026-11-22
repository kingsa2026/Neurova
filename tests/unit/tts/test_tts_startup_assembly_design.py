# -*- coding: utf-8 -*-
"""L2 TTS 装配核对钉（多模态追平计划语音域遗留）。

核对结论（现读取证）：TTS 装配**没有** ASR 同型的「只构造不初始化 +
is_initialized 门控 → 统一层永不装配」缺口，本文件把设计态钉住防回退：

1. TTSManager 有 initialize()/is_initialized 语义（``manager.py``），构造
   即置 ``_initialized=False``——但所有合成入口（synthesize/synthesize_stream）
   都经 ``_ensure_ready()`` 咽喉按需初始化，lazy_release 模式（默认，见
   ``_resolve_tts_lazy_release``）下启动跳过引擎加载是**设计**而非遗漏。
2. ``_on_startup`` 在常驻模式（lazy_release=False）下 ``await initialize()``
   （app.py TTS 装配段），随后 VoiceEngine[TTS] 装配无 is_initialized 门控
   （H2-C）——常驻模式下统一层包的是已初始化的真引擎。
3. ASR 的病根（VoiceEngine[ASR] 门控在 is_initialized 上、启动从不初始化 →
   永不装配，见 tests/unit/api/test_asr_manager_startup_init.py）在 TTS 侧
   不存在：VoiceEngine[TTS] 只看 tts_manager 在不在。

单元档不碰真权重（本机 moss-tts-nano 权重在位，真初始化实测 670MB 加载）：
常驻模式启动用例把 moss/edge 的**构造接缝**桩成假引擎（同
``tests/unit/tts/conftest.py`` 夹具口径），真权重只在显式集成档加载。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import _resolve_tts_lazy_release, create_app
from neurova.api.endpoints import get_app_state
from neurova.tts import manager as tts_manager_mod
from neurova.tts.manager import TTSConfig, TTSManager
from tests.unit.tts._fakeEngines import fakeHeavyFactory, fakeLightFactory


def _patchFakeEngines(monkeypatch):
    """把 moss/edge 的构造接缝都桩掉：单元档任何路径不得碰真权重/真在线服务。"""
    monkeypatch.setattr(tts_manager_mod, "MOSSNanTTS", fakeHeavyFactory)
    monkeypatch.setattr(tts_manager_mod, "EdgeTTS", fakeLightFactory)


@pytest.fixture()
def startedApp(monkeypatch):
    """默认（lazy_release=on）全量启动：断言 tts_manager 的设计态。"""
    monkeypatch.setenv("NEUROVA_ENV", "test")
    _patchFakeEngines(monkeypatch)
    app = create_app(enable_memory=False, enable_channels=False)
    with TestClient(app):
        yield app


class TestLazyStartupDefersByDesign:
    @pytest.mark.timeout(120)
    def testTtsManagerAssembledAndDeferredAfterStartup(self, startedApp):
        state = get_app_state()
        manager = state["tts_manager"]
        assert manager is not None, "启动后 tts_manager 缺席"
        # H2-C：VoiceEngine[TTS] 装配不设 is_initialized 门控——本卡要钉的形状
        assert "tts" in state["voice_engines"], "VoiceEngine[TTS] 未装配"
        assert manager._config.lazy_release is True, (
            "默认装配应是 lazy_release=on（启动跳过引擎加载）")
        assert manager.is_initialized is False, (
            "lazy 模式启动后未初始化是设计态（首次合成经 _ensure_ready 按需就绪），"
            "不是装配缺口——此断言红说明启动路径偷偷加载了引擎")

    def testLazyThroatInitializesOnFirstSynthesize(self, monkeypatch):
        """设计态的另一半：lazy manager 首次合成即自愈就绪（deferred ≠ forgotten）。"""
        monkeypatch.setenv("NEUROVA_ENV", "test")
        _patchFakeEngines(monkeypatch)
        manager = TTSManager(config=TTSConfig(engine="auto", lazy_release=True))
        assert manager.is_initialized is False

        audio = asyncio.run(manager.synthesize("你好"))

        assert manager.is_initialized is True, "首次合成应经 _ensure_ready 完成初始化"
        assert audio, "初始化后合成应产出音频"


class TestResidentModeInitializesAtStartup:
    @pytest.mark.timeout(120)
    def testTtsManagerInitializedAfterStartupInResidentMode(self, monkeypatch):
        """常驻模式（NEUROVA_TTS_LAZY_RELEASE=0）：启动即 await initialize()，
        VoiceEngine[TTS] 包的是已初始化引擎（启动段先 initialize 再建统一层）。"""
        monkeypatch.setenv("NEUROVA_ENV", "test")
        monkeypatch.setenv("NEUROVA_TTS_LAZY_RELEASE", "0")
        _patchFakeEngines(monkeypatch)
        app = create_app(enable_memory=False, enable_channels=False)
        with TestClient(app):
            state = get_app_state()
            manager = state["tts_manager"]
            assert manager is not None
            assert manager.is_initialized is True, "常驻模式启动后 TTS 必须已完成初始化"
            assert manager.engine_name == "moss-nano"
            engine = state["voice_engines"].get("tts")
            assert engine is not None, "常驻模式下 VoiceEngine[TTS] 必须装配"
            assert engine.is_available() is True, "统一层应读到已初始化的可用引擎"


class TestResolverDefaults:
    """lazy_release 默认值解析：默认 on，env 部署级开关优先，config 键其次。"""

    def testLazyReleaseDefaultIsOn(self):
        assert _resolve_tts_lazy_release("", None) is True
        assert _resolve_tts_lazy_release("0", None) is False
        assert _resolve_tts_lazy_release("1", None) is True
        assert _resolve_tts_lazy_release("", False) is False
        assert _resolve_tts_lazy_release("", True) is True
        assert _resolve_tts_lazy_release("", None) is True


class TestManagerInitializeSemantics:
    def testConstructThenInitializeReachesReadyState(self, monkeypatch):
        """TTSManager 设计语义：构造未就绪，initialize() 后就绪——
        常驻模式启动分支依赖的正是这条语义。"""
        monkeypatch.setenv("NEUROVA_ENV", "test")
        _patchFakeEngines(monkeypatch)
        manager = TTSManager(config=TTSConfig(engine="auto", lazy_release=False))
        assert manager.is_initialized is False
        assert asyncio.run(manager.initialize()) is True
        assert manager.is_initialized is True
