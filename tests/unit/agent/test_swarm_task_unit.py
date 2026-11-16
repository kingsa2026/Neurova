"""P1-1 结构化任务单元（TaskUnit）单元测试。

覆盖：
- parseTaskUnit：None/空/合法（camel+snake 别名）/缺 goal/坏 reviewMode/非 dict；
- renderTaskUnitPrompt：无单元原样返回；有单元渲染任务书分节；
- spawn 携带 task_unit：run 落账、member 收到任务书拼装提示词、to_dict 可见；
- spawn 携带非法 task_unit：结构化拒绝 TASK_UNIT_INVALID；
- spawn_subagent 工具 schema 暴露 task_unit 参数，执行器透传。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.agent.task_unit import parseTaskUnit, renderTaskUnitPrompt
from neurova.builtin_tools import _BUILTIN_SCHEMAS
from neurova.tool_executor import ToolExecutor


def make_mock_agent(name="子Agent", reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestParseTaskUnit:
    def test_none_and_empty_return_none(self):
        assert parseTaskUnit(None) is None
        assert parseTaskUnit({}) is None

    def test_valid_camel_case(self):
        unit = parseTaskUnit({
            "goal": "完成登录页重构",
            "expectedResult": "可运行的页面 + 测试",
            "acceptanceCriteria": ["登录成功跳转", "错误提示可见"],
            "requiredInputs": ["现有路由表"],
            "artifactOwnership": "归档进父任务",
            "reviewMode": "supervisor",
            "dependencies": ["swarm_abc"],
        })
        assert unit is not None
        assert unit.goal == "完成登录页重构"
        assert unit.acceptanceCriteria == ["登录成功跳转", "错误提示可见"]
        assert unit.reviewMode == "supervisor"
        assert unit.dependencies == ["swarm_abc"]

    def test_snake_case_alias_accepted(self):
        unit = parseTaskUnit({
            "goal": "g",
            "acceptance_criteria": ["c1"],
            "review_mode": "none",
        })
        assert unit.acceptanceCriteria == ["c1"]
        assert unit.reviewMode == "none"

    def test_missing_goal_raises(self):
        with pytest.raises(ValueError, match="goal"):
            parseTaskUnit({"expectedResult": "x"})

    def test_bad_review_mode_raises(self):
        with pytest.raises(ValueError, match="reviewMode"):
            parseTaskUnit({"goal": "g", "reviewMode": "everyone"})

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="对象"):
            parseTaskUnit("重构登录页")


class TestRenderPrompt:
    def test_without_unit_returns_task_unchanged(self):
        assert renderTaskUnitPrompt("原始任务", None) == "原始任务"
        assert renderTaskUnitPrompt("原始任务", {}) == "原始任务"

    def test_with_unit_renders_sections(self):
        rendered = renderTaskUnitPrompt("原始任务", {
            "goal": "完成 X",
            "expectedResult": "报告一份",
            "acceptanceCriteria": ["含结论", "含数据来源"],
            "reviewMode": "supervisor",
        })
        assert rendered.startswith("原始任务")
        assert "【任务书（结构化）】" in rendered
        assert "目标：完成 X" in rendered
        assert "预期产物：报告一份" in rendered
        assert "1. 含结论" in rendered
        assert "2. 含数据来源" in rendered
        assert "评审方式" in rendered


class TestSpawnWithTaskUnit:
    @pytest.mark.asyncio
    async def test_spawn_stores_unit_and_member_gets_rendered_prompt(self, swarm):
        agent = make_mock_agent(reply="已按任务书完成")
        unit = {
            "goal": "完成登录页重构",
            "acceptanceCriteria": ["登录成功跳转", "错误提示可见"],
            "reviewMode": "supervisor",
        }
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="重构登录页", agent_id="researcher", task_unit=unit)

        assert result["status"] == "completed"
        stored = swarm.status(result["subagent_id"])
        assert stored["task_unit"]["goal"] == "完成登录页重构"
        assert stored["task_unit"]["acceptanceCriteria"] == ["登录成功跳转", "错误提示可见"]
        # member 实际收到的提示词 = 原始任务 + 任务书分节
        prompt = agent.chat.call_args[0][0]
        assert prompt.startswith("重构登录页")
        assert "【任务书（结构化）】" in prompt
        assert "1. 登录成功跳转" in prompt

    @pytest.mark.asyncio
    async def test_spawn_without_unit_keeps_plain_prompt(self, swarm):
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="纯文本任务", agent_id="researcher")
        assert result["status"] == "completed"
        assert swarm.status(result["subagent_id"])["task_unit"] is None
        assert agent.chat.call_args[0][0] == "纯文本任务"

    @pytest.mark.asyncio
    async def test_invalid_unit_structurally_rejected(self, swarm):
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务", agent_id="researcher", task_unit={"noGoal": 1})
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "TASK_UNIT_INVALID"
        agent.chat.assert_not_called()


class TestToolSurface:
    def test_schema_exposes_task_unit(self):
        props = _BUILTIN_SCHEMAS["spawn_subagent"]["parameters"]["properties"]
        assert "task_unit" in props
        assert props["task_unit"]["required"] == ["goal"]
        assert "acceptanceCriteria" in props["task_unit"]["properties"]

    @pytest.mark.asyncio
    async def test_executor_passes_task_unit_through(self, swarm):
        agent = make_mock_agent(reply="完成")
        exe = ToolExecutor(agent)
        unit = {"goal": "g", "acceptanceCriteria": ["c1"]}
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await exe._execute_spawn_subagent({
                "task": "子任务", "agent_id": "a1", "task_unit": unit,
            })
        assert result["status"] == "completed"
        assert swarm.status(result["subagent_id"])["task_unit"]["goal"] == "g"
