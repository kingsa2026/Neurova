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

#: 记录里承载"调用参数"的键。`arguments` 是协议原文形态（provider 回传串），
#: `params` 是解析后的结构 —— 两者是同一份事实的两种形态，出口门控必须一起认，
#: 只脱一个等于让同一密钥在出口处出现两个结论。
_PARAM_FIELDS = ("params", "arguments")


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
    - 事件带 visibility:"private" → 丢掉全部参数字段（事件名/状态保留，供 UI 显示）
    - 参数字段中敏感键（password/token/secret/api_key…）值脱敏（保留键名与形状）
    - 其余字段原样透传；非 dict 条目原样返回

    "参数字段"是集合而非单个键名（见 `_PARAM_FIELDS`）：`params` 与 `arguments`
    是同一份调用参数的两种形态，只脱一个会让同一密钥在出口处得到两个结论。
    """
    out: List[Dict] = []
    for m in tool_messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        item = dict(m)
        for field in _PARAM_FIELDS:
            if field not in item:
                continue
            if item.get("visibility") == "private":
                item.pop(field, None)
                continue
            raw = item[field]
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    redacted = _redact_params(parsed)
                    # 没有敏感键时保留原文逐字形态，不做无谓的重新序列化
                    if redacted != parsed:
                        item[field] = json.dumps(redacted, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    # 解不开原文 = 判不出里面有没有敏感值，只能整体移除（不放行原文）
                    logger.debug("%s 原文脱敏失败，整体移除: %s", field, e)
                    item.pop(field, None)
            else:
                item[field] = _redact_params(raw)
        out.append(item)
    return out
