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
        # P0-B1：轮次状态已迁 ContextVar，实现读 agent 公有快照 API——
        # mock 桥接（残留处理 2026-09-13）
        mock_agent.get_tool_messages_snapshot = lambda: mock_agent._tool_messages_list
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
        mock_agent.get_tool_messages_snapshot = lambda: mock_agent._tool_messages_list
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
        # P0-B1：清空走 reset_tool_messages 公有 API（残留处理 2026-09-13）
        mock_agent.reset_tool_messages = lambda: mock_agent._tool_messages_list.clear()
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

    def test_exception_tool_result_uses_the_single_failure_producer(self):
        """异常 tool_result 的正文只许由**那台**失败正文生产者构造（原 N5 的第二格式不得复活）。

        现契约（§6-499 定责后重写）：
        - 工具异常由执行咽喉 `native_tool_dispatch.execute_native_tool` 转成
          `{"success": False, "error": "工具执行异常: <原因>"}`，回装正文一律走
          `buildFailureToolBody`（诊断键名单也在它内部，此处不抄第二份）；
        - 本档建档时钉的字面量（先 `"执行出错: "` 后 `"执行失败"`）跟着措辞走，
          产品改词它就红——判据要钉的是「正文出自单源、原因传得出去、旧格式不复活」，
          不是某一句中文。
        - 接缝同步跟到咽喉：异常须由 `tool_executor.execute_tool` 抛出（当年打的是
          `skill_registry.execute_skill`，原生链改走咽喉后那个接缝已不在执行路径上，
          于是诱发出的是 `MagicMock can't be used in 'await'`——测的是替身，不是产品）。
        """
        import json

        from neurova.agent import native_tool_dispatch as native
        from neurova.agent.loops.base import BaseAgentLoop

        class _ConcreteLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return None

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        # P3-c 收窄：base.handle_tool_calls 经 append_tool_messages 回装，桥接到真实列表
        mock_agent.append_tool_messages = lambda records: mock_agent._tool_messages_list.extend(records or [])
        mock_agent.llm_client = MagicMock()
        executor = MagicMock()
        executor.execute_tool = AsyncMock(side_effect=RuntimeError("boom"))
        mock_agent.tool_executor = executor
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
        body = json.loads(tool_results[0]["result"])
        assert tool_results[0]["success"] is False, "失败轮不得把 success 写成真"
        assert "boom" in body["error"], f"原因必须在回环正文里，实际 {body}"
        assert set(body) <= {"error"} | set(native.FAILURE_DIAGNOSTIC_KEYS), (
            f"失败正文混进了单源名单之外的键：{sorted(body)}")
        assert body == native.buildFailureToolBody(body["error"], None), (
            f"正文不是那台生产者构造的：{body}")
        assert "Error:" not in tool_results[0]["result"], "原 N5 的第二格式复活"


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
            async def aiter():
                yield {"type": "content", "data": "Hello"}
                yield {"type": "reasoning", "data": "thinking..."}
                yield {"type": "tool_call", "data": {"name": "search"}}
                yield {"type": "content", "data": " world"}
                yield {"type": "done", "reply": "Hello world"}

            return aiter()  # V2-6 契约：predict_step 为 await 后返回异步迭代器

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

