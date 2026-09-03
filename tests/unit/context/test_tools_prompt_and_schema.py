"""P0 工具可见性修复测试

覆盖：
1. 系统提示不再教 [TOOL_CALL:] 文本格式（消除与原生 function calling 的双通道冲突），
   改为通用工具使用策略；文本格式教学收敛到独立的降级通道 helper
2. 同名工具合并时保留更完整的 builtin schema（web_search 不再被空参技能覆盖）
3. 发给 provider 前的工具 schema 消毒（parameters.type 必须存在）
4. ExecutorBackedSkill 三个内置技能补齐参数定义
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.context.orchestrator import ContextOrchestrator


def make_orchestrator(tool_router=None, skill_registry=None) -> ContextOrchestrator:
    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    # config / tool_router / skill_registry 均为只读属性，派生自 self._agent
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.agent_id = "a1"
    agent.config.user_id = "u1"
    agent.tool_router = tool_router
    agent._skill_registry = skill_registry
    orch._agent = agent
    return orch


def fake_tool(name: str, description: str = "", properties: dict = None, required: list = None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or f"{name} 工具",
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


class FakeRegistry:
    def __init__(self, skills: dict):
        self.skills = skills


def make_skill(name: str, params: dict = None):
    """构造 unpack_skill 可解包、带可选 _get_parameters 的最小技能对象"""
    skill = SimpleNamespace(name=name, description=f"{name} 技能")
    if params is not None:
        skill._get_parameters = lambda: params
    return skill


class TestNoFormatTeachingInSystemPrompt:
    @pytest.mark.asyncio
    async def test_system_prompt_has_no_text_format_teaching(self):
        """原生 FC 模式下系统提示不得再教 [TOOL_CALL:] 文本格式（双通道冲突根因）"""
        orch = make_orchestrator(
            tool_router=SimpleNamespace(get_all_tools=lambda **kw: {"t": fake_tool("web_search")})
        )
        desc = await orch.get_tools_description()
        assert "[TOOL_CALL" not in desc, "系统提示不应再教文本调用格式"

    @pytest.mark.asyncio
    async def test_system_prompt_lists_tools_with_strategy(self):
        orch = make_orchestrator(
            tool_router=SimpleNamespace(get_all_tools=lambda **kw: {"t": fake_tool("web_search", "网络搜索")}
                                        )
        )
        desc = await orch.get_tools_description()
        assert "web_search" in desc
        # 通用使用策略存在：引导主动用工具而不是回复做不到
        assert ("主动" in desc and "工具" in desc)

    @pytest.mark.asyncio
    async def test_empty_tools_returns_empty_description(self):
        orch = make_orchestrator()
        assert await orch.get_tools_description() == ""

    def test_format_hint_helper_exists_for_degraded_path(self):
        """降级路径（provider 不支持原生FC）专用的文本格式教学"""
        from neurova.context.orchestrator import get_tool_call_format_hint

        hint = get_tool_call_format_hint()
        assert "[TOOL_CALL" in hint
        assert "工具名" in hint


class TestSchemaMergePrecedence:
    @pytest.mark.asyncio
    async def test_rich_builtin_schema_not_overwritten_by_empty_skill(self):
        """web_search 的完整内置参数不得被空参技能 proxy 覆盖"""
        rich = fake_tool("web_search", "实时搜索", properties={"query": {"type": "string"}}, required=["query"])
        orch = make_orchestrator(
            tool_router=SimpleNamespace(get_all_tools=lambda **kw: {"w": rich}),
            skill_registry=FakeRegistry({"web_search": make_skill("web_search")}),  # 无 _get_parameters → 空参
        )
        tools = await orch.build_tools_for_llm()
        ws = next(t for t in tools if t["function"]["name"] == "web_search")
        assert ws["function"]["parameters"]["properties"], "完整 schema 被空参覆盖了"

    @pytest.mark.asyncio
    async def test_parameterized_skill_still_wins(self):
        """真正带参数定义的技能应替换占位条目"""
        placeholder = fake_tool("my_skill", "占位")
        skill_schema_params = {"target": {"type": "string", "required": True}}
        orch = make_orchestrator(
            tool_router=SimpleNamespace(get_all_tools=lambda **kw: {"m": placeholder}),
            skill_registry=FakeRegistry({"my_skill": make_skill("my_skill", skill_schema_params)}),
        )
        tools = await orch.build_tools_for_llm()
        got = next(t for t in tools if t["function"]["name"] == "my_skill")
        assert "target" in got["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_parameters_type_sanitized_for_providers(self):
        """缺 parameters.type 的工具会被消毒补全，避免 provider 400"""
        broken = {"type": "function", "function": {"name": "odd", "description": "x", "parameters": {}}}
        orch = make_orchestrator(
            tool_router=SimpleNamespace(get_all_tools=lambda **kw: {"o": broken})
        )
        tools = await orch.build_tools_for_llm()
        odd = next(t for t in tools if t["function"]["name"] == "odd")
        assert odd["function"]["parameters"].get("type") == "object"
        assert isinstance(odd["function"]["parameters"].get("properties"), dict)


class TestBuiltinSkillSchemas:
    def _skill_names_with_schemas(self):
        from neurova.skills.builtin import create_builtin_executor_skills

        out = {}
        for s in create_builtin_executor_skills():
            getter = getattr(s, "_get_parameters", None)
            out[s.name] = getter() if callable(getter) else {}
        return out

    def test_all_three_have_parameter_definitions(self):
        schemas = self._skill_names_with_schemas()
        for name in ("memory", "web_search", "file_operation"):
            assert schemas.get(name), f"{name} 缺少参数定义"

    def test_web_search_query_required(self):
        p = self._skill_names_with_schemas()["web_search"]
        assert "query" in p
        assert any(k.get("required") for k in p.values())

    def test_file_operation_covers_operations(self):
        p = self._skill_names_with_schemas()["file_operation"]
        assert "operation" in p and "file_path" in p
