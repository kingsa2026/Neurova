"""内置技能的参数定义（纯静态元数据）

LLM 可见工具 schema 的唯一来源：OpenAISchemaAdapter 通过
`skill._get_parameters()` 读取本表构建 function calling 参数定义。
缺失参数定义会导致模型不知道如何传参，从而不调用对应技能。

字段结构与各 executor.execute(params) 的真实读取逻辑一一对应。
每行四元组：(字段名, JSON类型, 是否必填, 描述)。
"""

from __future__ import annotations

import typing

# skill_id -> 字段四元组列表
_BUILTIN_SKILL_FIELDS: typing.Dict[str, typing.List[typing.Tuple[str, str, bool, str]]] = {
    "memory": [
        ("action", "string", True, "操作类型：search 检索 / store 存储"),
        ("query", "string", False, "检索词或待存储的内容主题"),
        ("limit", "integer", False, "返回条数上限"),
        ("content", "string", False, "action=store 时要存储的完整内容"),
        ("category", "string", False, "记忆分类（可选）"),
    ],
    "web_search": [
        ("query", "string", True, "检索词"),
        ("max_results", "integer", False, "返回结果数上限"),
    ],
    "file_operation": [
        ("operation", "string", True, "文件操作类型：read/write/list/delete"),
        ("file_path", "string", True, "目标文件路径"),
        ("content", "string", False, "operation=write 时写入的内容"),
    ],
}


def get_builtin_skill_parameters(skill_id: str) -> typing.Dict[str, typing.Dict[str, typing.Any]]:
    """按 skill_id 返回参数定义表；未知技能返回空 dict"""
    fields = _BUILTIN_SKILL_FIELDS.get(skill_id, [])
    result: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    for name, ftype, required, desc in fields:
        entry: typing.Dict[str, typing.Any] = {"type": ftype, "description": desc}
        if required:
            entry["required"] = True
        if name == "operation":
            entry["enum"] = ["read", "write", "list", "delete"]
        if name == "action":
            entry["enum"] = ["search", "store"]
        result[name] = entry
    return result
