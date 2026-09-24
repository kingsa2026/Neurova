"""原生协议工具载荷转换（Issue #177）。

原生 Anthropic / Gemini 通路此前**没有 tools 形参**：请求侧静默丢弃，
响应侧把 `tool_use` / `functionCall` 块一并丢掉 —— 配了原生 provider，
函数调用能力直接消失，没有日志、没有报错、没有降级提示。运维侧看到的
表象是「模型就是没用工具」，是最难归因的一类故障。

本模块是这条通路请求侧的唯一转换点，响应侧归一见
`protocol_thinking.toOpenAIToolCalls`（同一契约、同一转换器）。

转换本身复用 `tool_layers/openai_schema.py` 的 `ToolSchemaConverter` ——
本仓既有的 OpenAI↔Anthropic↔Google 归一器，不另写第二份解包逻辑。

`tool_choice` 的取值按各协议自身的语义映射：
  OpenAI `auto`     → Anthropic `{"type": "auto"}` / Gemini `AUTO`
  OpenAI `required` → Anthropic `{"type": "any"}`  / Gemini `ANY`
  OpenAI `none`     → Anthropic `{"type": "none"}` / Gemini `NONE`
未识别取值不猜，一律按 `auto` 处理（fail-safe，与 `map_reasoning_effort`
对未知档位的处理同一纪律）。
"""
from __future__ import annotations

import typing

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "toAnthropicTools",
    "toAnthropicToolChoice",
    "toGeminiTools",
    "toGeminiToolChoice",
]

_ANTHROPIC_TOOL_CHOICE = {"auto": "auto", "required": "any", "none": "none"}
_GEMINI_TOOL_CHOICE = {"auto": "AUTO", "required": "ANY", "none": "NONE"}


def _asOpenAIFunction(tool: dict) -> typing.Optional[dict]:
    """把一条工具定义归一到 (name, description, parameters)。

    **形态判别在此收口**：调用方可能已按目标协议转好（`AnthropicLoop`
    自带的 `_convert_tools_to_anthropic` 就是这么做的），也可能给的是
    OpenAI 形态。判别一次、两条路都归到同一中间形态，避免同一份 tools
    被转两次而互相清空（这是本片 live 自证里实测到的形态）。
    """
    tool = tool or {}
    if isinstance(tool.get("function"), dict):  # OpenAI 形态
        func = tool["function"]
        name = str(func.get("name") or "")
        parameters = func.get("parameters") or {"type": "object", "properties": {}}
        description = str(func.get("description") or "")
    elif tool.get("input_schema") is not None:  # 已是 Anthropic 形态
        name = str(tool.get("name") or "")
        parameters = tool.get("input_schema") or {"type": "object", "properties": {}}
        description = str(tool.get("description") or "")
    elif tool.get("parameters") is not None:  # 已是 Google 形态
        name = str(tool.get("name") or "")
        parameters = tool.get("parameters") or {"type": "object", "properties": {}}
        description = str(tool.get("description") or "")
    else:  # 裸 {name, description, parameters} 或无参工具
        name = str(tool.get("name") or "")
        parameters = {"type": "object", "properties": {}}
        description = str(tool.get("description") or "")
    if not name:
        return None
    return {"name": name, "description": description, "parameters": parameters}


def toAnthropicTools(tools: typing.Optional[typing.List[dict]]) -> typing.List[dict]:
    """tools（OpenAI / Anthropic / Google 任一形态）→ Anthropic `tools`。

    转换经 `tool_layers/openai_schema.py` 的既有归一器完成；入参形态先经
    `_asOpenAIFunction` 收口，故对已转换过的输入是幂等的。
    """
    from neurova.tool_layers.openai_schema import OpenAIFunctionSchema, ToolSchemaConverter

    converter = ToolSchemaConverter()
    out: typing.List[dict] = []
    for tool in tools or []:
        normalized = _asOpenAIFunction(tool)
        if normalized is None:
            continue
        schema = OpenAIFunctionSchema(
            name=normalized["name"],
            description=normalized["description"],
            parameters=normalized["parameters"],
        )
        out.append(converter.openai_to_anthropic(schema).to_anthropic_format())
    return out


def toAnthropicToolChoice(tool_choice: typing.Optional[str]) -> typing.Optional[dict]:
    """OpenAI `tool_choice` → Anthropic `tool_choice`；未识别取值按 `auto`。"""
    if not tool_choice:
        return None
    key = str(tool_choice).strip().lower()
    return {"type": _ANTHROPIC_TOOL_CHOICE.get(key, "auto")}


def toGeminiTools(tools: typing.Optional[typing.List[dict]]) -> typing.List[dict]:
    """OpenAI 形态 tools → Gemini `tools[].functionDeclarations[]`。"""
    from neurova.tool_layers.openai_schema import OpenAIFunctionSchema, ToolSchemaConverter

    converter = ToolSchemaConverter()
    declarations: typing.List[dict] = []
    for tool in tools or []:
        normalized = _asOpenAIFunction(tool)
        if normalized is None:
            continue
        schema = OpenAIFunctionSchema(
            name=normalized["name"],
            description=normalized["description"],
            parameters=normalized["parameters"],
        )
        declarations.append(converter.openai_to_google(schema).to_google_format())
    return [{"functionDeclarations": declarations}] if declarations else []


def toGeminiToolChoice(tool_choice: typing.Optional[str]) -> typing.Optional[dict]:
    """OpenAI `tool_choice` → Gemini `toolConfig`；未识别取值按 `AUTO`。"""
    if not tool_choice:
        return None
    key = str(tool_choice).strip().lower()
    return {"functionCallingConfig": {"mode": _GEMINI_TOOL_CHOICE.get(key, "AUTO")}}
