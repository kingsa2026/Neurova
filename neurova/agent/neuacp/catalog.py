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
import subprocess
from copy import deepcopy
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


# ── C5：provider 切换五结果决策（纯函数，能力数据驱动，无 IO） ─────────────

#: provider 切换决策结果（参照系 ac 借鉴 C5）。
TRANSITION_RESULTS = ("reuse", "switch_model_in_session", "restart_and_resume", "create_with_handoff", "reject")


def _handoffCapable(caps: Dict[str, Any]) -> bool:
    """handoff 工件产出能力（C5 新增维度）：键缺失按 False 保守处理（fail-closed）。"""
    return bool((caps or {}).get("handoff_inject", False))


def decideProviderTransition(current_caps: Dict[str, Any], target_caps: Dict[str, Any], *,
                             same_executor: bool, target_installed: bool = True,
                             model_changed: bool = False) -> str:
    """provider 切换/接续五结果决策（纯函数，能力数据驱动，无 IO）。

    判定顺序：
    1. not target_installed → "reject"
    2. not same_executor → 跨 executor：双方 capabilities 的 handoff 能力均可用
       （_handoffCapable：capabilities.get("handoff_inject", False) 为真——保守缺省 False）
       → "create_with_handoff"，否则 "reject"
    3. model_changed and session_reuse(target) → "switch_model_in_session"
    4. session_reuse(target) → "reuse"
    5. resume(target) → "restart_and_resume"
    6. 兜底 → "reject"（同 executor 但既不能复用也不能续跑，且无 handoff 能力）

    capabilities dict 键缺失按保守值处理（session_reuse/resume/handoff_inject 缺省 False）。
    返回值必须属于 TRANSITION_RESULTS。
    """
    if not target_installed:
        return "reject"
    if not same_executor:
        if _handoffCapable(current_caps) and _handoffCapable(target_caps):
            return "create_with_handoff"
        return "reject"
    target = target_caps or {}
    session_reuse = bool(target.get("session_reuse", False))
    if model_changed and session_reuse:
        return "switch_model_in_session"
    if session_reuse:
        return "reuse"
    if bool(target.get("resume", False)):
        return "restart_and_resume"
    return "reject"


# ── C1：provider 目录健康探测与握手档案 ─────────────────────────────────────

#: 健康探测子进程超时（秒）：只读 ``--version`` 探测，超时即杀，不拖住调用方。
PROBE_TIMEOUT_S = 10.0


def _defaultProbeRun(cmd_list: List[str], timeout_s: float) -> tuple:
    """缺省探测执行：``subprocess.run`` 只读子进程，超时强杀。

    超时（``TimeoutExpired``，run 内部已 kill 子进程）转译为返回码 124
    （与 GNU timeout 口径一致）；命令不可执行（``OSError``）转译为 127。
    探测纪律：绝不 spawn 会话/登录/MCP，只执行调用方给定的只读命令。
    """
    try:
        proc = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=timeout_s
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return 124, stdout, stderr or f"timeout after {timeout_s}s"
    except OSError as exc:
        return 127, "", str(exc)


