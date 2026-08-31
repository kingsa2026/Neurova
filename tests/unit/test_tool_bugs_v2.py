"""
工具使用/创建 bug 第二轮排查测试 (TDD RED→GREEN)

基于 bug-hunt + zoom-out 重新检查发现的 8 个新 bug（N-1~N-10）。
上一个测试文件 test_tool_use_create_bugs.py 已验证 T-1~T-4 修复有效（12/12 PASS）。
本文件覆盖工作区恢复后新发现的 bug，按 TDD vertical slice 逐个推进。

Bug 清单:
  N-9  [MED] skill_generator.py:449   三元表达式优先级错误
  N-4  [HIGH] tool_executor.py:1116    get_tool_messages 读错列表
  N-10 [MED] nl_synthesizer.py:213     parse_description 返回值丢弃
  N-5  [HIGH] loops/base.py:199+211    异常路径双写 tool_result
  N-2  [HIGH] closed_loop.py:189       NLToolSynthesizer 类名冲突
  N-6  [HIGH] chat_pipeline.py:779     流式事件 str() 化污染回复
  N-3  [HIGH] evolution_facade.py:269  synthesize_tools 三重断裂
  N-1  [CRIT] chat_pipeline.py:542     NL 合成工具从未注册
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════
# N-9: 三元表达式优先级错误 (skill_generator.py:449)
# ═══════════════════════════════════════════════════════════════

class TestN9TernaryPrecedence:
    """Bug N-9: skill_generator.py:449 三元表达式优先级错误。

    原代码:
        if "->" not in code and ":" not in code.split("def ")[1] if "def " in code else True:

    Python 解析为 ((A and B) if C else True)，而非 (A and (B if C else True))。
    无 "def " 时走 else 返回 True，导致无函数代码被错误添加"建议添加类型提示"警告。
    """

    def test_no_type_hint_warning_for_code_without_function(self):
        """无函数代码不应被提示"建议添加类型提示"。"""
        from neurova.skills.skill_generator import SkillGenerator

        generator = SkillGenerator()
        code_without_func = "# just a comment\nx = 1\nprint(x)\n"
        warnings = asyncio.run(generator._check_best_practices(code_without_func))
        assert "建议添加类型提示" not in warnings, (
            f"无函数代码不应提示类型提示，实际 warnings: {warnings}"
        )

    def test_type_hint_warning_for_function_without_annotation(self):
        """有函数但无类型注解时应提示（验证修复不破坏正向行为）。"""
        from neurova.skills.skill_generator import SkillGenerator

        generator = SkillGenerator()
        code_without_hint = "def foo(x):\n    return x\n"
        warnings = asyncio.run(generator._check_best_practices(code_without_hint))
        assert "建议添加类型提示" in warnings, (
            f"无类型注解的函数应被提示，实际 warnings: {warnings}"
        )

    def test_no_type_hint_warning_for_function_with_return_annotation(self):
        """有返回类型注解的函数不应被提示。"""
        from neurova.skills.skill_generator import SkillGenerator

        generator = SkillGenerator()
        code_with_hint = "def foo(x: int) -> int:\n    return x\n"
        warnings = asyncio.run(generator._check_best_practices(code_with_hint))
        assert "建议添加类型提示" not in warnings, (
            f"有返回注解的函数不应被提示，实际 warnings: {warnings}"
        )


# ═══════════════════════════════════════════════════════════════
# N-4: get_tool_messages 读错列表 (tool_executor.py:1116)
# ═══════════════════════════════════════════════════════════════

class TestN4GetToolMessagesWrongList:
    """Bug N-4: ToolExecutor.get_tool_messages() 读 self._messages_list（本地列表），
    但消费者（chat_pipeline._collect_tool_messages、Agent.get_tool_messages）读
    agent._tool_messages_list。属性名不匹配导致工具消息丢失。

    BE-CORE-008 已修复写入端（line 217 写 agent._tool_messages_list），
    但读取端 get_tool_messages (line 1118) 和 clear_tool_messages (line 1122)
    仍操作本地列表，消费者调用此方法会得到空/不完整数据。
    """

    def test_get_tool_messages_reads_agent_list(self):
        """get_tool_messages 应返回 agent._tool_messages_list 的内容。"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = [
            {"role": "tool", "tool_call_id": "call_1", "content": "result_1"},
        ]
        executor = ToolExecutor(mock_agent)

        msgs = executor.get_tool_messages()

        assert len(msgs) == 1, f"应返回 1 条消息，实际 {len(msgs)}"
        assert msgs[0]["content"] == "result_1"

    def test_get_tool_messages_not_read_local_list(self):
        """get_tool_messages 不应只返回本地 _messages_list（消费者不可见）。"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = [
            {"role": "tool", "tool_call_id": "call_agent", "content": "from_agent"},
        ]
        executor = ToolExecutor(mock_agent)
        # 本地列表为空（默认），agent 列表有数据
        assert len(executor._messages_list) == 0

        msgs = executor.get_tool_messages()

        # 应返回 agent 列表的数据，而非空本地列表
        assert len(msgs) == 1, "应返回 agent._tool_messages_list 的数据，而非空本地列表"

    def test_clear_tool_messages_clears_agent_list(self):
        """clear_tool_messages 应清空 agent._tool_messages_list。"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = [
            {"role": "tool", "tool_call_id": "call_1", "content": "result_1"},
        ]
        executor = ToolExecutor(mock_agent)

        executor.clear_tool_messages()

        assert len(mock_agent._tool_messages_list) == 0, "应清空 agent._tool_messages_list"


