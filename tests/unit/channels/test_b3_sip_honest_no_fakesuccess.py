"""B-3: sip.py 假成功残留清理（红→绿 TDD）

修复前缺陷（诚实性）:
- _init_dev_mode: pyVoIP 缺失时 "模拟初始化" 置 _initialized=True 并 return True
- _init_production_mode: 无条件置 _initialized=True 并 return True（LiveKit 对接从未实现）
- _send_production_audio: 无条件 return True
- _send_dev_audio: pyVoIP 缺失时 "[SIP模拟]" return True

契约: 未实现的能力必须 logging.warning("SIP 通道未实现") 并返回 False/None，
真实可用的路径（pyVoIP 就绪的 dev 初始化/发送）保持可用。
"""

import logging
import sys
import types

import pytest

import neurova.channels.sip as sip_module
from neurova.channels.sip import SIPAdapter


@pytest.fixture
def adapter():
    return SIPAdapter()


# ============================================================
# 假成功路径：修复后必须诚实返回 False
# ============================================================


def test_init_dev_mode_without_pyvoip_returns_false(adapter, monkeypatch, caplog):
    """pyVoIP 缺失时禁止"模拟初始化"假成功"""
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", False)
    with caplog.at_level(logging.WARNING):
        assert adapter._init_dev_mode() is False
    assert adapter._initialized is False, "未实现的能力不得置 _initialized=True"
    assert any("SIP 通道未实现" in r.message for r in caplog.records)


def test_init_production_mode_returns_false(adapter, caplog):
    """LiveKit Production 对接从未实现——禁止无条件 return True"""
    adapter.sip_server = "sip.example.com"
    with caplog.at_level(logging.WARNING):
        assert adapter._init_production_mode() is False
    assert adapter._initialized is False
    assert any("SIP 通道未实现" in r.message for r in caplog.records)


def test_send_production_audio_returns_false(adapter, caplog):
    """Production 音频发送从未实现——禁止无条件 return True"""
    with caplog.at_level(logging.WARNING):
        assert adapter._send_production_audio(b"\x00\x01", "call1") is False
    assert any("SIP 通道未实现" in r.message for r in caplog.records)


def test_send_dev_audio_without_pyvoip_returns_false(adapter, monkeypatch, caplog):
    """pyVoIP 缺失时禁止"[SIP模拟]"假成功"""
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", False)
    with caplog.at_level(logging.WARNING):
        assert adapter._send_dev_audio(b"\x00\x01", "call1") is False
    assert "[SIP模拟]" not in caplog.text


def test_authenticate_dev_mode_without_pyvoip_honest_fail(adapter, monkeypatch):
    """dev 模式 + pyVoIP 缺失 → authenticate 诚实失败（经由 _init_sip）"""
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", False)
    assert adapter.authenticate({"sip_username": "u", "sip_password": "p", "sip_mode": "dev"}) is False


def test_authenticate_production_mode_honest_fail(adapter, monkeypatch):
    """production 模式初始化未实现 → authenticate 诚实失败"""
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", True)
    assert adapter.authenticate({"sip_username": "u", "sip_password": "p", "sip_mode": "production"}) is False


def test_play_welcome_message_no_longer_fakes_success(adapter, monkeypatch):
    """play_welcome_message 链路（唯一可达入口）不得再返回假成功 True"""
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", False)
    monkeypatch.setattr(adapter, "text_to_speech", lambda text: b"fake-audio", raising=False)

    adapter.sip_mode = "dev"
    assert adapter.play_welcome_message("call1") is False

    adapter.sip_mode = "production"
    assert adapter.play_welcome_message("call1") is False


# ============================================================
# 真实可用的路径必须保留：pyVoIP 就绪时 dev 初始化/发送仍然工作
# ============================================================


class _FakeSIPClient:
    """可控成功/失败的 pyVoIP.SIPClient 替身（不触网）"""

    fail_with: Exception = None
    registered: list = []

    def __init__(self, server=None, port=None, username=None, password=None, transport=None):
        self.username = username
        _FakeSIPClient.init_kwargs = {
            "server": server,
            "port": port,
            "username": username,
            "password": password,
            "transport": transport,
        }

    def register(self):
        if _FakeSIPClient.fail_with is not None:
            raise _FakeSIPClient.fail_with
        _FakeSIPClient.registered.append(self.username)


@pytest.fixture
def fake_pyvoip(monkeypatch):
    module = types.ModuleType("pyvoip")
    module.SIPClient = _FakeSIPClient
    monkeypatch.setitem(sys.modules, "pyvoip", module)
    monkeypatch.setattr(sip_module, "pyvoip", module, raising=False)
    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", True)
    _FakeSIPClient.fail_with = None
    _FakeSIPClient.registered = []
    return module


def test_init_dev_mode_with_pyvoip_success_path_kept(adapter, fake_pyvoip):
    """pyVoIP 就绪：dev 初始化真实路径保留（创建客户端 + 注册）"""
    adapter.sip_username = "u"
    adapter.sip_password = "p"
    adapter.sip_port = 5061
    assert adapter._init_dev_mode() is True
    assert adapter._initialized is True
    assert adapter._voip_client is not None
    assert _FakeSIPClient.registered == ["u"]


def test_init_dev_mode_with_pyvoip_failure_honest(adapter, fake_pyvoip):
    """pyVoIP 就绪但注册失败（如 OSError）→ 如实返回 False"""
    _FakeSIPClient.fail_with = OSError("network unreachable")
    assert adapter._init_dev_mode() is False
    assert adapter._initialized is False


# ============================================================
# 假成功代码残留清零（源级断言，防"模拟"字样回流）
# ============================================================


def test_no_mock_success_residue_in_source():
    import inspect

    src = inspect.getsource(sip_module)
    assert "模拟初始化" not in src, "_init_dev_mode 不得再出现'模拟初始化'假成功路径"
    assert "[SIP模拟]" not in src, "_send_dev_audio 不得再出现'[SIP模拟]'假成功路径"
    assert "模拟" not in inspect.getsource(SIPAdapter._init_dev_mode)
    assert "模拟" not in inspect.getsource(SIPAdapter._init_production_mode)
    assert "模拟" not in inspect.getsource(SIPAdapter._send_dev_audio)
    assert "模拟" not in inspect.getsource(SIPAdapter._send_production_audio)
