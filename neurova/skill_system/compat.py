"""
neurova.skill_system.compat — Skill 系统兼容层

Bug W-3 修复:
  原本 orchestrator.build_tools_for_llm (line 625) 试图:
      from neurova.skill_system.compat import OpenAISchemaAdapter
  但本文件不存在，导致 ImportError，fallback 到空参数 schema，
  使 Skill 工具对 LLM 暴露的参数描述不完整（丢失参数定义）。

职责:
  提供 OpenAISchemaAdapter，将 Skill 对象转换为 OpenAI function call schema。
  与 orchestrator.build_tools_for_llm 的 fallback 逻辑（line 630-644）保持一致:
  读取 skill._get_parameters() 返回的 {pname: {"type", "required", "description"}} 字典。

设计原则:
  - 单一职责：仅做 Skill → OpenAI schema 的格式转换
  - 防御式：skill 没有 _get_parameters() 时返回空参数 schema，不抛异常
  - 与 builtin_tools.BuiltinTool.to_openai_format 输出格式一致
"""

from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class OpenAISchemaAdapter:
    """Skill → OpenAI function call schema 适配器

    所有方法均为静态方法，无状态，可被 orchestrator 直接调用:
        schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)
    """

    @staticmethod
    def skill_to_tool_schema(skill: Any) -> Dict[str, Any]:
        """将 Skill 对象转换为 OpenAI function call schema

        Args:
            skill: Skill 实例，需有 name/description 属性，
                   可选实现 _get_parameters() 方法返回参数字典

        Returns:
            OpenAI function call schema dict:
            {
                "type": "function",
                "function": {
                    "name": str,
                    "description": str,
                    "parameters": {
                        "type": "object",
                        "properties": {pname: {"type": ..., "description": ...}},
                        "required": [pname, ...]
                    }
                }
            }
        """
        skill_name = getattr(skill, "name", "unknown_skill")
        skill_desc = getattr(skill, "description", f"Skill: {skill_name}")

        props: Dict[str, Any] = {}
        required: List[str] = []

        params_info = {}
        getter = getattr(skill, "_get_parameters", None)
        if callable(getter):
            try:
                params_info = getter() or {}
            except Exception as e:
                logger.debug("skill %s._get_parameters() 失败: %s", skill_name, e)
                params_info = {}

        for pname, pinfo in params_info.items():
            if not isinstance(pinfo, dict):
                continue
            props[pname] = {
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", pname),
            }
            if pinfo.get("required"):
                required.append(pname)

        return {
            "type": "function",
            "function": {
                "name": skill_name,
                "description": skill_desc,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }


__all__ = ["OpenAISchemaAdapter"]