def probeToolHealth(tool: str, *, timeout_s: float = PROBE_TIMEOUT_S,
                    which_fn=None, run_fn=None) -> Dict[str, Any]:
    """目录工具健康探测（C1）：installed + version，无副作用。

    - which_fn/run_fn 供测试注入（缺省 ``shutil.which`` / ``_defaultProbeRun``）；
      run_fn 约定：``run_fn(cmd_list, timeout_s) -> (returncode, stdout, stderr)``。
    - 探测只读目录既有 command 声明：which 命中 ``command[0]``，再运行
      ``command[0] + ["--version"]``；绝不发送目录 command 的完整参数
      （不触发登录/会话/MCP 启动）。
    - 未知/禁用工具 → ``{"tool", "installed": False, "install_hint",
      "version": None, "error": "unknown_tool"|"disabled"}``；
    - 已知但未安装 → 同形态且 ``error=None``（install_hint 取目录声明）；
    - 已安装 → ``{"installed": True, "version": stdout 首行截 200 字符,
      "error": None}``；运行失败/超时 → ``{"installed": True, "version": None,
      "error": "<原因>"}``（installed 与 version 独立：装了但 version 探测
      失败仍是 installed=True）。
    """
    tool = str(tool or "").strip()
    entry = CATALOG.get(tool)
    if entry is None:
        return {"tool": tool, "installed": False, "install_hint": "",
                "version": None, "error": "unknown_tool"}
    if entry.get("disabled"):
        return {"tool": tool, "installed": False,
                "install_hint": str(entry.get("install_hint") or ""),
                "version": None, "error": "disabled"}
    which_fn = which_fn or shutil.which
    run_fn = run_fn or _defaultProbeRun
    command = list(entry.get("command") or [])
    head = command[0] if command else ""
    install_hint = str(entry.get("install_hint") or "")
    if not head or not which_fn(head):
        return {"tool": tool, "installed": False, "install_hint": install_hint,
                "version": None, "error": None}
    try:
        returncode, stdout, stderr = run_fn([head, "--version"], timeout_s)
    except subprocess.TimeoutExpired:
        return {"tool": tool, "installed": True, "install_hint": install_hint,
                "version": None,
                "error": f"version 探测超时: {timeout_s}s（子进程已终止）"}
    except OSError as exc:
        return {"tool": tool, "installed": True, "install_hint": install_hint,
                "version": None, "error": f"version 探测失败: {exc}"}
    if returncode != 0:
        return {"tool": tool, "installed": True, "install_hint": install_hint,
                "version": None,
                "error": f"version 探测失败: rc={returncode} stderr={str(stderr or '')[:200]}"}
    lines = str(stdout or "").splitlines()
    version = lines[0].strip()[:200] if lines else ""
    if not version:
        return {"tool": tool, "installed": True, "install_hint": install_hint,
                "version": None, "error": "version 探测无输出"}
    return {"tool": tool, "installed": True, "install_hint": install_hint,
            "version": version, "error": None}


#: 三家 P1 预设握手档案（C1，目录声明扩展、单一事实源）：initialize 参数 /
#: 鉴权形态 / 会话方法名。键为 provider 短名，与 CATALOG 的映射：
#: gemini→gemini-cli、claude→claude-code、codex→codex。
#: 确证程度：
#: - protocolVersion "1" 与 session 方法名（session/new、session/prompt）：
#:   本仓 acp_client/acp_executor 现行实现 + ACP 规范通用方法名（确证）；
#: - clientCapabilities：本仓 ACP 客户端现以空能力发起 initialize
#:   （acp_client.start 的 client_capabilities 缺省 {}），故为空表，
#:   真握手卡按各家 agentCapabilities 回填；
#: - auth：各家官方公开口径的主形态（gemini=Google OAuth 登录；
#:   claude=Claude 订阅登录；codex=ChatGPT 订阅登录），属公开文档推断，
#:   api_key 为各家亦有支持的备选形态；不确定处不臆造。
_PRESET_HANDSHAKE_PROFILES: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "initialize": {"protocolVersion": "1", "clientCapabilities": []},
        "auth": "oauth",
        "session": {"new": "session/new", "prompt": "session/prompt"},
    },
    "claude": {
        "initialize": {"protocolVersion": "1", "clientCapabilities": []},
        "auth": "subscription",
        "session": {"new": "session/new", "prompt": "session/prompt"},
    },
    "codex": {
        "initialize": {"protocolVersion": "1", "clientCapabilities": []},
        "auth": "subscription",
        "session": {"new": "session/new", "prompt": "session/prompt"},
    },
}


def presetHandshakeProfiles() -> Dict[str, Dict[str, Any]]:
    """三家 P1 预设的握手档案（目录声明扩展，单一事实源）。

    返回深拷贝：外部改写不影响目录声明。键为 provider 短名
    （gemini/claude/codex ↔ CATALOG 的 gemini-cli/claude-code/codex）。
    """
    return deepcopy(_PRESET_HANDSHAKE_PROFILES)
