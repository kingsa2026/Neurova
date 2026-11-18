"""QwenPaw 对照批 C12：e2e 双档 marker + page object 骨架。

红灯（实现前）：tests/e2e/pages/ 不存在、conftest 无 e2e_mock/e2e_real
marker 注册、tests/e2e/_e2e.py 临时脚本未退役。

绿灯：
- marker 双档：e2e_mock（in-process mock LLM，恒跑）与 e2e_real（真后端
  子进程，NEUROVA_E2E_REAL 未开时诚实跳过）；
- shouldSkipReal 纯函数钉跳过语义；
- BasePage：URL 解析（环境变量优先）与 get/post 封装。
"""

import importlib.util
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parents[1] / "e2e"


def _load(module_name: str, relative: str):
    spec = importlib.util.spec_from_file_location(module_name, E2E_DIR / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMarkersRegistered:

    def test_conftest_declares_dual_tier_markers(self):
        source = (E2E_DIR / "conftest.py").read_text(encoding="utf-8")
        assert "e2e_mock" in source, "conftest 必须注册 e2e_mock marker（mock 档）"
        assert "e2e_real" in source, "conftest 必须注册 e2e_real marker（真后端档）"

    def test_legacy_temp_script_retired(self):
        assert not (E2E_DIR / "_e2e.py").exists(), \
            "tests/e2e/_e2e.py 是临时脚本（自述'临时脚本'且零引用），按测试纪律应退役"


class TestShouldSkipReal:

    def test_real_tier_runs_when_enabled(self):
        mod = _load("e2e_pages_base", "pages/base.py")
        skip, reason = mod.shouldSkipReal("1")
        assert (skip, reason) == (False, "")

    def test_real_tier_skips_when_disabled(self):
        mod = _load("e2e_pages_base", "pages/base.py")
        skip, reason = mod.shouldSkipReal("")
        assert skip is True and "NEUROVA_E2E_REAL" in reason

    def test_mock_tier_never_skips(self):
        mod = _load("e2e_pages_base", "pages/base.py")
        assert mod.shouldSkipMock("") == (False, "")


class TestBasePage:

    def test_resolve_base_url_env_priority(self, monkeypatch):
        mod = _load("e2e_pages_base", "pages/base.py")
        monkeypatch.setenv("NEUROVA_E2E_BASE_URL", "http://127.0.0.1:9999")
        assert mod.resolveBaseUrl(port=9527) == "http://127.0.0.1:9999"
        monkeypatch.delenv("NEUROVA_E2E_BASE_URL")
        assert mod.resolveBaseUrl(port=9527) == "http://127.0.0.1:9527"

    def test_base_page_get_returns_status_and_json(self, tmp_path, monkeypatch):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            mod = _load("e2e_pages_base", "pages/base.py")
            page = mod.BasePage(base_url=f"http://127.0.0.1:{server.server_port}")
            status, data = page.get("/health")
            assert status == 200 and data == {"ok": True}
        finally:
            server.shutdown()
