"""
TDD 测试:工具调用断点修复

 Bug 现象:聊天对话触发工具,工具执行成功但 agent 报告"执行错误"。

 根因(分层):
 - 断点 #5 (HIGH): base.py tool message 缺 name 字段,DeepSeek/通义/智谱等
   OpenAI 兼容 API 在 strict 模式下要求 tool message 必须含 name,
   缺失会导致后续 LLM 调用 400,触发 _tools_supported=False 永久禁用。
 - 断点 #2 (HIGH): console.py 强制传空历史,LLM 缺上下文导致工具参数错误。
 - 断点 #10 (MID): openai_loop.py _tools_supported 一次性 400 后永久 False,
   后续所有工具调用静默失效,需要重启 agent 才恢复。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────
# 断点 #5: tool message 必须含 name 字段
# ──────────────────────────────────────────────────────────────────

class TestToolMessageNameField:
    """#B-5: base.py handle_tool_calls 返回的 tool message 必须含 name 字段。

    OpenAI 官方 API 的 name 字段可选,但 DeepSeek/通义/智谱/Kimi 等
    OpenAI 兼容服务在 strict 模式下要求 tool message 必须含 name。
    缺失会导致后续 LLM 调用返回 400 "Missing required field: name",
    触发 _tools_supported=False 永久禁用,所有工具调用静默失效。
    """

    @pytest.mark.asyncio
    async def test_success_tool_message_has_name(self):
        """工具执行成功时,tool message 必须包含 name 字段。"""
        from neurova.agent.loops.openai_loop import OpenAILoop

        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        agent.tool_router = None

        loop = OpenAILoop.__new__(OpenAILoop)
        loop.agent = agent

        tool_calls = [{
            "id": "call_001",
            "type": "function",
            "function": {
                "name": "weather",
                "arguments": json.dumps({"city": "北京"}),
            },
        }]

        # 模拟 SkillRegistry 和 ToolRouter 都不处理,落到 except 分支
        # (V2-8 删除死代码 _build_tools_from_skills 后,此 patch 不再需要)
        messages = await loop.handle_tool_calls(tool_calls, [])

        # 找到 role=tool 的消息
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) > 0, "应有 tool 消息"
        for tm in tool_msgs:
            assert "name" in tm, (
                f"tool message 缺 name 字段。"
                f"OpenAI 兼容 API (DeepSeek/通义/智谱) 要求 tool message 含 name。"
                f"实际消息:{tm!r}"
            )
            assert tm["name"] == "weather", (
                f"tool message 的 name 字段应为工具名 'weather'。实际:{tm['name']!r}"
            )

    @pytest.mark.asyncio
    async def test_error_tool_message_has_name(self):
        """工具执行失败时,tool message 也必须包含 name 字段。"""
        from neurova.agent.loops.openai_loop import OpenAILoop

        agent = MagicMock()
        agent._tool_messages_list = []
        # 让 skill_registry 抛异常触发 except 分支
        sr = MagicMock()
        sr.execute_skill = AsyncMock(side_effect=RuntimeError("skill 内部错误"))
        agent.skill_registry = sr
        agent.tool_router = None

        loop = OpenAILoop.__new__(OpenAILoop)
        loop.agent = agent

        tool_calls = [{
            "id": "call_002",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": json.dumps({"query": "test"}),
            },
        }]

        messages = await loop.handle_tool_calls(tool_calls, [])

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        for tm in tool_msgs:
            assert "name" in tm, (
                f"失败 tool message 也缺 name 字段。实际:{tm!r}"
            )
            assert tm["name"] == "web_search"

    @pytest.mark.asyncio
    async def test_not_found_tool_message_has_name(self):
        """工具未找到时(SkillRegistry+ToolRouter 都不处理),tool message 必须含 name。"""
        from neurova.agent.loops.openai_loop import OpenAILoop

        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        agent.tool_router = None

        loop = OpenAILoop.__new__(OpenAILoop)
        loop.agent = agent

        tool_calls = [{
            "id": "call_003",
            "type": "function",
            "function": {
                "name": "nonexistent_tool",
                "arguments": "{}",
            },
        }]

        messages = await loop.handle_tool_calls(tool_calls, [])

        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        for tm in tool_msgs:
            assert "name" in tm, (
                f"未找到工具的 tool message 也缺 name 字段。实际:{tm!r}"
            )
            assert tm["name"] == "nonexistent_tool"


# ──────────────────────────────────────────────────────────────────
# 断点 #2: console.py 不应强制传空历史
# ──────────────────────────────────────────────────────────────────

class TestConsoleHistoryNotForceEmpty:
    """#B-2: console.py 不应强制传 history=[] 给 agent.chat()。

    强制空历史导致 LLM 缺对话上下文:
    - 工具参数因指代不清而错误(如"搜一下他"不知道"他"是谁)
    - 多轮工具调用场景完全失败
    - agent 忘记之前已执行过的工具结果

    修复:不传 history metadata,让 agent.chat() 自己恢复 session 历史。
    """

    def test_console_no_history_in_metadata(self):
        """console.py 不应在 metadata 中传 history=[]。"""
        src = open(
            "e:/项目/Neurova/neurova/api/endpoints/console.py",
            encoding="utf-8",
        ).read()
        # 查找 history_for_agent = [] 这行
        # 修复后应删除此变量,或改为从 session 加载
        assert (
            'metadata={"history": history_for_agent}' not in src
            or 'history_for_agent = []' not in src
        ), (
            "console.py 仍强制传 history=[] 给 agent,LLM 缺对话上下文。"
            "应删除 history_for_agent 变量,让 agent.chat() 自己恢复 session 历史。"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 #10: _tools_supported 不应永久禁用
# ──────────────────────────────────────────────────────────────────

class TestToolsSupportedNotPermanent:
    """#B-10: OpenAILoop._tools_supported 不应一次性 400 后永久 False。

    当前实现:_tools_supported = False 后,后续所有 chat 都不注入 tools,
    工具调用静默失效,需要重启 agent 才恢复。

    修复方案:改为 per-request 禁用(本次请求 400 后本次不传 tools,
    但不污染下一次 chat 请求)。
    """

    def test_tools_supported_resets_per_request(self):
        """_tools_supported 应在每个 predict_step 开始时重置为 True。"""
        src = open(
            "e:/项目/Neurova/neurova/agent/loops/openai_loop.py",
            encoding="utf-8",
        ).read()
        # 查找 predict_step 方法中是否重置 _tools_supported
        # 修复后应在 predict_step 开始时重置(或在 except 后恢复)
        assert (
            "self._tools_supported = True" in src
            and src.count("self._tools_supported = True") >= 2
        ), (
            "OpenAILoop._tools_supported 应在每次 predict_step 开始时重置为 True,"
            "避免一次性 400 后永久禁用所有工具调用。"
            "应在 __init__ 和 predict_step 两处设置 _tools_supported = True。"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 #4: SkillRegistry 异常应 fallback 到 ToolRouter
# ──────────────────────────────────────────────────────────────────

class TestSkillExceptionFallback:
    """#B-4: SkillRegistry 执行抛异常时,应 fallback 到 ToolRouter 而非直接报错。

    当前实现:try 块包裹 SkillRegistry + ToolRouter,异常直接进 except,
    返回 error,ToolRouter 不被尝试。
    """

    @pytest.mark.asyncio
    async def test_skill_exception_falls_back_to_tool_router(self):
        """SkillRegistry 抛异常时,应尝试 ToolRouter 而非直接失败。"""
        from neurova.agent.loops.base import BaseAgentLoop

        agent = MagicMock()
        agent._tool_messages_list = []
        # SkillRegistry 抛异常
        sr = MagicMock()
        sr.execute_skill = AsyncMock(side_effect=RuntimeError("skill bug"))
        agent.skill_registry = sr
        # ToolRouter 应能成功执行(base.py 读取 router_result.result,不是 .data)
        tr = MagicMock()
        router_result = MagicMock()
        router_result.success = True
        router_result.result = {"result": "from_tool_router"}
        tr.execute = AsyncMock(return_value=router_result)
        agent.tool_router = tr

        from neurova.agent.loops.openai_loop import OpenAILoop

        loop = OpenAILoop.__new__(OpenAILoop)
        loop.agent = agent

        tool_calls = [{
            "id": "call_004",
            "type": "function",
            "function": {
                "name": "weather",
                "arguments": json.dumps({"city": "上海"}),
            },
        }]

        messages = await loop.handle_tool_calls(tool_calls, [])

        # ToolRouter 应被调用(fallback 生效)
        assert tr.execute.called, (
            "SkillRegistry 异常时,ToolRouter 应被尝试 fallback 执行"
        )
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_msgs) > 0
        assert tool_msgs[0]["name"] == "weather"
        # 结果应是 ToolRouter 的成功结果
        result = json.loads(tool_msgs[0]["content"])
        assert result.get("result") == "from_tool_router"
