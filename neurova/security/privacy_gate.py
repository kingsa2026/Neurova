"""E2 工具事件隐私门控（docs/Neurova_OpenClaw工具技能专项对比 §5）。

AGENT_TOOL_RESULT 等工具事件会广播到 WS/聊天渠道预览。工具 params 里
常见 password/token/secret/api_key 等敏感键——OC 的做法是 progress 事件
必须显式 visibility:"channel"/privacy:"public" 才进 UI。Neurova 侧采取
等效的出口脱敏：敏感键值脱敏 + 显式 visibility:"private" 的事件整体丢 params。
"""

import re
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|api_key|apikey|authorization|credential", re.I)


def _redact_value(value: Any) -> str:
    s = str(value)
    if len(s) <= 4:
        return "***"
    return s[:2] + "***" + s[-2:]


def _redact_params(params: Any) -> Any:
    """递归脱敏敏感键；非 dict/list 原样返回。"""
    if isinstance(params, dict):
        out = {}
        for k, v in params.items():
            if _SENSITIVE_KEY.search(str(k)):
                out[k] = _redact_value(v)
            else:
                out[k] = _redact_params(v)
        return out
    if isinstance(params, list):
        return [_redact_params(v) for v in params]
    return params


def redact_tool_messages_for_channel(tool_messages: List[Dict]) -> List[Dict]:
    """工具事件出口脱敏（E2）。

    规则：
    - 事件带 visibility:"private" → 丢 params（事件名/状态保留，供 UI 显示）
    - params 中敏感键（password/token/secret/api_key…）值脱敏（保留键名与形状）
    - 其余字段原样透传；非 dict 条目原样返回
    """
    out: List[Dict] = []
    for m in tool_messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        item = dict(m)
        if item.get("visibility") == "private":
            item.pop("params", None)
        elif "params" in item:
            try:
                item["params"] = _redact_params(item["params"])
            except Exception as e:
                logger.debug("params 脱敏失败，整体移除: %s", e)
                item.pop("params", None)
        out.append(item)
    return out
