"""ActionResult 封闭契约

每个 computer/browser 动作
结果可携带一个 action_result 结构，声明 实际投递路径(route)/投递模式
(delivery)/效果确认档位(effect)/证据(evidence)/精确拒绝码(refusal_code)。

不变式（build 构造器强制，越界即抛 ActionResultError）：
- confirmed ⇒ evidence ≥ 1 且无 refusal_code
- refused ⇒ 无 evidence，delivery=not_applicable，refusal_code 必填
- suspected_noop ⇒ 无 evidence（"已投递但无验证手段"的诚实档）
- 词表封闭

参考
evidence/escalation 词汇表），并按 Neurova 双后端扩展 camofox_ref /
playwright_role / remote。
"""

from typing import Any, Dict, List, Optional

ROUTES = frozenset(
    {
        "accessibility",     # AX/UIA 语义动作（macOS AXUIElement PerformAction）
        "uia",               # Windows UI Automation 语义（Invoke/Value/...）
        "app_post",          # 消息直投目标窗口（PostMessage，不抢焦点）
        "global_input",      # 全局指针/键盘（会移动真实光标、抢前台）
        "atspi",             # Linux AT-SPI2 doAction（UIA 的 Linux 等价物，不动光标）
        "xdotool",           # X11 定窗合成事件投递（Wayland 下不可用）
        "shell",             # CLI 命令通道（不经任何输入设备，天然无抢占）
        "playwright_role",   # Playwright get_by_role 定位交互
        "playwright_ref",    # Playwright 快照 [eN] ref 定位交互（click_ref/fill_ref）
        "camofox_ref",       # camofox [eN] ref 定位交互
        "dom",               # DOM 层导航/求值
        "remote",            # 远程会话平面（隔离虚拟屏，RS 批次）
        "device",            # 设备桥（用户手机执行端，经移动 WS 派发）
    }
)
# background=用户桌面后台投递；foreground=夺真实输入设备；
# isolated_plane=隔离平面内执行（用户桌面纹丝不动，画面源是虚拟平面）；
# not_applicable=未投递（refused）或该动作根本不涉及投递平面（如 shell）。
DELIVERIES = frozenset(
    {"background", "foreground", "isolated_plane", "not_applicable"}
)
EFFECTS = frozenset({"confirmed", "partial", "unverifiable", "suspected_noop", "refused"})
EVIDENCE_KINDS = frozenset(
    {
        "value_readback",    # 读回状态值验证（如 UIA Value/开关态）
        "window_change",     # 窗口/控件状态变化验证
        "locator_ack",       # 定位器等待并确认交付（Playwright actionability 等）
        "delivery_ack",      # 后端返回的投递确认（如 camofox click 200）
        "screenshot_diff",   # 动作前后截图差异（预留）
    }
)
REFUSAL_CODES = frozenset(
    {
        "stale_generation",        # 快照事实过期（页面/窗口已变化）
        "ref_not_found",           # 快照中找不到 (role, name) 对应元素
        "ambiguous_ref",           # 匹配到多个候选，拒绝猜测
        "background_unavailable",  # 该动作在后台路径不可投递
        "background_occluded",     # 目标窗口被遮挡，后台路径不可达
        "permission_required",     # 权限门控拒绝（如全局输入未开）
        "unsupported_method",      # 平台/后端不支持该投递方式
        "not_initialized",         # 后端未初始化
        "element_not_clickable",   # 元素无可投递交互/无可点击区域
        "missing_params",          # 必要参数缺失
        "backend_error",           # 后端执行错误（兜底）
        "sandbox_session_required",  # 运行档要求隔离会话但当前无活动会话
        "stale_frame",             # 坐标所属观测帧已过期（画面已变化），须重新观察
        "controller_busy",         # 另一会话正持有前台输入，拒绝并发操控
        "device_offline",          # 设备桥：无在线设备可派发（重连/唤醒后可重试）
        "device_timeout",          # 设备桥：命令在窗口内未回执（可安全重试）
        "device_bridge_disabled",  # 设备桥总闸未开（NEUROVA_DEVICE_BRIDGE_ENABLED）
        "device_budget_exhausted",  # 设备桥：会话步数/时长熔断触顶（重试无意义）
    }
)

# 重试建议三值（P1-2，CUA 错误契约的 retry 语义）：
# - reobserve：画面/事实可能已变，先重新观察再行动（非幂等动作禁止凭旧事实重放）
# - retry：同一调用可安全重试（瞬时故障/后端未就绪）
# - never：重试无意义或危险（权限拒绝/参数非法/互斥占用），模型应停止或换路径
RETRY_MODES = frozenset({"reobserve", "retry", "never"})

#: 每个拒绝码的重试建议（新增拒绝码必须同步登记，守卫见
#: tests/unit/computer_use/test_action_result_retry_contract.py）
REFUSAL_RETRY_ADVICE = {
    "stale_generation": "reobserve",
    "ref_not_found": "reobserve",
    "ambiguous_ref": "reobserve",
    "background_unavailable": "reobserve",
    "background_occluded": "reobserve",
    "element_not_clickable": "reobserve",
    "stale_frame": "reobserve",
    "permission_required": "never",
    "unsupported_method": "never",
    "missing_params": "never",
    "sandbox_session_required": "never",
    "controller_busy": "never",
    "not_initialized": "retry",
    "backend_error": "retry",
    "device_offline": "retry",
    "device_timeout": "retry",
    "device_bridge_disabled": "never",
    "device_budget_exhausted": "never",
}


