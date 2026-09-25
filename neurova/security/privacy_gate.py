"""E2 工具事件隐私门控。

AGENT_TOOL_RESULT 等工具事件会广播到 WS/聊天渠道预览。工具 params 里
常见 password/token/secret/api_key 等敏感键——OC 的做法是 progress 事件
必须显式 visibility:"channel"/privacy:"public" 才进 UI。Neurova 侧采取
等效的出口脱敏：载荷键（`TOOL_PAYLOAD_KEYS`）内的敏感键值脱敏 +
显式 visibility:"private" 的事件整体丢掉全部载荷键。
"""

import json
import re
from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|api_key|apikey|authorization|credential", re.I)

#: 工具事件里承载调用参数的键名（**契约本体**，唯一事实源）。
#: 调用侧展示记录同时写 `params`（剥离展示参数后的执行参数）与 `arguments`
#: （模型原样传入的参数串，读侧重建协议消息用）——两者都是"参数载荷"，
#: 出口脱敏必须按同一契约覆盖全部载荷键；曾按单键名硬编码，新增载荷键
#: 即从 channel/SSE 出口泄露敏感值。
TOOL_PAYLOAD_KEYS: Tuple[str, ...] = ("params", "arguments")


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


def _redact_payload(value: Any) -> Tuple[Any, bool]:
    """按载荷自身形态脱敏；返回 (脱敏值, 是否应丢弃该键)。

    形态是契约的一部分，脱敏不改形态：dict/list 就地递归；JSON 串解析后
    仍序列化成串（`arguments` 的消费方按串取用）。解析不开则**丢弃该键**并
    出声 —— 不可定位的载荷不得原样出口（静默放行等于没脱敏）。
    """
    if isinstance(value, str):
        if not value.strip():
            return value, False
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError) as err:
            logger.warning("工具事件参数载荷不是可解析 JSON，已从出口移除: %s", err)
            return None, True
        return json.dumps(_redact_params(parsed), ensure_ascii=False), False
    return _redact_params(value), False


def redact_tool_messages_for_channel(tool_messages: List[Dict]) -> List[Dict]:
    """工具事件出口脱敏（E2）。

    规则：
    - 事件带 visibility:"private" → 丢掉全部载荷键（事件名/状态保留，供 UI 显示）
    - 载荷键（`TOOL_PAYLOAD_KEYS`）中敏感键（password/token/secret/api_key…）
      的值脱敏（保留键名与形状）；解析不开的载荷整体移除
    - 其余字段原样透传；非 dict 条目原样返回
    """
    out: List[Dict] = []
    for m in tool_messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        item = dict(m)
        if item.get("visibility") == "private":
            for key in TOOL_PAYLOAD_KEYS:
                item.pop(key, None)
        else:
            for key in TOOL_PAYLOAD_KEYS:
                if key not in item:
                    continue
                try:
                    redacted, drop = _redact_payload(item[key])
                except Exception as e:  # noqa: BLE001 - 脱敏失败即不派发，不静默放行
                    logger.debug("%s 脱敏失败，整体移除: %s", key, e)
                    drop = True
                if drop:
                    item.pop(key, None)
                else:
                    item[key] = redacted
        out.append(item)
    return out