class TestN1NLSynthesizedToolRegistration:
    """N-1 的现役契约：合成产物**经创建治理闸**注册；闸拦下时要看得见理由。

    建档时（2026-09）产品里合成成功只 log、从不注册 ⇒ 整条管线是死代码。后来接上了
    `publish_automatic(agentLibrary(agent_id), registry, manifest)`，而它自带一道
    「同一工具序列至少 3 条独立真实成功」的闸（`creation_governance.eligible`／
    `MIN_SUCCESSES`）。于是原断言的前提被换掉了：注册不再是"合成即注册"，而是
    "证据够才注册"——所以本档现钉三态，而不是只钉最后一态：

    1. 没有能力缺口信号 ⇒ 合成器根本不该被调（入口判据 T-03 已从"用户话说得像命令"
       改成 `capability_gap` 单源投出的 capability 族缺口；本批定责前那条红的确切成因
       就是这条：测试只塞了 `user_input`，第一步就 return）；
    2. 有缺口、合成出 COMPLETED 产物，但零证据 ⇒ 治理闸拒绝，且拒绝理由进日志
       （工单 014 那条"拦了还是根本没门"必须能从读数看出来）；
    3. 补齐 3 条独立证据 ⇒ 经同一个闸注册，`list_skills()` 与 `SkillService` 两侧都读得到
       （写→读闭环，N-1 的原命题在这一态照旧成立）。
    """

    _USER_INPUT = "搜索用户数据"
    _AGENT_ID = "test_agent"

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        from neurova.agent.capability_gap import clearCapabilityGap
        from neurova.skills.registry import SkillRegistry
        from neurova.skills.skill_service import SkillService

        clearCapabilityGap("session-tool-bugs-n1")
        registry = SkillRegistry()
        saved = dict(registry._skills)
        registry._skills.clear()
        service = SkillService(agent_id=self._AGENT_ID, skills_dir=str(tmp_path))
        # 接缝打在**使用方**的模块名上：`chat_pipeline` 顶层 import 了 agentLibrary，
        # 落盘走向由它决定（不 patch 就会写进 NEUROVA_DATA_DIR 的常驻库）。
        monkeypatch.setattr("neurova.agent.chat_pipeline.agentLibrary", lambda agent_id: service)
        self._registry, self._service = registry, service
        yield
        registry._skills.clear()
        registry._skills.update(saved)
        clearCapabilityGap("session-tool-bugs-n1")

    def _pipeline(self):
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer

        mock_agent = MagicMock()
        mock_agent.tool_synthesizer = NLToolSynthesizer()
        mock_agent._skill_registry = self._registry
        mock_agent.skill_manager = None      # 跳过 auto_acquire 互斥
        mock_agent.config.agent_id = self._AGENT_ID
        pipeline = object.__new__(ChatPipeline)   # __init__ 需要大量依赖
        pipeline._agent = mock_agent
        return pipeline

    def _check(self, *, withGap: bool):
        from neurova.agent.capability_gap import GAP_CATALOG_MISS, recordCapabilityGap
        from neurova.agent.chat_pipeline import ChatContext

        if withGap:
            recordCapabilityGap(GAP_CATALOG_MISS, {"query": self._USER_INPUT},
                                session_id="session-tool-bugs-n1")
        asyncio.run(self._pipeline()._check_nl_synthesis(ChatContext(user_input=self._USER_INPUT)))

    def test_noGapSignalMeansNoSynthesisAttempt(self):
        """缺口没投 ⇒ 一条技能都不会多出（入口判据是缺口，不是措辞）。"""
        self._check(withGap=False)
        assert self._registry.list_skills() == [], "没有缺口信号却注册了技能——入口闸失效"

    def test_gapWithoutEvidenceIsRefusedWithAReason(self, caplog):
        """闸拦下必须留痕：零证据时不注册，且日志说得出是闸拦的。"""
        with caplog.at_level("INFO"):
            self._check(withGap=True)
        assert self._registry.list_skills() == [], (
            "零证据却注册成功——创建治理闸被绕过（MIN_SUCCESSES 失效）")
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "合成技能未发布" in text and "证据" in text, (
            "拒绝没留痕，读不出「闸拦了」还是「根本没门」：" + text[-400:])

    def test_gapWithThreeEvidence_registersAndStaysReadable(self):
        """补齐 3 条独立真实成功 ⇒ 同一道闸放行，注册面与持久面都读得到。"""
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer

        # 先按同一输入问一次真实合成器，拿它的工具序列去记账——证据的「结构身份」
        # 由序列决定（`task_results` 按 structure 聚合），抄来的序列不算证据。
        probe = NLToolSynthesizer().synthesize(description=self._USER_INPUT,
                                               context={"author_id": self._AGENT_ID})
        assert probe.success and probe.synthesized_tool is not None, "合成器离线不可用"
        steps = list(probe.synthesized_tool.tool_sequence)
        for i in range(3):
            assert self._service.creation_evidence.record(
                f"task-{i}", steps, self._USER_INPUT, True)

        self._check(withGap=True)

        skills = self._registry.list_skills()
        assert len(skills) == 1, f"应注册 1 条合成技能，实际 {len(skills)}"
        registered = skills[0]
        assert registered.name, "注册的 skill 应有 name"
        assert registered.description == self._USER_INPUT, (
            f"description 应为原始描述，实际: {registered.description}")
        # 门面（list_skills 返回 SkillInfo，没有 config）之外还要钉运行态条目本体：
        # 合成标记与工具序列丢了，下一轮 has_tool 判据照样看不见它 ⇒ 重复合成（N-1 原命题）
        runtime = next(iter(self._registry._skills.values()))
        config = getattr(runtime, "config", None) or {}
        assert config.get("synthesized") is True, config
        assert config.get("tool_sequence") == steps, config
        # 写→读闭环：磁盘侧（前端技能页读的那一面）也必须看见它，否则又是重启即丢
        persisted = str(self._service.list_skills())
        assert self._USER_INPUT in persisted, persisted

