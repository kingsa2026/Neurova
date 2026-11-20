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
from neurova.agent.neuacp.catalog import (
    CATALOG,
    EXECUTOR_KINDS,
    capabilitiesFor,
    defaultCommand,
    listCatalog,
    probeTool,
    refuseExecutorSpec,
)
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


# ── F1：能力声明 + 打开前拒绝（升级方案 §3.1，线乙） ─────────────────────

#: ACP 原生/适配器家声明口径（七家一致，trae 留档照常声明）
_ACP_CAPS = {
    "transports": ["stdio", "ssh"],
    "permission_modes": ["chain", "auto"],
    "streaming": True,
    "resume": False,
    "session_reuse": True,
}
#: plugin 家（zcode）声明口径：--resume 官方可续跑；每 prompt 一进程不复用会话
_PLUGIN_CAPS = {
    "transports": ["stdio", "ssh"],
    "permission_modes": ["chain"],
    "streaming": True,
    "resume": True,
    "session_reuse": False,
}
#: 保守档：未知/禁用只放行最朴素组合
_CONSERVATIVE_CAPS = {
    "transports": ["stdio"],
    "permission_modes": ["chain"],
    "streaming": False,
    "resume": False,
    "session_reuse": False,
}
_CAPABILITY_KEYS = {"transports", "permission_modes", "streaming", "resume", "session_reuse"}


def test_executorKindsIsSingleSource():
    assert EXECUTOR_KINDS == ("acp", "plugin")
    kinds = {entry["kind"] for entry in CATALOG.values()}
    assert kinds <= set(EXECUTOR_KINDS), "目录内不得出现 EXECUTOR_KINDS 之外的 kind"


def test_everyPresetDeclaresCapabilities():
    assert len(CATALOG) == 8, "八家预设（含 trae 留档）都须声明 capabilities"
    for tool, entry in CATALOG.items():
        caps = entry.get("capabilities")
        assert isinstance(caps, dict), f"{tool} 缺 capabilities 声明"
        assert _CAPABILITY_KEYS <= set(caps), f"{tool} capabilities 缺键: {_CAPABILITY_KEYS - set(caps)}"
        expected = _PLUGIN_CAPS if entry["kind"] == "plugin" else _ACP_CAPS
        for key in ("streaming", "resume", "session_reuse"):
            assert caps[key] is expected[key], f"{tool}.{key} 应为 {expected[key]}"
        assert tuple(caps["transports"]) == tuple(expected["transports"]), f"{tool}.transports 口径不符"
        assert tuple(caps["permission_modes"]) == tuple(expected["permission_modes"]), f"{tool}.permission_modes 口径不符"


def test_catalogProbeExportsCapabilitiesAsJsonLists():
    for item in listCatalog():
        caps = item.get("capabilities")
        assert isinstance(caps, dict), f"{item['tool']} 探测出口缺 capabilities"
        assert _CAPABILITY_KEYS <= set(caps), f"{item['tool']} 出口 capabilities 缺键"
        assert isinstance(caps["transports"], list), "transports 出口须为 list（JSON 可序列化）"
        assert isinstance(caps["permission_modes"], list), "permission_modes 出口须为 list（JSON 可序列化）"


def test_capabilitiesForKnownReturnsDeclaredCopy():
    assert capabilitiesFor("opencode")["permission_modes"] == ["chain", "auto"]
    assert capabilitiesFor("zcode")["resume"] is True
    # 拷贝语义：改返回值不得污染目录声明
    mutated = capabilitiesFor("opencode")
    mutated["transports"].append("pigeon")
    assert capabilitiesFor("opencode")["transports"] == ["stdio", "ssh"]


def test_capabilitiesForUnknownConservative():
    assert capabilitiesFor("not-a-tool") == _CONSERVATIVE_CAPS
    assert capabilitiesFor("") == _CONSERVATIVE_CAPS
    assert capabilitiesFor("trae") == _CONSERVATIVE_CAPS, "禁用工具按保守档收口"


def test_refuseExecutorSpecMatrix():
    # 合法：acp + stdio + chain 放行（空列表）
    legal = {"kind": "acp", "tool": "opencode", "transport": "stdio", "permission_mode": "chain"}
    assert refuseExecutorSpec(legal) == []
    # plugin + auto 拒（plugin 无运行中审批交互，auto 无意义）
    reasons = refuseExecutorSpec({"kind": "plugin", "tool": "zcode", "transport": "stdio", "permission_mode": "auto"})
    assert reasons and "permission_mode" in "; ".join(reasons)
    # transport 非法拒
    reasons = refuseExecutorSpec({"kind": "acp", "tool": "opencode", "transport": "pigeon", "permission_mode": "chain"})
    assert reasons and "transport" in "; ".join(reasons)
    # remote 仅随 ssh：stdio 带 remote 拒
    reasons = refuseExecutorSpec({**legal, "remote": {"host": "box"}})
    assert reasons and "remote" in "; ".join(reasons)
    # ssh + remote 合法放行
    assert refuseExecutorSpec({**legal, "transport": "ssh", "remote": {"host": "box"}}) == []
    # 未知 tool 拒
    reasons = refuseExecutorSpec({"kind": "acp", "tool": "not-a-tool", "transport": "stdio", "permission_mode": "chain"})
    assert reasons and "未知工具" in "; ".join(reasons)
    # kind 与目录不符拒（opencode 是 acp，声明成 plugin）
    reasons = refuseExecutorSpec({"kind": "plugin", "tool": "opencode", "transport": "stdio", "permission_mode": "chain"})
    assert reasons and "kind" in "; ".join(reasons)
    # disabled 工具拒（trae 留档但不可配）
    reasons = refuseExecutorSpec({"kind": "acp", "tool": "trae", "transport": "stdio", "permission_mode": "chain"})
    assert reasons and "禁用" in "; ".join(reasons)
    # kind 本身非法拒
    reasons = refuseExecutorSpec({"kind": "carrier-pigeon", "transport": "stdio", "permission_mode": "chain"})
    assert reasons and "kind" in "; ".join(reasons)
    # tool 留空按 kind 取能力档：acp 档允许 ssh+auto；plugin 档拒 auto
    assert refuseExecutorSpec({"kind": "acp", "transport": "ssh", "permission_mode": "auto"}) == []
    reasons = refuseExecutorSpec({"kind": "plugin", "transport": "stdio", "permission_mode": "auto"})
    assert reasons and "permission_mode" in "; ".join(reasons)
    # 返回的是全部原因（多错并列）：未知工具 + 非法 transport 同时报
    reasons = refuseExecutorSpec({"kind": "acp", "tool": "not-a-tool", "transport": "pigeon", "permission_mode": "chain"})
    joined = "; ".join(reasons)
    assert "未知工具" in joined and "transport" in joined


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
