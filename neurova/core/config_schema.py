# -*- coding: utf-8 -*-
"""配置表单契约单源（Yuxi 对比 P2 #15）。

对位 Yuxi `MilvusRetrievalConfig` dataclass metadata → `get_query_params_config`
反射生成前端参数面板。Neurova 前后端键位契约历次漂移（睡眠设置键位、负一屏
公共字段丢弃、ChannelIntegration 不回填）的共同根因=字段清单前后端各写各的。

`form_options(pydantic_model)` 从模型字段单源生成表单描述列表：
  [{"key","label","description","type","required","default","secret"}]
label 取 Field(title=...)（或 json_schema_extra["label"]），secret 取
json_schema_extra["secret"]=True（凭据字段：前端只写不读、UI 打码）。
消费端点可把结果附在响应（新键加性），并配**契约测试**钉住
"前端提交的键 ⊆ schema 键集"。
"""
from __future__ import annotations

import types
from typing import Any, Dict, List, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_TYPE_NAMES = {bool: "boolean", int: "integer", float: "number", str: "string"}


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str, list, dict)):
        return v
    return str(v)


def _type_name(ann: Any) -> str:
    origin = get_origin(ann)
    if origin in (types.UnionType, None) and str(ann).startswith("typing.Optional"):
        origin = types.UnionType
    if origin is types.UnionType or (origin is not None and str(origin) == "typing.Union"):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return _type_name(args[0])
        return "string"
    if ann in _TYPE_NAMES:
        return _TYPE_NAMES[ann]
    if origin in (list, List):
        return "array"
    if origin in (dict, Dict):
        return "object"
    return "string"


def form_options(model_cls: type) -> List[Dict[str, Any]]:
    """从 pydantic 模型反射出表单描述列表（单源）。"""
    if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
        raise TypeError(f"form_options 需要 pydantic BaseModel 子类，收到 {model_cls!r}")
    out: List[Dict[str, Any]] = []
    for name, f in model_cls.model_fields.items():
        extra = f.json_schema_extra if isinstance(f.json_schema_extra, dict) else {}
        # default：显式标量默认值透出；PydanticUndefined / factory → None
        default = None if f.default_factory or f.default is PydanticUndefined else _jsonable(f.default)
        out.append(
            {
                "key": name,
                "label": extra.get("label") or f.title or name,
                "description": f.description or extra.get("description") or "",
                "type": _type_name(f.annotation),
                "required": bool(f.is_required()),
                "default": default,
                "secret": bool(extra.get("secret", False)),
            }
        )
    return out
