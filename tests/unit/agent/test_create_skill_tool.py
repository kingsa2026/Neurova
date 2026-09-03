"""P1-8 create_skill 元工具测试

LLM 可以主动把一组工具调用封装为可复用技能（一键调用、可步间传参）。
覆盖：tool_executor._execute_create_skill 把 manifest 写入 SkillRegistry
使其立即可见可执行（与 P1-5 ToolSequenceSkill 协作）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def make_executor():
    from neurova.tool_executor import ToolExecutor

    registry = MagicMock()
    registry.register_skill = MagicMock(return_value=True)
    agent = MagicMock()
    agent._current_session_id = "s1"
    agent._skill_registry = registry
    return ToolExecutor(agent), registry


class TestCreateSkillSchema:
    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "create_skill" in _BUILTIN_SCHEMAS
        schema = _BUILTIN_SCHEMAS["create_skill"]
        assert {"name", "description", "steps"} <= set(schema["parameters"]["required"])

    def test_executor_branch_wired(self):
        from neurova.tool_executor import ToolExecutor

        # 必须在 _execute_builtin_tool 分派分支里
        src = open("neurova/tool_executor.py", encoding="utf-8").read()
        assert '"create_skill"' in src


class TestCreateSkillExecution:
    @pytest.mark.asyncio
    async def test_skill_registered_and_returns_description(self):
        exe, registry = make_executor()
        result = await exe._execute_builtin_tool(
            "create_skill",
            {
                "name": "fetch_then_save",
                "description": "拉取 URL 内容并保存到文件",
                "steps": [
                    {"name": "browser_extract_text", "params": {"url": "https://example.com"}},
                    {"name": "file_write", "params": {"file_path": "out.txt", "content": "{step_0.text}"}},
                ],
            },
        )
        assert result.get("success") is True
        assert result.get("skill_name") == "fetch_then_save"
        # 调用了 SkillRegistry.register_skill
        registry.register_skill.assert_called_once()
        # manifest 包含 tool_sequence（与 ToolSequenceSkill 约定一致）
        manifest = registry.register_skill.call_args[0][0]
        seq = manifest.config["tool_sequence"]
        assert len(seq) == 2
        assert seq[0]["tool"] == "browser_extract_text"
        assert seq[1]["tool"] == "file_write"

    @pytest.mark.asyncio
    async def test_validates_required_fields(self):
        exe, _ = make_executor()
        for missing in ("name", "description", "steps"):
            kwargs = {"name": "x", "description": "y", "steps": [{"name": "a", "params": {}}]}
            kwargs.pop(missing)
            result = await exe._execute_builtin_tool("create_skill", kwargs)
            assert "error" in result
            assert missing in result["error"] or "缺少" in result["error"]
