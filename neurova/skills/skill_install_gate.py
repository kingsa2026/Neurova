"""
技能安装安全门（P1-6）

语义：任何技能在落盘安装前必须过 SkillScanner 扫描；扫描结果含
critical（或 DENY 策略下的 high）即拒绝；扫描器自身故障 **fail-closed**
（拒绝安装而非静默放行）——安全的默认值永远比可用性优先。

消费方：agent_skill_manager.acquire/安装路径（市场技能落盘前）。
返回 dict（不走异常）便于调用方直接并入安装结果信封：
    {"passed": bool, "blocked": bool, "action": "allow"|"deny",
     "findings": [...], "error": str|None}
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 模块级共享扫描器（白名单/自定义规则跨安装保持）；异常时懒重建
_scanner: Optional[Any] = None


def _get_scanner():
    """懒加载共享 SkillScanner（DENY 策略——安装是信任边界）。"""
    global _scanner
    if _scanner is None:
        from neurova.security.skill_scanner import ScanPolicy, SkillScanner

        _scanner = SkillScanner(workspace_path=".")
        _scanner.policy = ScanPolicy.DENY
    return _scanner


def reset_install_gate_scanner() -> None:
    """重置共享扫描器（测试隔离 / 白名单热更后重建）。"""
    global _scanner
    _scanner = None


def validate_permissions_for_install(permissions_raw: Any) -> Dict[str, Any]:
    """manifest.permissions 声明校验（P0-4 安装时声明面）。

    语义：permissions 声明在安装时验证合法性——未知能力键、tools.allow
    非列表、白名单含未知工具、mcp.* 白名单未声明网络能力均拒绝；
    permissions 缺省（None/空）放行（存量技能向后兼容，运行时模型级
    fail-closed 兜底）。

    Returns:
        {"blocked": bool, "errors": [...]}（与扫描门同风格的 dict 信封）
    """
    errors: list = []

    if permissions_raw is None or (isinstance(permissions_raw, dict) and not permissions_raw):
        return {"blocked": False, "errors": []}

    if not isinstance(permissions_raw, dict):
        return {"blocked": True, "errors": [f"permissions 必须是 dict，实际 {type(permissions_raw).__name__}"]}

    from neurova.skills.permissions import (
        KNOWN_CAPABILITY_KEYS,
        tool_category,
        tools_for_categories,
    )

    for key in permissions_raw:
        if key not in KNOWN_CAPABILITY_KEYS:
            errors.append(f"未知权限能力键: {key!r}（有效: {sorted(KNOWN_CAPABILITY_KEYS)}）")

    tools_raw = permissions_raw.get("tools")
    allow: list = []
    if tools_raw is not None:
        if isinstance(tools_raw, dict):
            allow = tools_raw.get("allow") if isinstance(tools_raw.get("allow"), list) else None
            if tools_raw.get("enabled") and allow is None:
                errors.append("tools.allow 必须是工具名列表")
        elif isinstance(tools_raw, (list, tuple)):
            allow = list(tools_raw)
        else:
            errors.append(f"tools 必须是 dict/列表，实际 {type(tools_raw).__name__}")

    if allow is not None:
        # 已知工具全集：分类注册表 + 内置注册表动态键（单一事实源）
        known = tools_for_categories(
            "network", "file", "system", "model", "node"
        )
        try:
            from neurova.builtin_tools import get_builtin_tool_params

            # 注册表探针：知名工具逐个验证（注册表无直接列表 API）
            builtin_known = {
                name
                for name in (
                    "recall_history", "memory_search", "file_read", "file_write",
                    "file_create", "file_delete", "file_edit", "file_list",
                    "file_search", "computer_screenshot", "computer_click",
                    "computer_type", "computer_scroll", "computer_shell",
                    "browser_navigate", "browser_click", "browser_type",
                    "browser_screenshot", "browser_extract_text", "browser_dom_snapshot",
                    "browser_click_role", "browser_fill_role", "youtube_transcript",
                    "browser_read", "bilibili_search", "rss_read", "social_search",
                    "planning", "emotion_analyze", "asr_transcribe", "tts_synthesize",
                    "voice_memory_search", "weather", "web_search", "spawn_subagent",
                    "subagent_status", "list_agents", "create_skill", "web_fetch",
                    "run_code",
                )
                if get_builtin_tool_params(name) is not None
            }
            known |= builtin_known
        except Exception:
            pass

        network_declared = bool(permissions_raw.get("network"))

        for tool in allow:
            if not isinstance(tool, str) or not tool.strip():
                errors.append(f"tools.allow 含非法工具名: {tool!r}")
                continue
            if tool in known:
                continue
            if tool.startswith("mcp."):
                # MCP 白名单必须有网络能力声明配套（声明一致性）
                if not network_declared:
                    errors.append(f"白名单放行 MCP 工具 {tool!r} 但未声明 network 能力")
                continue
            errors.append(f"tools.allow 含未知工具: {tool!r}")

    if errors:
        return {"blocked": True, "errors": errors}
    return {"blocked": False, "errors": []}


def scan_skill_for_install(skill_id: str, skill_path: str) -> Dict[str, Any]:
    """安装前扫描门。

    Args:
        skill_id: 技能标识（白名单键）
        skill_path: 技能落盘目录（含 SKILL.md / 脚本）

    Returns:
        dict: passed/blocked/action/findings/error
    """
    try:
        scanner = _get_scanner()
        from neurova.security.skill_scanner import ScanMode

        result = scanner.scan_skill(skill_id, skill_path, mode=ScanMode.QUICK)
    except Exception as e:
        # fail-closed：扫描器故障 ≠ 放行
        logger.error("技能安装扫描器异常 %s（fail-closed 拒绝）: %s", skill_id, e)
        return {
            "passed": False,
            "blocked": True,
            "action": "deny",
            "findings": [],
            "error": f"扫描器异常（fail-closed）: {e}",
        }

    findings = [f.to_dict() for f in result.findings]
    if not result.passed:
        blocked_by = [f.get("rule_id") for f in findings]
        logger.warning(
            "技能 %s 安装被安全门拦截: %s", skill_id, blocked_by
        )
        return {
            "passed": False,
            "blocked": True,
            "action": "deny",
            "findings": findings,
            "error": "安全扫描未通过: " + "; ".join(
                f.get("message", f.get("rule_id", "")) for f in findings[:5]
            ),
        }

    return {"passed": True, "blocked": False, "action": "allow", "findings": findings, "error": None}


def scan_text_for_injection(text: str, source: str = "") -> Dict[str, Any]:
    """轻量文本注入扫描（NL 合成产物等非落盘内容的快速门）。

    只跑 PromptInjectionAnalyzer（critical 级注入签名），不做全量扫描。
    Returns:
        {"blocked": bool, "findings": [...]}
    """
    try:
        from neurova.security.skill_scanner import (
            PromptInjectionAnalyzer,
            SkillFile,
        )

        analyzer = PromptInjectionAnalyzer()
        findings = analyzer.analyze(SkillFile(path=source, content=text, file_type="txt"))
        return {
            "blocked": any(f.severity == "critical" for f in findings),
            "findings": [f.to_dict() for f in findings],
        }
    except Exception as e:
        # fail-closed：注入扫描不可用时视为可疑
        logger.error("文本注入扫描异常 %s（fail-closed 拦截）: %s", source, e)
        return {
            "blocked": True,
            "findings": [{"rule_id": "scanner_error", "severity": "critical", "message": str(e)}],
        }
