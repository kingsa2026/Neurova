# -*- coding: utf-8 -*-
"""
P1-8 后端 boot e2e

纯 subprocess 语义：真实拉起 start_server --backend（固定 9527；若本机
已有健康实例则复用），探活 /health（含版本上报）；钉死 API 文档面
（/docs /redoc /openapi.json）已移除为 404；自启实例优雅关停。

诚实标注：
- mock LLM chat / 登录需要账号与 LLM mock 注入点（后端尚无环境级开关），
  不做假断言；API 级生命周期冒烟见 TestApiSmoke（复用 boot 后端，
  无凭据的写接口允许 401/403——生命周期存在性以可探活为准）。
- in-process create_app() 冒烟曾实测卡死（全子系统初始化），故一律
  走真实子进程。
"""
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = 9527


def _port_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get(url: str, timeout: float = 5.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _wait_health(port: int, seconds: float = 90.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, _ = _http_get(f"http://127.0.0.1:{port}/health", timeout=2)
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


@pytest.fixture(scope="module")
def backend_port():
    """已有健康实例复用之；否则 subprocess 拉起，结束关停（仅限自启实例）。"""
    if _port_open(BACKEND_PORT) and _wait_health(BACKEND_PORT, seconds=3):
        yield BACKEND_PORT
        return

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "start_server.py"), "--backend"],
        cwd=str(PROJECT_ROOT),
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        assert _wait_health(BACKEND_PORT, seconds=90), "后端 90s 内未就绪"
        yield BACKEND_PORT
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


class TestBackendBoot:
    """真实进程 boot 冒烟（subprocess 拉起或复用常驻实例）"""

    def test_health_endpoint(self, backend_port):
        status, _ = _http_get(f"http://127.0.0.1:{backend_port}/health")
        assert status == 200

    def test_docs_surface_removed(self, backend_port):
        """API 文档面已移除（2026-09-16）：/docs /redoc /openapi.json 必须 404。

        Swagger/ReDoc 全链路零消费者，且随 0.0.0.0 监听把完整 API 面暴露到
        局域网。本用例钉住移除契约，防 FastAPI 默认值把文档面悄悄带回来。
        """
        for path in ("/docs", "/redoc", "/openapi.json"):
            try:
                code, _ = _http_get(f"http://127.0.0.1:{backend_port}{path}")
            except urllib.error.HTTPError as e:
                code = e.code
            assert code == 404, f"{path} 应 404（文档面已移除），实际 {code}"

    def test_health_reports_version(self, backend_port):
        """/health 报 API 版本（2026-09-16 起版本上报自 openapi.json 接管至此）"""
        status, body = _http_get(f"http://127.0.0.1:{backend_port}/health")
        assert status == 200
        import json

        version = json.loads(body).get("version", "")
        assert "1.0.0" in version, f"/health 未报版本，实际: {version!r}"

    def test_metrics_scrape(self, backend_port):
        """/metrics prometheus 文本可抓取（P2-4 观测底座 e2e 验证）"""
        status, body = _http_get(f"http://127.0.0.1:{backend_port}/metrics")
        assert status == 200

    def test_tool_layers_requires_auth(self, backend_port):
        """未认证访问受保护资源必须 401（P0-1 e2e 复验）"""
        try:
            status, _ = _http_get(
                f"http://127.0.0.1:{backend_port}/api/v1/tool-layers/mcp-servers"
            )
            # 401/403 都是正确拒绝形态；200 反而是漏洞
            assert status in (401, 403)
        except urllib.error.HTTPError as e:
            assert e.code in (401, 403)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
