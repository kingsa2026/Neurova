# -*- coding: utf-8 -*-
"""外部编码代理工具目录：内置预设 + 本机命令探测 + 能力声明（F1）。

- 运行时事实源是名册 ``executor.command``（生效值）；本目录只给默认值、
  能力标注与本机可用探测（设计文档 §4.9）。
- CLI 安装检查发生在「用户启用连接时」（catalog 查询/测试连接的实时
  ``shutil.which`` 探测），部署期不预装不强校验；未命中返回
  ``installed=false`` + ``install_hint``。
- F1 能力声明（升级方案 §3.1）：每家预设显式声明支持面（transports /
  permission_modes / streaming / resume / session_reuse），并提供
  ``capabilitiesFor`` / ``refuseExecutorSpec`` 供「打开前拒绝」双闸共用
  （配置期 422 + 派活期拒绝）；声明是本仓已验证支持面的单一事实源。
"""
import shutil
from typing import Any, Dict, List, Optional

#: 执行体类型取值唯一事实源（名册/管理面/派活同口径，教义第 6 条）。
EXECUTOR_KINDS = ("acp", "plugin")

#: ACP 原生/适配器家能力档（七家同口径）。ssh 是通用命令包装
#: （ssh_transport.resolveSpawnCommand），机制上两家 transport 都支持；
#: 审批链 chain/auto 均可；ACP update 流为流式；无官方续跑口径；
#: 会话内可复用进程/会话。
_ACP_CAPABILITIES = {
    "transports": ("stdio", "ssh"),
    "permission_modes": ("chain", "auto"),
    "streaming": True,
    "resume": False,
    "session_reuse": True,
}

#: plugin 家（zcode）能力档：--resume 有官方口径可续跑；每 prompt 一进程
#: （session_reuse=False）；无运行中审批交互，auto 无意义（只 chain）。
_PLUGIN_CAPABILITIES = {
    "transports": ("stdio", "ssh"),
    "permission_modes": ("chain",),
    "streaming": True,
    "resume": True,
    "session_reuse": False,
}

#: 保守能力档：未知/禁用工具只放行最朴素组合（stdio + chain，
#: 无流式/续跑/会话复用）——fail-closed 的缺省声明。
_CONSERVATIVE_CAPABILITIES = {
    "transports": ("stdio",),
    "permission_modes": ("chain",),
    "streaming": False,
    "resume": False,
    "session_reuse": False,
}

#: kind 级能力档（executor.tool 留空时的判定口径）：acp 取目录 acp 档、
#: plugin 取 zcode 档——直接引用目录声明，不另造第二份口径。
_KIND_PROFILES = {
    "acp": _ACP_CAPABILITIES,
    "plugin": _PLUGIN_CAPABILITIES,
}

#: 内置预设（默认 command 为官方口径，允许名册覆盖）。
CATALOG: Dict[str, Dict[str, Any]] = {
    "opencode": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["opencode", "acp"],
        "origin": "native",
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "https://opencode.ai/docs/",
    },
    "qoder": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["qoder", "--acp"],
        "origin": "native",
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "https://docs.qoder.com/cli/acp",
    },
    "codebuddy": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@tencent-ai/codebuddy-code", "--acp"],
        "origin": "native",
        "requires_node": True,
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "npm i -g @tencent-ai/codebuddy-code",
    },
    "zcode": {
        "kind": "plugin",
        "transport": "stdio",
        "command": [
            "zcode",
            "--output-format", "stream-json",
            "--no-color",
            "--mode", "yolo",
            "--disallowed-tools", "AskUserQuestion,EnterPlanMode,ExitPlanMode",
        ],
        "origin": "headless-cli",
        "capabilities": dict(_PLUGIN_CAPABILITIES),
        "install_hint": "https://zcode.z.ai/cn/docs",
    },
    "gemini-cli": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["gemini", "--acp"],
        "origin": "native",
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "https://github.com/google-gemini/gemini-cli",
    },
    "claude-code": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@agentclientprotocol/claude-agent-acp"],
        "origin": "adapter",
        "requires_node": True,
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "npm i -g @agentclientprotocol/claude-agent-acp",
    },
    "codex": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["npx", "@agentclientprotocol/codex-acp"],
        "origin": "adapter",
        "requires_node": True,
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "npm i -g @agentclientprotocol/codex-acp",
    },
    # 已裁定暂不接入（2026-11-19）：结论留档，不进生效预设；能力照常声明留档。
    "trae": {
        "kind": "acp",
        "transport": "stdio",
        "command": ["traecli", "acp", "serve"],
        "origin": "native",
        "disabled": True,
        "capabilities": dict(_ACP_CAPABILITIES),
        "install_hint": "https://docs.trae.cn/cli_agent-client-protocol",
    },
}


def defaultCommand(tool: str) -> Optional[List[str]]:
    """目录默认启动命令；未知工具/禁用工具返回 None。"""
    entry = CATALOG.get(str(tool or "").strip())
    if entry is None or entry.get("disabled"):
        return None
    return list(entry.get("command") or [])


