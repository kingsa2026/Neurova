# -*- coding: utf-8 -*-
"""本地 Whisper opt-in 同意门测试（管理员同意后下载安装兜底）。

锁定：未同意链中跳过（显式选择也拒绝）/ 同意后参与 / 状态端点 /
consent 端点 admin 门。
"""
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_manager(consent=False, funasr_ok=True):
    from neurova.asr.manager import ASRConfig, ASRManager

    config = ASRConfig(engine="auto", local_whisper_consent=consent)
    mgr = ASRManager(config)

    async def fake_init(name):
        if name == "funasr":
            return funasr_ok  # 未装 funasr 环境下 False
        if name == "remote_whisper":
            return False  # 测试态无 key → 诚实 False
        if name == "whisper":
            # 动态读 consent（grant 置 True 后才成功；闭包旧值会让
            # consent 端点测试永远 False）
            return mgr._config.local_whisper_consent
        return False

    mgr._initialize_engine = fake_init
    return mgr


def test_chain_skips_whisper_without_consent():
    mgr = _make_manager(consent=False, funasr_ok=False)
    ok = asyncio.run(mgr._initialize_with_fallback())
    # 未同意：funasr False → remote False → whisper 被跳过 → 整链失败
    assert ok is False
    assert mgr._engine_name is None


def test_chain_uses_whisper_after_consent():
    mgr = _make_manager(consent=True, funasr_ok=False)
    ok = asyncio.run(mgr._initialize_with_fallback())
    assert ok is True
    assert mgr._engine_name == "whisper"


def test_explicit_whisper_blocked_without_consent():
    from neurova.asr.manager import ASRConfig, ASRManager

    mgr = ASRManager(ASRConfig(engine="whisper", local_whisper_consent=False))
    mgr._initialize_engine = MagicMock(
        side_effect=lambda name: asyncio.sleep(0, result=True)
    )
    ok = asyncio.run(mgr.initialize())
    assert ok is False  # 同意门拒绝，不走 _initialize_engine


def test_get_consent_status_shape():
    mgr = _make_manager(consent=False)
    status = mgr.get_consent_status()
    assert status["consent"] is False
    assert status["chain"] == ["funasr", "remote_whisper", "whisper"]
    assert "model_ready" in status and "model_dir" in status


@pytest.fixture()
def client(monkeypatch):
    from neurova.api.endpoints import audio as audio_mod

    fake_mgr = _make_manager(consent=False, funasr_ok=False)
    monkeypatch.setattr(audio_mod, "_get_asr_manager", lambda: fake_mgr)

    from neurova.api.auth import get_current_user_or_default

    app = FastAPI()
    app.include_router(audio_mod.router, prefix="/audio")
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "user_id": "u-admin",
        "role": "admin",
    }
    return TestClient(app), fake_mgr


def test_status_endpoint(client):
    tc, mgr = client
    resp = tc.get("/audio/asr/local-whisper/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["consent"] is False


def test_consent_endpoint_enables_whisper(client):
    tc, mgr = client
    resp = tc.post("/audio/asr/local-whisper/consent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"]["consent"] is True
    assert body["data"]["enabled"] is True  # 同意后 whisper 初始化成功
    assert mgr._engine_name == "whisper"
