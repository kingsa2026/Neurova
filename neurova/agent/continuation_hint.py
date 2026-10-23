# -*- coding: utf-8 -*-
"""截断续写提示与「API 配置类错误」判别——两件与管线状态无关的纯函数。

从 `chat_pipeline` 抽出：热路径文物体积门禁只允许该文件变瘦，而这两处都与管线
状态无关、纯入参出参，天然适合独立成模块。

`isApiConfigError` 决定 `_call_agent_loop` 上抛还是 fallback：供应商错误（限流/认证/
连接/token 超限）必须直接上抛，静默 fallback 到 legacy 会掩盖真实原因（实测缺陷：
限流被转译成无关的 TypeError，用户拿到空回复）；legacy 只供 Loop 自身实现错误兜底。

标签风格 `<system-hint>/<previous-tail>` 是全仓先例（`neurova/context/envelope.py` 沿用同一套）。
"""

#: 中文字符占比阈值：超过它按中文提示，否则按英文提示。
_CJK_RATIO_THRESHOLD = 0.15


def build_continue_hint(user_input: str, reply: str) -> str:
    """按本轮语言构建截断续写提示（中文语境中文、其余英文）。"""
    sample = (user_input or "") + (reply or "")
    cjk = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    is_cjk = cjk > len(sample) * _CJK_RATIO_THRESHOLD if sample else False

    if is_cjk:
        return (
            "<system-hint>上轮回复因长度限制被截断。"
            "请结合下文 <previous-tail> 片段判断："
            "若仍需执行操作则立刻调用工具；"
            "若仅为文本未写完，从截断处直接接续，不要重复已说内容。"
            "</system-hint>"
        )
    return (
        "<system-hint>Previous reply was truncated due to length limit. "
        "Review <previous-tail> below and decide: "
        "if tools are still needed, call them now; "
        "if only text remains, continue from cutoff, do NOT repeat."
        "</system-hint>"
    )


def isApiConfigError(exc: Exception) -> bool:
    """是否属于 API 配置类错误（400/401/403，不应 fallback）。"""
    try:
        from openai import AuthenticationError, BadRequestError

        if isinstance(exc, (BadRequestError, AuthenticationError)):
            return True
    except ImportError:
        pass
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status in (400, 401, 403)
