"""social_search 渐进式暴露的 CLI 面测试。

死门修复后契约：run_doctor 走真实 agent-reach CLI doctor（此前 import 的
agent_reach.core／agent_reach.config 库面在 PyPI 与源码仓都不存在，门永远
落到 backend_unavailable）；执行走 CLI 渠道动作，登录态/接入引导由 CLI
错误码（NEED_SETUP/NEED_LOGIN）映射。
"""

import json
from types import SimpleNamespace

import pytest

from neurova.web_reach import agent_reach_cli as cli
from neurova.web_reach.reach import run_doctor, social_search

_DOCTOR_OK = json.dumps(
    {
        "schema_version": 1,
        "ok": True,
        "action": "doctor",
        "result": {
            "version": "1.6.0",
            "channels": [
                {"channel": "twitter", "level": "experimental", "status": "unverified",
                 "problems": [], "hint": "agent-reach check twitter", "regressed": False},
                {"channel": "reddit", "level": "optional", "status": "not_added",
                 "problems": [], "hint": "agent-reach add reddit", "regressed": False},
                {"channel": "xiaohongshu", "level": "optional", "status": "needs_setup",
                 "problems": ["opencli not installed: run `agent-reach add xiaohongshu`"],
                 "hint": "", "regressed": False},
            ],
        },
        "error": None,
    },
    ensure_ascii=False,
)
# 渠道动作的**归一结果**（桥接 runChannelAction 的产出形态，非原始 envelope）
_SEARCH_OK = {
    "success": True,
    "channel": "twitter",
    "action": "search",
    "backend": "opencli",
    "items": [{"title": "t1", "url": "https://x.com/1"}],
    "meta": {"elapsed_ms": 900, "attempts": []},
}
_SEARCH_NEED_LOGIN = {
    "success": False,
    "code": "NEED_LOGIN",
    "error": "login required",
    "hint": "Run `agent-reach login twitter`",
}


def _patchDoctor(monkeypatch, *, doctorResult=None, searchResult=None):
    monkeypatch.setattr(cli, "runDoctor", lambda: doctorResult)
    monkeypatch.setattr(cli, "runChannelAction", lambda *a, **kw: searchResult)


class TestRunDoctorRealCli:
    def test_doctorGoesThroughCliBridge(self, monkeypatch):
        """run_doctor 必须走 CLI 桥接——幽灵库面（agent_reach.core）已退役。"""
        doctorEnvelope = json.loads(_DOCTOR_OK)
        monkeypatch.setattr(
            cli, "runDoctor", lambda: {
                "success": True, "data": doctorEnvelope["result"], "version": "1.6.0",
            }
        )
        result = run_doctor()
        # 原样交回上游体检读数（不包裹、不污染字段）
        assert result == doctorEnvelope["result"]
        assert result["version"] == "1.6.0"

    def test_doctorUnavailableReportedHonestly(self, monkeypatch):
        monkeypatch.setattr(
            cli, "runDoctor", lambda: {
                "success": False, "not_installed": True,
                "error": cli.INSTALL_GUIDE,
            }
        )
        result = run_doctor()
        assert result["success"] is False
        assert "uv tool install" in result["error"]


class TestSocialSearchLadder:
    def test_cliMissingReturnsBackendUnavailableWithInstallGuide(self, monkeypatch):
        _patchDoctor(
            monkeypatch,
            doctorResult={"success": False, "not_installed": True, "error": cli.INSTALL_GUIDE},
        )
        result = social_search("reddit", "python")
        assert result["success"] is False
        assert result["backend_unavailable"] is True
        assert "uv tool install" in result["guide"]

    def test_channelNotAddedGuidesToAdd(self, monkeypatch):
        doctorEnvelope = json.loads(_DOCTOR_OK)
        _patchDoctor(
            monkeypatch,
            doctorResult={"success": True, "data": doctorEnvelope["result"], "version": "1.6.0"},
        )
        result = social_search("reddit", "python")
        assert result["success"] is False
        assert result["needs_setup"] is True
        assert "agent-reach add reddit" in result["guide"]

    def test_channelNeedsSetupCarriesProblems(self, monkeypatch):
        doctorEnvelope = json.loads(_DOCTOR_OK)
        _patchDoctor(
            monkeypatch,
            doctorResult={"success": True, "data": doctorEnvelope["result"], "version": "1.6.0"},
        )
        result = social_search("xiaohongshu", "咖啡")
        assert result["success"] is False
        assert result["needs_setup"] is True
        assert "opencli not installed" in result["guide"]

    def test_readyChannelExecutesCliSearch(self, monkeypatch):
        doctorEnvelope = json.loads(_DOCTOR_OK)
        calls = {}

        def fakeAction(channel, action, target=None, limit=None, extraArgs=None):
            calls.update(channel=channel, action=action, target=target, limit=limit)
            return dict(_SEARCH_OK)

        monkeypatch.setattr(
            cli, "runDoctor",
            lambda: {"success": True, "data": doctorEnvelope["result"], "version": "1.6.0"},
        )
        monkeypatch.setattr(cli, "runChannelAction", fakeAction)
        result = social_search("twitter", "neurova", limit=3)
        assert result["success"] is True
        assert result["platform"] == "twitter"
        assert result["query"] == "neurova"
        assert result["items"][0]["title"] == "t1"
        assert calls == {"channel": "twitter", "action": "search", "target": "neurova", "limit": 3}

    def test_needLoginMapsToLoginGuide(self, monkeypatch):
        doctorEnvelope = json.loads(_DOCTOR_OK)
        monkeypatch.setattr(
            cli, "runDoctor",
            lambda: {"success": True, "data": doctorEnvelope["result"], "version": "1.6.0"},
        )
        monkeypatch.setattr(cli, "runChannelAction", lambda *a, **kw: dict(_SEARCH_NEED_LOGIN))
        result = social_search("twitter", "x")
        assert result["success"] is False
        assert result["needs_login"] is True
        assert "agent-reach login twitter" in result["guide"]

    def test_unsupportedPlatformRejected(self):
        result = social_search("weibo", "x")
        assert result["success"] is False
        assert "twitter" in result["error"]
