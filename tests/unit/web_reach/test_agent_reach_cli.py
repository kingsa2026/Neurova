"""agent-reach CLI 桥接单元测试。

契约以 v1.6.0 实测输出为准（stdout 单行 JSON envelope）：
- 常规 envelope：{schema_version, ok, channel, action, backend, items, meta, error}
- doctor：{ok, action:"doctor", result:{version, channels:[{channel, level, status, ...}]}}
- 错误码：NEED_SETUP/NEED_LOGIN/UPSTREAM_BROKEN/TIMEOUT/RATE_LIMITED/NOT_FOUND/BAD_INPUT
"""

import json
import subprocess
from types import SimpleNamespace

import pytest

from neurova.web_reach import agent_reach_cli as cli

_OK_READ = (
    '{"schema_version": 1, "ok": true, "channel": "web", "action": "read", '
    '"backend": "jina", "items": [{"title": "Example Domain", '
    '"url": "https://example.com", "text": "hello"}], '
    '"meta": {"elapsed_ms": 1381, "attempts": [{"backend": "jina", "result": "ok"}]}, '
    '"error": null}'
)
_ERR_RATE_LIMITED = (
    '{"schema_version": 1, "ok": false, "channel": "github", "action": "search", '
    '"backend": null, "items": [], "meta": {"elapsed_ms": 1155}, '
    '"error": {"code": "RATE_LIMITED", "message": "GitHub API rate limit", '
    '"hint": "respect retry_after_seconds"}}'
)
_DOCTOR_OK = json.dumps(
    {
        "schema_version": 1,
        "ok": True,
        "action": "doctor",
        "result": {
            "version": "1.6.0",
            "channels": [
                {"channel": "github", "level": "default", "status": "unverified",
                 "problems": [], "hint": "agent-reach check github", "regressed": False},
                {"channel": "twitter", "level": "experimental", "status": "not_added",
                 "problems": [], "hint": "agent-reach add twitter", "regressed": False},
                {"channel": "youtube", "level": "default", "status": "needs_setup",
                 "problems": ["ffmpeg not installed: run `agent-reach add youtube`"],
                 "hint": "", "regressed": False},
            ],
        },
        "error": None,
    },
    ensure_ascii=False,
)


def _patchRun(monkeypatch, *, stdout="", stderr="", returncode=0, raise_exc=None):
    """把桥接模块命名空间里的 subprocess.run 换成假实现，返回捕获器。"""
    captured = {}

    def fakeRun(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(
        cli, "subprocess", SimpleNamespace(run=fakeRun, TimeoutExpired=subprocess.TimeoutExpired)
    )
    return captured


def _patchExecutable(monkeypatch, exe):
    monkeypatch.setattr(cli, "resolveExecutable", lambda: exe)


# ══════════════════════════════════════════════════════════════
# 可执行文件定位
# ══════════════════════════════════════════════════════════════


class TestResolveExecutable:
    def test_usesWhichWhenFound(self, monkeypatch):
        monkeypatch.setattr(cli.shutil, "which", lambda name: "C:/fake/agent-reach.exe")
        assert cli.resolveExecutable() == "C:/fake/agent-reach.exe"

    def test_fallsBackToUvKnownBinDir(self, monkeypatch, tmp_path):
        """uv 装的 CLI 落 ~/.local/bin 且常不在 PATH——按已知目录回退。"""
        monkeypatch.setattr(cli.shutil, "which", lambda name: None)
        fakeHome = tmp_path / "home"
        binDir = fakeHome / ".local" / "bin"
        binDir.mkdir(parents=True)
        (binDir / "agent-reach.exe").write_bytes(b"")
        monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: fakeHome))
        found = cli.resolveExecutable()
        assert found and "agent-reach.exe" in found

    def test_noneWhenAbsent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli.shutil, "which", lambda name: None)
        monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path / "nothing"))
        assert cli.resolveExecutable() is None


# ══════════════════════════════════════════════════════════════
# envelope 归一
# ══════════════════════════════════════════════════════════════