def retry_advice_for(refusal_code: str) -> str:
    """拒绝码 → 重试建议（未知码回保守的 retry；词表封闭由守卫测试保证）。"""
    return REFUSAL_RETRY_ADVICE.get(refusal_code, "retry")


class ActionResultError(ValueError):
    """action_result 结构违反不变式/词表越界"""


def build(
    route: str,
    effect: str,
    delivery: str = "not_applicable",
    evidence: Optional[List[str]] = None,
    refusal_code: Optional[str] = None,
    escalation: Optional[Dict[str, str]] = None,
    action_sent: Optional[bool] = None,
    retry: Optional[str] = None,
) -> Dict[str, Any]:
    """构造并校验 action_result（封闭契约的唯一构造入口）。

    action_sent：动作是否（可能）已下发——refused 恒 False 且禁止声明 True
    （与 delivery=not_applicable 同一条"未投递"不变式）；其余档缺省 True
    （已尝试投递）。retry：重试建议三值，refused 缺省按拒绝码从
    REFUSAL_RETRY_ADVICE 推导，显式传参可覆盖。
    """
    if route not in ROUTES:
        raise ActionResultError(f"route 越界: {route!r}")
    if effect not in EFFECTS:
        raise ActionResultError(f"effect 越界: {effect!r}")
    if delivery not in DELIVERIES:
        raise ActionResultError(f"delivery 越界: {delivery!r}")
    if retry is not None and retry not in RETRY_MODES:
        raise ActionResultError(f"retry 越界: {retry!r}（允许 {sorted(RETRY_MODES)}）")

    result: Dict[str, Any] = {"route": route, "effect": effect, "delivery": delivery}
    if effect == "refused":
        if evidence:
            raise ActionResultError("refused 不得携带 evidence")
        if delivery != "not_applicable":
            raise ActionResultError("refused 不得声明 delivery（未投递）")
        if not refusal_code:
            raise ActionResultError("refused 必须携带 refusal_code")
        if refusal_code not in REFUSAL_CODES:
            raise ActionResultError(f"refusal_code 越界: {refusal_code!r}")
        if action_sent is True:
            raise ActionResultError("refused 不得声明 action_sent=True（未投递）")
        result["refusal_code"] = refusal_code
        result["action_sent"] = False
        result["retry"] = retry or retry_advice_for(refusal_code)
        if escalation is not None:
            result["escalation"] = escalation
        return result

    if refusal_code:
        raise ActionResultError(f"effect={effect} 不得携带 refusal_code")
    if effect == "confirmed":
        if not evidence:
            raise ActionResultError("confirmed 必须携带 ≥1 条 evidence")
    elif effect == "suspected_noop" and evidence:
        raise ActionResultError("suspected_noop 不得携带 evidence（无验证手段）")
    if evidence:
        for kind in evidence:
            if kind not in EVIDENCE_KINDS:
                raise ActionResultError(f"evidence 词越界: {kind!r}")
        result["evidence"] = list(evidence)
    if escalation is not None:
        result["escalation"] = escalation
    result["action_sent"] = True if action_sent is None else bool(action_sent)
    if retry is not None:
        result["retry"] = retry
    return result


def confirmed(route: str, delivery: str, evidence: List[str]) -> Dict[str, Any]:
    return build(route, "confirmed", delivery=delivery, evidence=evidence)


def refused(
    route: str,
    refusal_code: str,
    escalation: Optional[Dict[str, str]] = None,
    retry: Optional[str] = None,
) -> Dict[str, Any]:
    return build(
        route, "refused", refusal_code=refusal_code, escalation=escalation, retry=retry
    )


def unverifiable(route: str, delivery: str) -> Dict[str, Any]:
    return build(route, "unverifiable", delivery=delivery)


def suspected_noop(route: str, delivery: str) -> Dict[str, Any]:
    return build(route, "suspected_noop", delivery=delivery)


def attach(result: Dict[str, Any], action_result: Dict[str, Any]) -> Dict[str, Any]:
    """把 action_result 挂到工具结果 dict 上（新增字段，旧消费方不受影响）"""
    result["action_result"] = action_result
    return result


def derive_from_browser_result(normalized: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 BrowserResult 归一化 dict 推导 action_result。

    - 成功且携带 route（后端自报）→ confirmed + locator_ack
    - 成功但 route 未知（历史路径）→ None（不编造）
    - 失败 → 按错误文本分类精确拒绝码（route 未知时不编造 → None）
    """
    route = normalized.get("route") if isinstance(normalized, dict) else None
    if route not in ROUTES:
        return None
    if normalized.get("success"):
        return confirmed(route, "background", ["locator_ack"])

    error = str(normalized.get("error") or "")
    if "generation" in error and ("过期" in error or "不一致" in error):
        return refused(route, "stale_generation")
    if "未找到" in error or "not found" in error.lower():
        return refused(route, "ref_not_found")
    if "not initialized" in error.lower():
        return refused(route, "not_initialized")
    if "does not support" in error.lower():
        return refused(route, "unsupported_method")
    return refused(route, "backend_error")