# ═══════════════════════════════════════════════════════════════
# N-5: 异常路径双写 tool_result (loops/base.py:199+211)
# ═══════════════════════════════════════════════════════════════

class TestN5DuplicateToolResultOnException:
    """Bug N-5: handle_tool_calls 的 except 块写两次 tool_result。

    loops/base.py:199-207 第一次写 {"result": "执行出错: ..."}，
    loops/base.py:209-219 第二次写 {"result": "Error: ..."}。
    且 line 210 `if hasattr(self.agent, "_tool_messages_list")` 是死代码
    （line 68-69 已初始化该属性），分支永远进入。

    结果：每个工具异常会产生 2 条几乎相同的 tool_result，前端显示重复错误。
    """

    def test_exception_writes_only_one_tool_result(self):
        """工具执行异常时 _tool_messages_list 只应有 1 条 tool_result。"""
        from neurova.agent.loops.base import BaseAgentLoop

        class _ConcreteLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return None

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        # P3-c 收窄：base.handle_tool_calls 经 append_tool_messages 回装，桥接到真实列表
        mock_agent.append_tool_messages = lambda records: mock_agent._tool_messages_list.extend(records or [])
        mock_agent.llm_client = MagicMock()
        mock_agent.skill_registry = AsyncMock()
        mock_agent.skill_registry.execute_skill = AsyncMock(side_effect=RuntimeError("boom"))
        mock_agent.tool_router = None
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.user_id = "test_user"

        loop = _ConcreteLoop(mock_agent)

        tool_calls = [
            {
                "id": "call_1",
                "function": {"name": "bad_tool", "arguments": "{}"},
            }
        ]

        asyncio.run(loop.handle_tool_calls(tool_calls, []))

        tool_results = [
            m for m in mock_agent._tool_messages_list if m.get("type") == "tool_result"
        ]
        assert len(tool_results) == 1, (
            f"异常时应只写 1 条 tool_result，实际 {len(tool_results)}: {tool_results}"
        )

    def test_exception_tool_result_uses_first_format(self):
        """异常 tool_result 应使用第一次写的格式（"执行出错: ..."），非 "Error: ..."。"""
        from neurova.agent.loops.base import BaseAgentLoop

        class _ConcreteLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return None

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        # P3-c 收窄：base.handle_tool_calls 经 append_tool_messages 回装，桥接到真实列表
        mock_agent.append_tool_messages = lambda records: mock_agent._tool_messages_list.extend(records or [])
        mock_agent.llm_client = MagicMock()
        mock_agent.skill_registry = AsyncMock()
        mock_agent.skill_registry.execute_skill = AsyncMock(side_effect=RuntimeError("boom"))
        mock_agent.tool_router = None
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.user_id = "test_user"

        loop = _ConcreteLoop(mock_agent)

        tool_calls = [
            {
                "id": "call_1",
                "function": {"name": "bad_tool", "arguments": "{}"},
            }
        ]

        asyncio.run(loop.handle_tool_calls(tool_calls, []))

        tool_results = [
            m for m in mock_agent._tool_messages_list if m.get("type") == "tool_result"
        ]
        assert len(tool_results) == 1
        # 第一次写的格式是 "执行出错: ..."，重复的第二次是 "Error: ..."
        assert "执行出错" in tool_results[0]["result"], (
            f"应保留第一次写的格式，实际: {tool_results[0]['result']}"
        )


# ═══════════════════════════════════════════════════════════════
# N-2 + N-3: NLToolSynthesizer 类名冲突 + evolution_facade 三重断裂
# ═══════════════════════════════════════════════════════════════

