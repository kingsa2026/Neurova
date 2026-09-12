"""ActionResult 封闭契约（CUA 升级方案 R1-2）

把 OCU 的"诚实降级文案"形式化为机器可读协议：每个 computer/browser 动作
结果可携带一个 action_result 结构，声明 实际投递路径(route)/投递模式
(delivery)/效果确认档位(effect)/证据(evidence)/精确拒绝码(refusal_code)。

不变式（build 构造器强制，越界即抛 ActionResultError）：
- confirmed ⇒ evidence ≥ 1 且无 refusal_code
- refused ⇒ 无 evidence，delivery=not_applicable，refusal_code 必填
- suspected_noop ⇒ 无 evidence（"已投递但无验证手段"的诚实档）
- 词表封闭

参考：trycua/cua `docs/action-result-contract.md`（effect/route/delivery/
evidence/escalation 词汇表），并按 Neurova 双后端扩展 camofox_ref /
playwright_role / remote。
"""

from typing import Any, Dict, List, Optional

ROUTES = frozenset(
    {
        "accessibility",     # AX/UIA 语义动作
        "uia",               # Windows UI Automation 语义（Invoke/Value/...）
        "app_post",          # 消息直投目标窗口（PostMessage，不抢焦点）
        "global_input",      # 全局指针/键盘（会移动真实光标、抢前台）
        "playwright_role",   # Playwright get_by_role 定位交互
        "camofox_ref",       # camofox [eN] ref 定位交互
        "dom",               # DOM 层导航/求值
        "remote",            # 远程会话平面（RS 批次预留）
    }
)
DELIVERIES = frozenset({"background", "foreground", "not_applicable"})
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
    }
)


class ActionResultError(ValueError):
    """action_result 结构违反不变式/词表越界"""


def build(
    route: str,
    effect: str,
    delivery: str = "not_applicable",
    evidence: Optional[List[str]] = None,
    refusal_code: Optional[str] = None,
    escalation: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """构造并校验 action_result（封闭契约的唯一构造入口）"""
    if route not in ROUTES:
        raise ActionResultError(f"route 越界: {route!r}")
    if effect not in EFFECTS:
        raise ActionResultError(f"effect 越界: {effect!r}")
    if delivery not in DELIVERIES:
        raise ActionResultError(f"delivery 越界: {delivery!r}")

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
        result["refusal_code"] = refusal_code
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
    return result


def confirmed(route: str, delivery: str, evidence: List[str]) -> Dict[str, Any]:
    return build(route, "confirmed", delivery=delivery, evidence=evidence)


def refused(
    route: str,
    refusal_code: str,
    escalation: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return build(route, "refused", refusal_code=refusal_code, escalation=escalation)


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