def _capabilitiesExport(caps: Dict[str, Any]) -> Dict[str, Any]:
    """能力档出口形态：元组转 list（JSON 可序列化），并拷贝防外部改写目录。

    管理面/前端直接消费本形态；目录内声明保持元组（不可变、单源）。
    """
    source = caps or _CONSERVATIVE_CAPABILITIES
    return {
        "transports": list(source.get("transports") or ()),
        "permission_modes": list(source.get("permission_modes") or ()),
        "streaming": bool(source.get("streaming")),
        "resume": bool(source.get("resume")),
        "session_reuse": bool(source.get("session_reuse")),
    }


def capabilitiesFor(tool: str) -> Dict[str, Any]:
    """工具能力声明（F1）：已知且未禁用的工具返回其声明拷贝；
    未知/禁用工具返回保守档（只放行 stdio + chain）。

    序量字段出口为 list（JSON 可序列化）；返回值为独立拷贝，改写不影响目录。
    """
    entry = CATALOG.get(str(tool or "").strip())
    caps = _CONSERVATIVE_CAPABILITIES
    if entry is not None and not entry.get("disabled"):
        caps = entry.get("capabilities") or _CONSERVATIVE_CAPABILITIES
    return _capabilitiesExport(caps)


def refuseExecutorSpec(spec: Dict[str, Any]) -> List[str]:
    """打开前能力校验（F1 双闸共用判据）：返回全部违规原因，空列表=放行。

    校验项：
    - kind ∈ EXECUTOR_KINDS；
    - tool 非空时必须已知、未禁用、且目录 kind 与 spec["kind"] 一致；
    - transport ∈ 该能力档 transports；permission_mode ∈ 该能力档 permission_modes；
    - remote 仅当 transport == "ssh"；
    - tool 为空时按 kind 取能力档（acp→acp 档、plugin→zcode 档）判定。

    多项违规全部并列返回（不短路），供配置期 422 与派活期拒绝共用。
    """
    reasons: List[str] = []
    spec = spec or {}
    kind = str(spec.get("kind") or "").strip().lower()
    tool = str(spec.get("tool") or "").strip()
    transport = str(spec.get("transport") or "stdio").strip().lower()
    permission_mode = str(spec.get("permission_mode") or "chain").strip().lower()
    remote = spec.get("remote")

    if kind not in EXECUTOR_KINDS:
        reasons.append(f"kind 非法: {kind or '(空)'}（支持 {' | '.join(EXECUTOR_KINDS)}）")
        return reasons

    if tool:
        entry = CATALOG.get(tool)
        if entry is None:
            reasons.append(f"未知工具: {tool}（目录未收录）")
        elif entry.get("disabled"):
            reasons.append(f"工具已禁用: {tool}")
        else:
            entry_kind = str(entry.get("kind") or "")
            if entry_kind != kind:
                reasons.append(f"kind 与目录不符: {tool} 为 {entry_kind}，spec 声明 {kind}")
        # 未知/禁用工具按保守档继续判 transport/mode（原因全部并列）
        caps = entry.get("capabilities") if entry is not None and not entry.get("disabled") else _CONSERVATIVE_CAPABILITIES
    else:
        caps = _KIND_PROFILES.get(kind, _CONSERVATIVE_CAPABILITIES)

    transports = caps.get("transports") or ()
    if transport not in transports:
        reasons.append(f"transport 非法: {transport}（支持 {' | '.join(transports)}）")
    modes = caps.get("permission_modes") or ()
    if permission_mode not in modes:
        reasons.append(f"permission_mode 非法: {permission_mode}（支持 {' | '.join(modes)}）")
    if remote is not None and transport != "ssh":
        reasons.append("remote 仅在 transport=ssh 时允许")
    return reasons


def probeTool(tool: str) -> Dict[str, Any]:
    """单工具本机探测：CLI 安装检查在用户启用连接时实时执行。"""
    entry = CATALOG.get(str(tool or "").strip())
    if entry is None:
        return {"tool": tool, "known": False, "installed": False}
    head = (entry.get("command") or [""])[0]
    needs_node = bool(entry.get("requires_node"))
    installed = bool(shutil.which(head)) if head else False
    if needs_node and installed:
        installed = bool(shutil.which("node")) or bool(shutil.which("npx"))
    return {
        "tool": tool,
        "known": True,
        "kind": entry.get("kind"),
        "origin": entry.get("origin"),
        "command": entry.get("command"),
        "requires_node": needs_node,
        "disabled": bool(entry.get("disabled")),
        "installed": installed,
        "install_hint": entry.get("install_hint"),
        # F1：能力声明随探测出口透出（前端下拉可据此预判，测试连接前即可提示）
        "capabilities": _capabilitiesExport(entry.get("capabilities")),
    }


def listCatalog() -> List[Dict[str, Any]]:
    """全量目录（每项附本机探测结果与能力声明），供管理面/前端下拉。"""
    return [probeTool(tool) for tool in CATALOG]
