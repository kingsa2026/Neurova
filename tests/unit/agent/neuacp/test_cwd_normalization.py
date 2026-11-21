# -*- coding: utf-8 -*-
"""G5 接线：外部代理执行体 cwd 符号链接感知规约（fail-closed）。

- 符号链接/junction 形式的 cwd：start 后子进程真实工作目录必须是规约后的
  真实路径（经 agent 回报自身 cwd 验证）；
- 断链 cwd：start 在拉起子进程前即 fail-closed（NeuacpError，文案含 cwd 语义）。
"""
import sys
import time
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient
from tests.unit.security.test_path_guard import makeDirLink


def _cwdAgentScript() -> Path:
    """initialize 应答后推送一条带自身 os.getcwd() 的通知的极简 agent。"""
    script = Path(__file__).resolve().parent / "_cwd_report_agent.py"
    if not script.exists():
        script.write_text(
            r'''import json, os, sys
def send(o):
    sys.stdout.buffer.write((json.dumps(o) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    try:
        msg = json.loads(line.decode("utf-8"))
    except Exception:
        continue
    if msg.get("method") == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": msg["params"]["protocolVersion"],
            "agentCapabilities": {}}})
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1", "update": {"sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": os.getcwd()}}}})
    elif msg.get("id") is not None:
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
''',
            encoding="utf-8")
    return script


def _waitFor(events, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for method, params in events:
            if method == "session/update":
                update = params.get("update") or {}
                if update.get("sessionUpdate") == "agent_message_chunk":
                    return (update.get("content") or {}).get("text", "")
        time.sleep(0.05)
    raise AssertionError("超时未收到 agent 的 cwd 回报")


def test_start_normalizes_symlinked_cwd(tmp_path):
    real = tmp_path / "real-dir"
    real.mkdir()
    link = tmp_path / "link-dir"
    makeDirLink(link, real)
    events = []
    client = NeuacpClient(
        [sys.executable, str(_cwdAgentScript())],
        cwd=str(link),
        on_event=lambda method, params: events.append((method, params)),
    )
    try:
        client.start()
        reported = _waitFor(events)
        assert reported == str(real.resolve()), (
            f"子进程真实 cwd 应为规约后的真实路径 {real.resolve()}，实际 {reported}")
    finally:
        client.terminate()


def test_start_fails_closed_on_broken_cwd(tmp_path):
    broken = tmp_path / "broken-link"
    makeDirLink(broken, tmp_path / "does-not-exist")
    client = NeuacpClient(
        [sys.executable, str(_cwdAgentScript())],
        cwd=str(broken),
    )
    with pytest.raises(Exception) as excinfo:
        client.start()
    assert "cwd" in str(excinfo.value), str(excinfo.value)
    assert not client.is_alive
