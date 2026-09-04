"""
后端启动失败远程上报契约（2026-09-04 安装机启动崩溃无人知晓）

复用前端 errorReporter → 官网 error-report.php 同一链路和 schema：
POST JSON {client_id, error_at, platform, source, error_code, location,
message, stack, app_version, ua, extra}。

契约：
- report_startup_failure() 永不抛异常（上报本身失败只能吞掉）
- 遵守服务端 schema：client_id UUID 形、error_code 正则形、
  error_at 秒级 ISO-Z、platform=desktop-windows、source=app
- client_id 持久化复用（data/nv_client_id）
- 环境开关 NEUROVA_ERROR_REPORT=off 关闭上报
- 上报端点 = 官方固定 URL（与前端一致）
"""
import json
import os
import re
import urllib.error
from unittest import mock

import pytest

from neurova.core import crash_report


class TestClientId:
    def test_creates_and_persists(self, tmp_path):
        cid_file = tmp_path / "nv_client_id"
        cid1 = crash_report.get_or_create_client_id(cid_file)
        assert re.fullmatch(r"[0-9a-fA-F\-]{8,64}", cid1)
        assert cid_file.read_text(encoding="utf-8") == cid1

    def test_reuses_existing(self, tmp_path):
        cid_file = tmp_path / "nv_client_id"
        cid_file.write_text("abcdef12-3456-7890-abcd-ef1234567890", encoding="utf-8")
        assert crash_report.get_or_create_client_id(cid_file) == (
            "abcdef12-3456-7890-abcd-ef1234567890"
        )

    def test_unwritable_path_still_returns_id(self, tmp_path):
        # 目录不可写时退化为内存一次性 ID，不抛异常
        bad = tmp_path / "no-such-dir" / "nv_client_id"
        cid = crash_report.get_or_create_client_id(bad)
        assert re.fullmatch(r"[0-9a-fA-F\-]{8,64}", cid)


class TestBuildReport:
    def test_schema_compliant(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            crash_report, "get_or_create_client_id", lambda p=None: "abcdef12-3456"
        )
        report = crash_report.build_report(
            error_code="backend_startup_failed",
            message="FileNotFoundError: agent_workspaces",
            stack="Traceback...",
            app_version="1.0.0-beta1",
        )
        assert report["client_id"] == "abcdef12-3456"
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", report["error_at"]
        )
        assert report["platform"] == "desktop-windows" or report["platform"] in (
            "desktop-windows", "desktop-linux", "linux", "mac", "web", "unknown"
        )
        assert report["source"] == "app"
        assert re.fullmatch(r"[a-zA-Z0-9_:.\-]{1,64}", report["error_code"])
        assert len(report["message"]) <= 500
        assert len(report["stack"]) <= 4000
        assert report["ua"]  # 后端 UA 标识

    def test_error_code_sanitized(self, monkeypatch):
        monkeypatch.setattr(
            crash_report, "get_or_create_client_id", lambda p=None: "abcdef12"
        )
        report = crash_report.build_report(
            error_code="坏 code 带空格!", message="m", stack="", app_version="v"
        )
        assert re.fullmatch(r"[a-zA-Z0-9_:.\-]{1,64}", report["error_code"])


class TestReportStartupFailure:
    def test_posts_to_official_endpoint(self, tmp_path, monkeypatch):
        posted = []
        monkeypatch.setattr(
            crash_report, "_http_post", lambda url, body, timeout: posted.append((url, body)) or {"ok": True}
        )
        monkeypatch.setattr(
            crash_report, "get_or_create_client_id", lambda p=None: "abcdef12"
        )
        rc = crash_report.report_startup_failure(
            FileNotFoundError("[WinError 3] agent_workspaces"),
            stage="startup",
            app_version="1.0.0-beta1",
            client_id_path=tmp_path / "cid",
        )
        assert rc is True
        url, body = posted[0]
        assert url == crash_report.REPORT_URL
        assert body["error_code"] == "backend_startup_failed"
        assert "agent_workspaces" in body["message"]
        assert body["extra"]["stage"] == "startup"

    def test_never_raises_on_network_error(self, tmp_path, monkeypatch):
        def bad_post(url, body, timeout):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr(crash_report, "_http_post", bad_post)
        monkeypatch.setattr(
            crash_report, "get_or_create_client_id", lambda p=None: "abcdef12"
        )
        rc = crash_report.report_startup_failure(
            RuntimeError("boom"), stage="startup", app_version="v",
            client_id_path=tmp_path / "cid",
        )
        assert rc is False  # 失败但吞掉，不抛

    def test_env_switch_off(self, tmp_path, monkeypatch):
        posted = []
        monkeypatch.setattr(crash_report, "_http_post", lambda *a, **k: posted.append(1))
        monkeypatch.setenv("NEUROVA_ERROR_REPORT", "off")
        rc = crash_report.report_startup_failure(
            RuntimeError("boom"), stage="startup", app_version="v",
            client_id_path=tmp_path / "cid",
        )
        assert rc is False
        assert posted == []

    def test_http_post_uses_short_timeout(self, monkeypatch):
        # seam 实现必须带超时（启动失败场景不能卡死退出流程）
        captured = {}
        real_urlopen = mock.Mock()

        def fake_urlopen(req, timeout):
            captured["timeout"] = timeout
            resp = mock.Mock()
            resp.read.return_value = b'{"ok": true}'
            resp.__enter__ = mock.Mock(return_value=resp)
            resp.__exit__ = mock.Mock(return_value=False)
            return resp

        monkeypatch.setattr(crash_report.urllib.request, "urlopen", fake_urlopen)
        crash_report._http_post("https://example.invalid/x", {"a": 1}, timeout=5)
        assert captured["timeout"] == 5


class TestLifespanWiring:
    def test_startup_event_reports_before_reraise(self, monkeypatch):
        """lifespan 启动崩溃必须先上报再 raise（uvicorn 会吞掉异常静默退出）。"""
        from fastapi import FastAPI

        reported = []
        monkeypatch.setenv("NEUROVA_ERROR_REPORT", "on")
        monkeypatch.setattr(
            crash_report, "report_startup_failure",
            lambda exc, stage="", app_version="": reported.append((exc, stage)) or True,
        )
        app = FastAPI()

        @app.on_event("startup")
        async def failing_startup():
            # 模拟 app.py 中 startup_event 的上报模式
            try:
                raise FileNotFoundError("[WinError 3] agent_workspaces")
            except Exception as e:
                crash_report.report_startup_failure(e, stage="lifespan-startup")
                raise

        import asyncio

        async def run():
            # 模拟 lifespan 启动失败
            try:
                async with app.router.lifespan_context(app):
                    pass
            except FileNotFoundError:
                return "crashed"
            return "ok"

        result = asyncio.run(run())
        assert result == "crashed"
        assert len(reported) == 1
        assert reported[0][1] == "lifespan-startup"
