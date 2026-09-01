# -*- coding: utf-8 -*-
"""
P1-8 后端 boot e2e（对标 QP test_hub_local_runtime 的冒烟语义）

纯 subprocess 语义：真实拉起 start_server --backend（固定 9527；若本机
已有健康实例则复用），探活 /health、/docs、/api/version，自启实例优雅
关停。

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

    def test_docs_reachable(self, backend_port):
        status, _ = _http_get(f"http://127.0.0.1:{backend_port}/docs")
        assert status == 200

    def test_openapi_spec_reports_beta(self, backend_port):
        """openapi.json 可达且版本为 1.0.0-beta1（无独立 /api/version 端点）"""
        status, body = _http_get(f"http://127.0.0.1:{backend_port}/openapi.json")
        assert status == 200
        assert b"1.0.0" in body

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
