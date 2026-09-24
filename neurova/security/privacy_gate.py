"""E2 工具事件隐私门控。

AGENT_TOOL_RESULT 等工具事件会广播到 WS/聊天渠道预览。工具 params 里
常见 password/token/secret/api_key 等敏感键——OC 的做法是 progress 事件
必须显式 visibility:"channel"/privacy:"public" 才进 UI。Neurova 侧采取
等效的出口脱敏：敏感键值脱敏 + 显式 visibility:"private" 的事件整体丢 params。
"""

import json
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


def _redact_arguments(raw: Any) -> Any:
    """调用原文 → 脱敏后的原文；解析不出（非 JSON 串）返回 None 表示"整体移除"。

    返回 None 是"宁丢不泄"：读不懂的原文无法逐键脱敏，放它出去等于把不确定
    内容当安全内容。
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    return _redact_params(raw)


def redact_tool_messages_for_channel(tool_messages: List[Dict]) -> List[Dict]:
    """工具事件出口脱敏（E2）。

    规则：
    - 事件带 visibility:"private" → 丢 params 与调用原文（事件名/状态保留，供 UI 显示）
    - params 中敏感键（password/token/secret/api_key…）值脱敏（保留键名与形状）
    - arguments（T-10a 新增的协议原文形态）与 params 同受脱敏：同一份调用参数
      的两个出口形态，只脱一个等于给敏感值留旁路
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
            item.pop("arguments", None)
        elif "params" in item or "arguments" in item:
            try:
                if "params" in item:
                    item["params"] = _redact_params(item["params"])
                if "arguments" in item:
                    # 脱敏后再序列化回原文形态；读不懂就整体移除（宁丢不泄）
                    safe = _redact_arguments(item["arguments"])
                    if safe is None:
                        item.pop("arguments", None)
                    else:
                        item["arguments"] = json.dumps(safe, ensure_ascii=False)
            except Exception as e:
                logger.debug("工具调用参数脱敏失败，整体移除: %s", e)
                item.pop("params", None)
                item.pop("arguments", None)
        out.append(item)
    return out