class TestN2N3ClassNameConflictAndFacadeBreakage:
    """Bug N-2: closed_loop.py:189 定义 12 行 stub 类 NLToolSynthesizer，
    与 nl_synthesizer.py:129 的 502 行真实类同名。EvolutionOrchestrator
    (closed_loop.py:215) 持有 stub 实例，而非真实 NL 合成器。

    Bug N-3: evolution_facade.py:279-283 synthesize_tools 三重断裂：
    1. 属性名错: 访问 nl_synthesizer，实际是 tool_synthesizer
    2. 方法名错: 调用 synthesize()，stub 只有 synthesize_from_patterns()
    3. 签名错: 传 top_n=，真实类签名是 synthesize(description, context)
    三重错误导致 synthesize_tools 永远返回空列表。
    """

    def test_closed_loop_no_stub_class_named_NLToolSynthesizer(self):
        """closed_loop 模块不应定义自己的 NLToolSynthesizer stub 类。"""
        import neurova.evolution.closed_loop as cl
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer as RealSynth

        cl_synth = getattr(cl, "NLToolSynthesizer", None)
        if cl_synth is not None:
            assert cl_synth is RealSynth, (
                f"closed_loop.NLToolSynthesizer 应是真实类，实际是独立 stub: {cl_synth}"
            )

    def test_synthesize_tools_calls_correct_attribute_and_method(self):
        """synthesize_tools 应调用 tool_synthesizer.synthesize_from_patterns。"""
        from neurova.evolution.evolution_facade import EvolutionFacade

        facade = EvolutionFacade()
        mock_orch = MagicMock()
        mock_synth = MagicMock()
        mock_synth.synthesize_from_patterns.return_value = [{"tool": "test"}]
        mock_orch.tool_synthesizer = mock_synth
        facade._orchestrator = mock_orch

        result = facade.synthesize_tools(top_n=3)

        assert result == [{"tool": "test"}], f"应返回合成结果，实际 {result}"
        mock_synth.synthesize_from_patterns.assert_called_once_with(top_n=3)

    def test_synthesize_tools_does_not_access_nl_synthesizer_attr(self):
        """synthesize_tools 不应访问 orchestrator.nl_synthesizer（属性不存在）。"""
        from neurova.evolution.evolution_facade import EvolutionFacade

        facade = EvolutionFacade()
        mock_orch = MagicMock()
        mock_synth = MagicMock()
        mock_synth.synthesize_from_patterns.return_value = []
        mock_orch.tool_synthesizer = mock_synth
        # nl_synthesizer 属性不应被访问（不存在）
        facade._orchestrator = mock_orch

        facade.synthesize_tools(top_n=5)

        # nl_synthesizer 不应被访问
        _ = mock_orch.nl_synthesizer  # MagicMock 会创建属性，所以用 mock_synth 验证
        mock_synth.synthesize_from_patterns.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# N-6: 流式事件 str() 化污染回复 (chat_pipeline.py:779-788)
# ═══════════════════════════════════════════════════════════════

