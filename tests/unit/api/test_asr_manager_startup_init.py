# -*- coding: utf-8 -*-
"""M6 语音域连带收口：ASRManager 启动即初始化。

缺口（多模态追平批一线3 live-verify 发现）：app.py 只构造 ASRManager
（app.py:537），从不 await initialize() → is_initialized 恒 False →
VoiceEngine[ASR] 永不装配（app.py:1250 门控），渠道语音预检/语音纪要/
本轮转写在真实部署中静默不可用。本测试钉：全量启动后 ASR 管理器必须
完成初始化（测试态 mock 追加链尾），且 VoiceEngine[ASR] 装配到位。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.endpoints import get_app_state


@pytest.fixture()
def started_app(monkeypatch):
    monkeypatch.setenv("NEUROVA_ENV", "test")
    app = create_app(enable_memory=False, enable_channels=False)
    with TestClient(app):
        yield app


class TestAsrManagerStartupInit:
    def test_asr_manager_initialized_after_startup(self, started_app):
        manager = get_app_state()["asr_manager"]
        assert manager is not None
        assert manager.is_initialized is True

    def test_asr_voice_engine_assembled_after_startup(self, started_app):
        engines = get_app_state()["voice_engines"]
        assert "asr" in engines
