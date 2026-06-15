"""
工具系统标准化 API

提供以下端点:
- GET    /v1/tools/formats          获取支持的 Schema 格式
- POST   /v1/tools/schema           创建工具 Schema
- POST   /v1/tools/convert          转换 Schema 格式
- POST   /v1/tools/validate         验证 Schema
- POST   /v1/tools/parse            解析工具调用
- POST   /v1/tools/batch-convert    批量转换
- GET    /v1/tools/examples          获取 Schema 示例
"""

import logging
from enum import Enum
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class SchemaFormat(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    NEUROVA = "neurova"


class ToolSchema(BaseModel):
    name: str
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    format: str = "neurova"


class CreateToolSchemaRequest(BaseModel):
    name: str = Field(..., description="工具名称")
    description: str = Field(default="", description="工具描述")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="参数定义")


class ConvertSchemaRequest(BaseModel):
    tool_schema: Dict[str, Any] = Field(..., alias="schema", description="源 Schema")
    source_format: str = Field(default="neurova", description="源格式")
    target_format: str = Field(default="openai", description="目标格式")

    class Config:
        populate_by_name = True


class ValidateSchemaRequest(BaseModel):
    tool_schema: Dict[str, Any] = Field(..., alias="schema", description="待验证的 Schema")
    format: str = Field(default="openai", description="格式")

    class Config:
        populate_by_name = True


class ParseToolCallRequest(BaseModel):
    message: str = Field(..., description="LLM 消息")
    available_tools: List[Dict[str, Any]] = Field(default_factory=list)


def _to_openai(name: str, desc: str, params: Dict) -> Dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}


def _to_anthropic(name: str, desc: str, params: Dict) -> Dict:
    return {"name": name, "description": desc, "input_schema": params}


@router.get("/formats")
async def get_supported_formats():
    """获取支持的 Schema 格式"""
    return {"code": 0, "data": {"formats": ["openai", "anthropic", "neurova"]}}


@router.post("/schema", response_model=ToolSchema)
async def create_tool_schema(body: CreateToolSchemaRequest):
    """创建工具 Schema"""
    return ToolSchema(name=body.name, description=body.description, parameters=body.parameters, format="neurova")


@router.post("/convert")
async def convert_schema_format(body: ConvertSchemaRequest):
    """转换 Schema 格式"""
    src = body.tool_schema
    name = src.get("name") or src.get("function", {}).get("name", "")
    desc = src.get("description") or src.get("function", {}).get("description", "")
    params = src.get("parameters") or src.get("input_schema") or src.get("function", {}).get("parameters", {})

    if body.target_format == "openai":
        return {"code": 0, "data": _to_openai(name, desc, params)}
    elif body.target_format == "anthropic":
        return {"code": 0, "data": _to_anthropic(name, desc, params)}
    else:
        return {"code": 0, "data": {"name": name, "description": desc, "parameters": params, "format": "neurova"}}


@router.post("/validate")
async def validate_schema(body: ValidateSchemaRequest):
    """验证 Schema"""
    schema = body.tool_schema
    errors = []
    if body.format == "openai":
        fn = schema.get("function", schema)
        if not fn.get("name"):
            errors.append("Missing 'name' field")
        if not fn.get("parameters"):
            errors.append("Missing 'parameters' field")
    elif body.format == "anthropic":
        if not schema.get("name"):
            errors.append("Missing 'name' field")
    return {"code": 0, "data": {"valid": len(errors) == 0, "errors": errors}}


@router.post("/parse")
async def parse_tool_call(body: ParseToolCallRequest):
    """解析工具调用"""
    import json

    try:
        # 简单的 JSON 工具调用解析
        msg = body.message.strip()
        if msg.startswith("```"):
            lines = msg.split("\n")
            msg = "\n".join(lines[1:-1]) if len(lines) > 2 else msg
        parsed = json.loads(msg)
        return {"code": 0, "data": {"tool_calls": [parsed] if isinstance(parsed, dict) else parsed}}
    except json.JSONDecodeError:
        return {"code": 0, "data": {"tool_calls": [], "message": "No valid tool call found"}}


@router.post("/batch-convert")
async def batch_convert_schemas(
    schemas: List[Dict[str, Any]],
    target_format: str = "openai",
):
    """批量转换 Schema"""
    results = []
    for src in schemas:
        name = src.get("name", "")
        desc = src.get("description", "")
        params = src.get("parameters", {})
        if target_format == "openai":
            results.append(_to_openai(name, desc, params))
        elif target_format == "anthropic":
            results.append(_to_anthropic(name, desc, params))
        else:
            results.append({"name": name, "description": desc, "parameters": params})
    return {"code": 0, "data": {"schemas": results}}


@router.get("/examples")
async def get_schema_examples():
    """获取 Schema 示例"""
    return {
        "code": 0,
        "data": {
            "openai": _to_openai(
                "get_weather",
                "Get weather info",
                {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            ),
            "anthropic": _to_anthropic(
                "get_weather",
                "Get weather info",
                {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            ),
        },
    }