class TestN6StreamEventStringification:
    """Bug N-6: _call_loop_stream 的 else 分支把所有非 content 事件 str() 化
    后拼入 reply_parts，导致 reasoning/tool_call/tool_result/done 事件的
    字典字符串表示污染最终回复。

    例如 {"type":"reasoning","data":"思考中"} 会变成
    "{'type': 'reasoning', 'data': '思考中'}" 拼入回复文本，
    随后 execute_text_tool_calls 在污染文本上跑正则，行为不可预测。
    """

    def test_non_content_events_not_stringified_into_reply(self):
        """非 content 事件不应被 str() 化拼入回复。"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

        async def mock_predict(messages, tools=None, stream=True, **kwargs):
            yield {"type": "content", "data": "Hello"}
            yield {"type": "reasoning", "data": "thinking..."}
            yield {"type": "tool_call", "data": {"name": "search"}}
            yield {"type": "content", "data": " world"}
            yield {"type": "done", "reply": "Hello world"}

        mock_agent = MagicMock()
        mock_agent.loop = MagicMock()
        mock_agent.loop.predict_step = mock_predict

        # 绕过 __init__（它需要大量依赖），直接设 _agent
        pipeline = object.__new__(ChatPipeline)
        pipeline._agent = mock_agent

        ctx = ChatContext(user_input="test")
        ctx.context = []

        result = asyncio.run(pipeline._call_loop_stream(ctx, None))

        assert result == "Hello world", f"回复被污染: {result!r}"
        assert "thinking" not in result, "reasoning 事件不应进入回复"
        assert "tool_call" not in result, "tool_call 事件不应进入回复"
        assert "done" not in result, "done 事件不应进入回复"
        assert "{" not in result, "字典字符串表示不应进入回复"


# ═══════════════════════════════════════════════════════════════
# N-10: parse_description 返回值丢弃 (nl_synthesizer.py:213)
# ═══════════════════════════════════════════════════════════════

class TestN10ParseDescriptionResultDiscarded:
    """Bug N-10: synthesize() 调用 self.parse_description(description) 但丢弃
    返回值。parse_description 返回 {words, verbs, nouns, ...}，下游方法
    (detect_category/generate_schema/suggest_tool_sequence) 全部重新从字符串
    解析，既浪费计算又丢失结构化信息。

    修复: 将解析结果存入 tool.metadata["parsed_description"]，使合成工具
    携带结构化解析信息，供消费者（注册器/前端/日志）使用。
    """

    def test_parsed_description_stored_on_tool_metadata(self):
        """合成工具应在 metadata 中携带 parse_description 的解析结果。"""
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer

        synth = NLToolSynthesizer()
        result = synth.synthesize("搜索用户数据并分析")

        assert result.success, f"合成应成功，error: {result.error_message}"
        assert result.synthesized_tool is not None, "应产出 synthesized_tool"

        parsed = result.synthesized_tool.metadata.get("parsed_description")
        assert parsed is not None, (
            "metadata.parsed_description 不应为空——parse_description 返回值不应被丢弃"
        )
        assert "verbs" in parsed, "解析结果应包含 verbs"
        assert "nouns" in parsed, "解析结果应包含 nouns"
        assert "搜索" in parsed["verbs"], f"应识别出动词'搜索'，实际 verbs: {parsed['verbs']}"
        assert "用户" in parsed["nouns"], f"应识别出名名词'用户'，实际 nouns: {parsed['nouns']}"
        assert "数据" in parsed["nouns"], f"应识别出名名词'数据'，实际 nouns: {parsed['nouns']}"


# ═══════════════════════════════════════════════════════════════
# N-1: NL 合成工具未注册 [CRITICAL] (chat_pipeline.py:542-549)
# ═══════════════════════════════════════════════════════════════

class TestN1NLSynthesizedToolNotRegistered:
    """Bug N-1 [CRITICAL]: _check_nl_synthesis 合成工具成功后只 log，
    从不注册到 skill_registry。导致每次相同请求都重新合成，且合成出的工具
    永远无法被 agent 发现和调用——整个 NL 合成管线是死代码。

    原代码 (chat_pipeline.py:542-549):
        if synth_result and synth_result.success and synth_result.synthesized_tool:
            tool = synth_result.synthesized_tool
            if tool.stage.value == "completed":
                logger.info("NL工具合成: %s (置信度=%.2f)", tool.name, tool.confidence)
                # ← 到此结束，从未调用 skill_registry.register_skill()

    修复: 将 SynthesizedTool 转为 Skill manifest 并注册到 skill_registry，
    使后续 chat 轮次可通过 list_skills/get_skill 发现已合成的工具。
    """

    def test_synthesized_tool_registered_to_skill_registry(self):
        """合成成功的工具应注册到 _skill_registry，使 list_skills() 可发现。"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer
        from neurova.skills.registry import SkillRegistry

        # 真实组件
        skill_registry = SkillRegistry()
        tool_synthesizer = NLToolSynthesizer()

        # mock agent：仅暴露 _check_nl_synthesis 需要的属性
        mock_agent = MagicMock()
        mock_agent.tool_synthesizer = tool_synthesizer
        mock_agent._skill_registry = skill_registry
        mock_agent.skill_manager = None  # 跳过 auto_acquire 检查
        mock_agent.config.agent_id = "test_agent"

        # 绕过 __init__（它需要大量依赖）
        pipeline = object.__new__(ChatPipeline)
        pipeline._agent = mock_agent

        ctx = ChatContext(user_input="搜索用户数据")

        asyncio.run(pipeline._check_nl_synthesis(ctx))

        skills = skill_registry.list_skills()
        assert len(skills) > 0, (
            "合成成功的工具应注册到 skill_registry，但 list_skills() 为空"
        )
        # 注册的 skill 应携带合成工具的信息
        registered = skills[0]
        assert registered.name, "注册的 skill 应有 name"
        assert registered.description == "搜索用户数据", (
            f"注册的 skill description 应为原始描述，实际: {registered.description}"
        )
