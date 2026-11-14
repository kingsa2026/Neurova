# -*- coding: utf-8 -*-
"""遥测 OTLP 导出（P2-13）。

- 显式开关：NEUROVA_TELEMETRY_ENABLED 默认关——关时 record 只丢弃、零网络；
- 脱敏：敏感键（password/token/key/secret/cookie/authorization/credential）
  值打码、字符串 512 截断、嵌套深度 8 截断；
- OTLP/HTTP JSON：logs 服务负载形状（resourceLogs/scopeLogs/logRecords）；
- fail-open：导出网络失败只计 dropped，不抛不阻断调用方；
- 单例 DCL：并发首取只建一个实例。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neurova.telemetry import (
    TelemetryClient,
    getTelemetryClient,
    resetTelemetryClient,
    sanitizeValue,
)


@pytest.fixture(autouse=True)
def freshClient(monkeypatch):
    monkeypatch.setenv("NEUROVA_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("NEUROVA_TELEMETRY_ENDPOINT", "http://127.0.0.1:18973/v1/logs")
    resetTelemetryClient(force=True)
    yield
    resetTelemetryClient(force=True)


class TestSanitize:
    def test_sensitive_keys_redacted(self):
        value = {"password": "hunter2", "api_key": "sk-123", "note": "ok", "token": "t"}
        out = sanitizeValue(value)
        assert out["password"] == "[REDACTED]"
        assert out["api_key"] == "[REDACTED]"
        assert out["token"] == "[REDACTED]"
        assert out["note"] == "ok"

    def test_long_strings_capped(self):
        out = sanitizeValue({"msg": "x" * 600})
        assert len(out["msg"]) == 512 + len("…(truncated)")

    def test_depth_capped(self):
        deep = current = {}
        for _ in range(12):
            current["child"] = {}
            current = current["child"]
        current["leaf"] = "v"
        out = sanitizeValue(deep)
        assert "leaf" not in json.dumps(out)

    def test_list_items_sanitized(self):
        out = sanitizeValue([{"secret": "s"}, "plain"])
        assert out[0]["secret"] == "[REDACTED]"
        assert out[1] == "plain"


class TestClientExport:
    def test_disabled_by_default_no_export(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TELEMETRY_ENABLED", "0")
        resetTelemetryClient(force=True)
        client = getTelemetryClient()
        assert client.record({"error_type": "x"}) is False
        assert client.stats["dropped"] == 1
        assert client.stats["exported"] == 0

    def test_export_posts_otlp_payload(self, monkeypatch):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = json.loads(self.rfile.read(length))
                captured["path"] = self.path
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        monkeypatch.setenv("NEUROVA_TELEMETRY_ENDPOINT", f"http://127.0.0.1:{server.server_port}/v1/logs")
        resetTelemetryClient(force=True)
        client = getTelemetryClient()

        entry = {"error_type": "RuntimeError", "message": "boom", "timestamp": "2026-11-14T10:00:00"}
        assert client.record(entry) is True
        client.flush(timeout=5)
        server.shutdown()
        server.server_close()

        assert captured["path"] == "/v1/logs"
        resource_logs = captured["body"]["resourceLogs"]
        record = resource_logs[0]["scopeLogs"][0]["logRecords"][0]
        assert record["severityText"] == "ERROR"
        assert record["body"]["stringValue"] == json.dumps(entry, ensure_ascii=False)
        assert resource_logs[0]["resource"]["attributes"][0]["key"] == "service.name"

    def test_fail_open_on_network_error(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TELEMETRY_ENDPOINT", "http://127.0.0.1:1/v1/logs")
        resetTelemetryClient(force=True)
        client = getTelemetryClient()
        assert client.record({"error_type": "x"}) is True
        client.flush(timeout=5)
        assert client.stats["dropped"] >= 1
        assert client.stats["exported"] == 0


class TestSingleton:
    def test_dcl_same_instance(self):
        results = []
        barrier = threading.Barrier(4)

        def get():
            barrier.wait()
            results.append(getTelemetryClient())

        threads = [threading.Thread(target=get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r is results[0] for r in results)

    def test_reset_creates_new(self, monkeypatch):
        first = getTelemetryClient()
        resetTelemetryClient(force=True)
        second = getTelemetryClient()
        assert first is not second


class TestErrorLoggerTap:
    def test_frontend_error_entries_reach_telemetry(self, monkeypatch, tmp_path):
        from neurova import error_logger

        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = json.loads(self.rfile.read(length))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        monkeypatch.setenv("NEUROVA_TELEMETRY_ENDPOINT", f"http://127.0.0.1:{server.server_port}/v1/logs")
        monkeypatch.setattr(error_logger, "_telemetrySink", lambda entries: getTelemetryClient().recordBatch(entries))
        resetTelemetryClient(force=True)

        error_logger.write_frontend_errors([{"error_type": "TypeError", "message": "前端错误", "source": "frontend"}])
        client = getTelemetryClient()
        client.flush(timeout=5)
        server.shutdown()
        server.server_close()

        records = captured["body"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        assert records and "前端错误" in records[0]["body"]["stringValue"]
