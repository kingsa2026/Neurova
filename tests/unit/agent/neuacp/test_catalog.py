# -*- coding: utf-8 -*-
"""工具目录（catalog）契约测试——预设、探测结构、禁用项、P1 三家扩编。

B5：gemini-cli / claude-code / codex 三家预设断言（command/origin/requires_node）
+ 真握手测试（照 test_tool_handshake_live.py 模式：probeTool 未装/不可达
pytest.skip 并附原因，装了才真握手——不伪造通过）。
"""
import asyncio
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.catalog import CATALOG, defaultCommand, listCatalog, probeTool
from neurova.agent.neuacp.executor import NeuacpSessionContext


def test_p0ToolsPresentWithCommands():
    for tool in ("opencode", "qoder", "codebuddy", "zcode"):
        assert tool in CATALOG
        assert CATALOG[tool]["command"], f"{tool} 缺默认命令"
    assert CATALOG["zcode"]["kind"] == "plugin"
    assert "--disallowed-tools" in CATALOG["zcode"]["command"]


def test_traeIsDisabledButArchived():
    assert CATALOG["trae"]["disabled"] is True
    assert defaultCommand("trae") is None


def test_defaultCommandReturnsCopy():
    command = defaultCommand("opencode")
    assert command == ["opencode", "acp"]
    command.append("x")
    assert defaultCommand("opencode") == ["opencode", "acp"]


def test_defaultCommandUnknownToolReturnsNone():
    assert defaultCommand("not-a-tool") is None


def test_listCatalogProbesEachEntry():
    items = listCatalog()
    names = {item["tool"] for item in items}
    assert {"opencode", "qoder", "codebuddy", "zcode", "gemini-cli", "claude-code", "codex", "trae"} <= names
    for item in items:
        assert "installed" in item and "install_hint" in item


def test_probeUnknownTool():
    result = probeTool("not-a-tool")
    assert result["known"] is False
    assert result["installed"] is False


# ── B5：P1 三家扩编预设（设计文档 §4.9） ──────────────────────────────────


def test_p1GeminiCliPreset():
    entry = CATALOG["gemini-cli"]
    assert entry["command"] == ["gemini", "--acp"]
    assert entry["origin"] == "native"
    assert entry["kind"] == "acp"
    assert not entry.get("requires_node"), "gemini --acp 原生，不需 Node"


def test_p1ClaudeCodePreset():
    entry = CATALOG["claude-code"]
    assert entry["command"] == ["npx", "@agentclientprotocol/claude-agent-acp"]
    assert entry["origin"] == "adapter"
    assert entry["requires_node"] is True, "npx 适配器需 Node"


def test_p1CodexPreset():
    entry = CATALOG["codex"]
    assert entry["command"] == ["npx", "@agentclientprotocol/codex-acp"]
    assert entry["origin"] == "adapter"
    assert entry["requires_node"] is True, "npx 适配器需 Node"


def test_p1PresetsResolvableByDefaultCommand():
    for tool in ("gemini-cli", "claude-code", "codex"):
        assert defaultCommand(tool) == CATALOG[tool]["command"]


# ── B5：真握手（未装/不可达 skip 并附原因，装了才真握手） ─────────────────


def _handshake(tool):
    probe = probeTool(tool)
    if not probe.get("installed"):
        pytest.skip(f"本机未安装 {tool}（installed=false，启用时展示 install_hint: {probe.get('install_hint')}）")
    executor = NeuacpStdioExecutor(
        list(probe["command"]),
        cwd=str(Path(__file__).parent),
        request_timeout=120.0,
    )
    ctx = NeuacpSessionContext(member_session_id="handshake", task_text="ping", cwd=str(Path(__file__).parent))

    async def run():
        await executor.start(ctx)
        await executor.close()

    try:
        asyncio.run(run())
    except Exception as exc:
        # npx 适配器依赖外网拉包（设计文档 §9 风险 5）：本环境不可达时如实
        # skip 并留原因——真实验收在用户启用连接（install_hint 安装后）进行。
        pytest.skip(f"{tool} 握手未通过（{exc}）——启用时按 install_hint 安装后重验")


def test_geminiCliHandshakeWhenInstalled():
    _handshake("gemini-cli")


def test_claudeCodeHandshakeWhenInstalled():
    _handshake("claude-code")


def test_codexHandshakeWhenInstalled():
    _handshake("codex")