class TestRunAgentReach:
    def test_notInstalledReturnsHonestInstallGuide(self, monkeypatch):
        monkeypatch.setattr(cli, "resolveExecutable", lambda: None)
        result = cli.runAgentReach(["channels"])
        assert result["success"] is False
        assert result["not_installed"] is True
        assert "uv tool install" in result["error"]

    def test_okEnvelopeNormalized(self, monkeypatch):
        _patchRun(monkeypatch, stdout=_OK_READ)
        _patchExecutable(monkeypatch, "AR")
        result = cli.runAgentReach(["read", "https://example.com"])
        assert result["success"] is True
        assert result["channel"] == "web"
        assert result["backend"] == "jina"
        assert result["items"][0]["title"] == "Example Domain"
        assert result["meta"]["elapsed_ms"] == 1381

    def test_errorEnvelopeCarriesCodeMessageHint(self, monkeypatch):
        _patchRun(monkeypatch, stdout=_ERR_RATE_LIMITED)
        _patchExecutable(monkeypatch, "AR")
        result = cli.runAgentReach(["github", "search", "fastapi"])
        assert result["success"] is False
        assert result["code"] == "RATE_LIMITED"
        assert "rate limit" in result["error"]
        assert "retry_after_seconds" in result["hint"]

    def test_nonJsonOutputReportedHonestly(self, monkeypatch):
        _patchRun(monkeypatch, stdout="Traceback (most recent call last): boom")
        _patchExecutable(monkeypatch, "AR")
        result = cli.runAgentReach(["channels"])
        assert result["success"] is False
        assert "非 JSON" in result["error"]
        assert "boom" in result["error"]

    def test_emptyOutputReportedWithStderrTail(self, monkeypatch):
        _patchRun(monkeypatch, stdout="", stderr="winerror 2", returncode=1)
        _patchExecutable(monkeypatch, "AR")
        result = cli.runAgentReach(["channels"])
        assert result["success"] is False
        assert "winerror 2" in result["error"]

    def test_timeoutReportedHonestly(self, monkeypatch):
        _patchRun(monkeypatch, raise_exc=subprocess.TimeoutExpired(cmd="AR", timeout=200))
        _patchExecutable(monkeypatch, "AR")
        result = cli.runAgentReach(["channels"])
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_subprocessGetsUtf8ChildEnvNoShell(self, monkeypatch):
        captured = _patchRun(monkeypatch, stdout=_OK_READ)
        _patchExecutable(monkeypatch, "AR")
        cli.runAgentReach(["channels"])
        assert captured["cmd"][0] == "AR"
        assert captured["kwargs"].get("shell") in (None, False)
        assert captured["kwargs"]["encoding"] == "utf-8"
        assert captured["kwargs"]["env"]  # utf8ChildEnv 产物，非裸 os.environ


# ══════════════════════════════════════════════════════════════
# 三种用法与安全门
# ══════════════════════════════════════════════════════════════


class TestRunRead:
    def test_buildsReadArgv(self, monkeypatch):
        captured = _patchRun(monkeypatch, stdout=_OK_READ)
        _patchExecutable(monkeypatch, "AR")
        cli.runRead("https://example.com")
        assert captured["cmd"] == ["AR", "read", "https://example.com"]

    def test_ssrfBlockedBeforeSubprocess(self, monkeypatch):
        """CLI 自带抓取会绕过本仓出网层——入口必须先过 url_guard 同一道门。"""
        captured = _patchRun(monkeypatch, stdout=_OK_READ)
        result = cli.runRead("http://127.0.0.1:9527/admin")
        assert result["success"] is False
        assert captured == {}, "SSRF 命中时不得发起子进程"

    def test_nonHttpSchemeRejected(self, monkeypatch):
        _patchRun(monkeypatch, stdout=_OK_READ)
        result = cli.runRead("file:///C:/Windows/win.ini")
        assert result["success"] is False


class TestRunChannelAction:
    def test_fullArgvWithLimitAndExtraArgs(self, monkeypatch):
        captured = _patchRun(monkeypatch, stdout=_ERR_RATE_LIMITED)
        _patchExecutable(monkeypatch, "AR")
        cli.runChannelAction(
            "github", "search", target="fastapi", limit=3, extraArgs=["--timeout", "30"]
        )
        assert captured["cmd"] == [
            "AR", "github", "search", "fastapi", "--limit", "3", "--timeout", "30",
        ]

    def test_rejectsLeadingDashTarget(self, monkeypatch):
        captured = _patchRun(monkeypatch, stdout=_OK_READ)
        result = cli.runChannelAction("github", "search", target="--help")
        assert result["success"] is False
        assert "-" in result["error"]
        assert captured == {}, "位置参数以 - 开头会被 CLI 当 flag，必须入口拒绝"

    def test_rejectsLeadingDashChannel(self, monkeypatch):
        result = cli.runChannelAction("-x", "search")
        assert result["success"] is False

    def test_limitOutOfRangeRejected(self, monkeypatch):
        for bad in (0, 101):
            result = cli.runChannelAction("github", "search", target="x", limit=bad)
            assert result["success"] is False, f"limit={bad} 应被拒"

    def test_extraArgsMustBeStrings(self, monkeypatch):
        result = cli.runChannelAction("github", "search", extraArgs=[1, 2])
        assert result["success"] is False


class TestDoctor:
    def test_doctorNormalizedWithChannelDict(self, monkeypatch):
        _patchRun(monkeypatch, stdout=_DOCTOR_OK)
        _patchExecutable(monkeypatch, "AR")
        result = cli.runDoctor()
        assert result["success"] is True
        assert result["version"] == "1.6.0"
        channels = cli.doctorChannels(result["data"])
        assert channels["github"]["status"] == "unverified"
        assert channels["twitter"]["status"] == "not_added"
        assert channels["youtube"]["status"] == "needs_setup"

    def test_doctorErrorPassthrough(self, monkeypatch):
        _patchRun(monkeypatch, stdout=_ERR_RATE_LIMITED)
        _patchExecutable(monkeypatch, "AR")
        result = cli.runDoctor()
        assert result["success"] is False
        assert result["code"] == "RATE_LIMITED"
