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
        ("backend", "string", False, "搜索后端（默认 bing，可选 duckduckgo 或已注册的自定义后端名）"),
    ],
    # 市场技能别名（id 带连字符，与 web_search 同参数字段）——市场安装的
    # web-search 注册名与原内置名不同，缺此条目时模型看不到参数 schema
    "web-search": [
        ("query", "string", True, "检索词"),
        ("max_results", "integer", False, "返回结果数上限"),
        ("backend", "string", False, "搜索后端（默认 bing，可选 duckduckgo 或已注册的自定义后端名）"),
    ],
    "file_operation": [
        ("operation", "string", True, "文件操作类型：read/write/list/delete"),
        ("file_path", "string", True, "目标文件路径"),
        ("content", "string", False, "operation=write 时写入的内容"),
    ],
    "kb_builder": [
        ("action", "string", False, "操作：build 构建知识库（默认）/ record_summary 沉淀心智模型综述"),
        ("topic", "string", True, "知识库主题"),
        ("urls", "array", False, "种子 URL 列表（build 可选；缺省时用搜索发现来源）"),
        ("max_sources", "integer", False, "最多抓取的来源数（默认 5）"),
        ("content", "string", False, "action=record_summary 时要沉淀的综述正文"),
        ("agent_id", "string", False, "来源 agent 标注（可选；条目属主由服务端身份决定）"),
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
            if skill_id == "kb_builder":
                entry["enum"] = ["build", "record_summary"]
            else:
                entry["enum"] = ["search", "store"]
        result[name] = entry
    return result
