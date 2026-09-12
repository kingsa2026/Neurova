"""参数落地校验（工具调用链升级计划 T5，Needle ungrounded-grounding 移植）。

契约：schema 标了 format=date/date-time 的 string 参数，其年份必须出现在
"本轮可见文本"（ContextVar，由 chat_pipeline._step_llm_call 每轮 set，含
system 时间事实）中，否则判模型臆造、拒执行回传 ungrounded。
纯字面年份比对不做语义猜测，误伤面为零；无标记参数天然豁免。

默认关：NEUROVA_ARG_GROUNDING=1 显式开启。生效开关=schema format 标记
（当前内置工具面无日历日期参数，机制 inert-but-ready，未来工具标记即生效）。
"""
import contextvars
import os
import re
from typing import Any, Dict, List

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_source: contextvars.ContextVar[str] = contextvars.ContextVar("arg_grounding_source", default="")


def set_conversation_source(text: str) -> None:
    _source.set(text or "")


def get_conversation_source() -> str:
    return _source.get()


def grounding_enabled() -> bool:
    return os.environ.get("NEUROVA_ARG_GROUNDING") == "1"


def find_ungrounded_date_fields(schema: Dict[str, Any], arguments: Dict[str, Any],
                                source_text: str) -> List[str]:
    """返回臆造日期字段的错误描述列表（空=放行）。"""
    props = (schema or {}).get("properties") or {}
    years = set(_YEAR_RE.findall(source_text or ""))
    out: List[str] = []
    for key, spec in props.items():
        if not isinstance(spec, dict) or spec.get("format") not in ("date", "date-time"):
            continue
        value = (arguments or {}).get(key)
        if not isinstance(value, str) or len(value) < 4:
            continue
        year = value[:4]
        if not re.fullmatch(r"(?:19|20)\d{2}", year):
            continue
        if year not in years:
            out.append(f"{key}: 值 {value} 的年份 {year} 在可见文本中无字面依据")
    return out
