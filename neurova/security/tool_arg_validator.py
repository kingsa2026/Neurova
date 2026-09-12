"""工具参数执行前校验（工具调用链升级计划 T2，T5 共用 schema 查表与开关单源）。

Needle 对比结论：云端模型不可文法约束解码，等价做法=执行前 jsonschema 校验，
失败拒执行、逐字段错误经 role=tool 通道回传 LLM 自纠（与 loops/base.py
参数解析失败同错误通道）。宽容原则：标量字符串化先归一（LLM 常把数字写成
字符串）；未知键放行（additionalProperties 缺省 true，防误伤多传参的存量工具）。

装配点：ToolExecutor._execute_single_tool param_guard 之后、治理预检之前——
所有执行路径（loop 原生/文本兜底/肌肉记忆自动执行）汇于此单一咽喉点。
NEUROVA_TOOL_ARG_VALIDATION=0 全局关闭（零行为变化）。
"""
import os
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MAX_ERRORS = 8


def validation_enabled() -> bool:
    return os.environ.get("NEUROVA_TOOL_ARG_VALIDATION", "1") != "0"


def get_tool_arg_schema(tool_name: str) -> Optional[Dict[str, Any]]:
    """内置工具 parameters schema（单源 builtin_tools 注册表）；查无返回 None。"""
    try:
        from neurova.builtin_tools import get_builtin_tool_params

        entry = get_builtin_tool_params(tool_name)
    except Exception:  # noqa: BLE001 - 查表失败降级放行，不阻断执行
        return None
    if not isinstance(entry, dict):
        return None
    schema = entry.get("parameters")
    return schema if isinstance(schema, dict) else None


def _coerce(value: Any, typ: Optional[str]) -> Any:
    """宽容标量归一：仅处理字符串→声明类型；失败原样交回校验器报类型错。"""
    if not isinstance(value, str) or not typ:
        return value
    text = value.strip()
    try:
        if typ == "integer":
            return int(text)
        if typ == "number":
            return float(text)
        if typ == "boolean" and text.lower() in ("true", "false"):
            return text.lower() == "true"
    except ValueError:
        return value
    return value


def validate_tool_args(tool_name: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """返回 (归一后参数, 逐字段错误列表)。错误列表非空即应拒绝执行。

    开关关闭时原样透传（校验与开关同契约，消费方无需各自判 env）。
    """
    if not validation_enabled():
        return params, []
    schema = get_tool_arg_schema(tool_name)
    if schema is None:
        return params, []
    props = schema.get("properties") or {}
    out = dict(params or {})
    for key, spec in props.items():
        if key in out and isinstance(spec, dict):
            out[key] = _coerce(out[key], spec.get("type"))
    errors: List[str] = []
    for err in sorted(Draft202012Validator(schema).iter_errors(out), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.path)
        errors.append(f"{path or '(root)'}: {err.message}")
        if len(errors) >= _MAX_ERRORS:
            break
    if errors:
        logger.debug("T2 参数校验拒绝 %s: %s", tool_name, errors)
    return out, errors
