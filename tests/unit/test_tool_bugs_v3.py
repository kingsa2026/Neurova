"""
工具使用/创建 bug 第三轮排查测试 (TDD RED→GREEN)

基于 docs/bugfix-tool-use-create-bugs-v2.md "未修复的架构观察" 清单，
按 TDD vertical slice + bug-hunt 五阶段逐个推进。

Bug 清单（架构观察项）:
  A-1  [HIGH] chat_pipeline.py:530      has_tool 匹配对 CJK 失效（split 不分词 + 方向反了）
  A-3  [HIGH] anthropic_loop.py:105     _convert_messages_to_anthropic 不处理 "tool" role
  A-5  [MED]  chat_pipeline.py:899-904  _auto_continue 死代码（while 条件已排除 tool_calls）
  A-2  [HIGH] _tool_messages_list       三格式分裂（待调查）
  A-4  [HIGH] openai_loop               超限返回未处理 tool_calls（待调查）
  A-6  [MED]  GeneticEngine             进化工具未注册（待调查）
  A-7  [LOW]  SkillGenerator            孤立死模块（待确认）
  A-8  [LOW]  UnifiedToolRegistry       死代码（待确认）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════
# A-1: has_tool 匹配逻辑对 CJK 失效 (chat_pipeline.py:525-531)
# ═══════════════════════════════════════════════════════════════

class TestA1HasToolCJKFailure:
    """Bug A-1: has_tool 匹配逻辑对 CJK 失效。

    chat_pipeline.py:530 `ctx.user_input.lower().split()` 对中文不分词：
    "搜索用户数据" → split() → ["搜索用户数据"]（整段一个词）
    `kw in s.name.lower()` → "搜索用户数据" in "search_tool" → False

    即使 skill "search_tool" 已注册且语义匹配，has_tool 永远 False，
    每次中文输入都触发重复合成——N-1 修复后会产生大量重复注册。

    根因（双重）:
    1. CJK tokenization: split() 无法分割中文
    2. 方向反了: 应检查 skill 的关键词是否在 user_input 中，
       而不是 user_input 的词是否在 skill name 中
       （skill name 通常是英文，user_input 通常是中文）
    """

    def test_registered_skill_found_for_chinese_input(self):
        """已注册的语义匹配 skill 应被识别，不触发重复合成。"""
        from pathlib import Path

        from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
        from neurova.skills.models import Skill, SkillSource
        from neurova.skills.registry import SkillRegistry

        # 准备：注册一个语义匹配的 skill
        skill_registry = SkillRegistry()
        # 清空单例避免污染（测试后还原）
        saved_skills = dict(skill_registry._skills)
        skill_registry._skills.clear()

        try:
            manifest = Skill(
                id="search_tool",
                name="search_tool",
                description="搜索文件和数据",
                source=SkillSource.LOCAL,
            )
            skill_registry.register_skill(manifest, Path("<test>"))

            # mock tool_synthesizer，验证不被调用
            tool_synthesizer = MagicMock()
            tool_synthesizer.synthesize = MagicMock(return_value=None)

            mock_agent = MagicMock()
            mock_agent.tool_synthesizer = tool_synthesizer
            mock_agent._skill_registry = skill_registry
            mock_agent.skill_manager = None
            mock_agent.config.agent_id = "test_agent"

            pipeline = object.__new__(ChatPipeline)
            pipeline._agent = mock_agent

            ctx = ChatContext(user_input="搜索用户数据")
            asyncio.run(pipeline._check_nl_synthesis(ctx))

            assert not tool_synthesizer.synthesize.called, (
                "已注册语义匹配的 skill（description 含'搜索'）时，"
                "中文输入'搜索用户数据'不应触发重复合成"
            )
        finally:
            # 还原单例状态
            skill_registry._skills.clear()
            skill_registry._skills.update(saved_skills)


# ═══════════════════════════════════════════════════════════════
# A-3: anthropic_loop 不处理 "tool" role (anthropic_loop.py:105)
# ═══════════════════════════════════════════════════════════════

class TestA3AnthropicLoopToolRole:
    """Bug A-3: anthropic_loop._convert_messages_to_anthropic 不处理 "tool" role。

    base.py:149-155 的 handle_tool_calls 生成 OpenAI 格式 tool result:
        {"role": "tool", "tool_call_id": "...", "content": "..."}

    anthropic_loop.py:83-115 的 _convert_messages_to_anthropic 只处理
    user/assistant/system role，line 105 `else: ant_role = role` 把 "tool"
    role 原样传给 Anthropic API。Anthropic 不认识 "tool" role，会报错或
    行为未定义。

    Anthropic 正确格式:
        {"role": "user", "content": [{"type": "tool_result",
         "tool_use_id": "...", "content": "..."}]}

    根因: 缺少 "tool" role → Anthropic tool_result 格式的转换。
    """

    def test_tool_role_converted_to_anthropic_tool_result(self):
        """OpenAI 格式 tool message 应转换为 Anthropic tool_result 格式。"""
        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        loop = object.__new__(AnthropicLoop)
        loop.agent = MagicMock()

        messages = [
            {"role": "user", "content": "搜索文件"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"result": "found"}',
            },
        ]

        converted = loop._convert_messages_to_anthropic(messages)

        # 找到 tool result 对应的转换后 message
        tool_result_msgs = [
            m for m in converted
            if m["role"] == "user"
            and isinstance(m["content"], list)
            and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])
        ]

        assert len(tool_result_msgs) == 1, (
            f"应将 'tool' role 转换为含 tool_result 的 'user' message，"
            f"实际转换结果: {converted}"
        )

        tool_result_block = next(
            c for c in tool_result_msgs[0]["content"]
            if isinstance(c, dict) and c.get("type") == "tool_result"
        )
        assert tool_result_block["tool_use_id"] == "call_1", (
            f"tool_use_id 应为 call_1，实际: {tool_result_block.get('tool_use_id')}"
        )
        assert "found" in str(tool_result_block["content"]), (
            f"content 应包含原 tool result，实际: {tool_result_block.get('content')}"
        )

    def test_no_tool_role_in_converted_messages(self):
        """转换后的 messages 不应包含 'tool' role。"""
        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        loop = object.__new__(AnthropicLoop)
        loop.agent = MagicMock()

        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]

        converted = loop._convert_messages_to_anthropic(messages)

        tool_roles = [m for m in converted if m["role"] == "tool"]
        assert len(tool_roles) == 0, (
            f"转换后不应有 'tool' role（Anthropic 不认识），实际: {tool_roles}"
        )

    def test_assistant_tool_calls_converted_to_tool_use(self):
        """assistant message 的 tool_calls 应转换为 Anthropic tool_use block。"""
        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        loop = object.__new__(AnthropicLoop)
        loop.agent = MagicMock()

        messages = [
            {"role": "user", "content": "搜索文件"},
            {
                "role": "assistant",
                "content": "让我搜索",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }
                ],
            },
        ]

        converted = loop._convert_messages_to_anthropic(messages)

        assistant_msgs = [m for m in converted if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1

        assistant_content = assistant_msgs[0]["content"]
        tool_use_blocks = [
            c for c in assistant_content
            if isinstance(c, dict) and c.get("type") == "tool_use"
        ]

        assert len(tool_use_blocks) == 1, (
            f"assistant content 应包含 1 个 tool_use block，实际: {assistant_content}"
        )
        tu = tool_use_blocks[0]
        assert tu["id"] == "call_1", f"tool_use id 应为 call_1，实际: {tu.get('id')}"
        assert tu["name"] == "search", f"tool_use name 应为 search，实际: {tu.get('name')}"
        assert tu["input"] == {"q": "test"}, (
            f"tool_use input 应为解析后的 dict，实际: {tu.get('input')}"
        )


# ═══════════════════════════════════════════════════════════════
# A-2: _tool_messages_list 三格式分裂 (tool_executor.py:155, 217)
# ═══════════════════════════════════════════════════════════════

class TestA2ToolMessagesListFormatSplit:
    """Bug A-2: _tool_messages_list 三格式分裂。

    写入端有三种不兼容格式：
    1. base.py:158  {"type": "tool_result", "tool_name", "result", "success", "timestamp"}
    2. tool_executor.py:155 (文本模式)  {"role": "tool", "tool_call_id", "name", "content"}
    3. tool_executor.py:217 (list 模式)  {"role": "tool", "tool_call_id", "content"}（无 name）

    消费者 post_chat_pipeline.py:966, 1859 用 `tm.get("tool_name", "unknown")` 读取工具名，
    但格式 2/3 无 tool_name 字段 → 返回 "unknown" → 工具使用统计失效。

    修复: tool_executor.py 的两种写入格式添加 tool_name 字段，与 base.py 一致。
    """

    def test_text_mode_tool_message_has_tool_name(self):
        """文本模式工具消息应包含 tool_name 字段（消费者依赖此字段）。"""
        import json as _json

        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        executor = ToolExecutor(mock_agent)

        async def _execute_single_tool(name, args):
            return {"ok": True}

        executor._execute_single_tool = AsyncMock(side_effect=_execute_single_tool)

        reply = '[TOOL_CALL:search_file({"q": "test"})]'
        asyncio.run(executor._execute_from_text(reply, "搜索文件"))

        assert len(mock_agent._tool_messages_list) == 1, (
            f"应写入 1 条工具消息，实际: {mock_agent._tool_messages_list}"
        )
        msg = mock_agent._tool_messages_list[0]
        assert "tool_name" in msg, (
            f"工具消息应包含 tool_name 字段（post_chat_pipeline 用此字段统计工具使用），"
            f"实际字段: {list(msg.keys())}"
        )
        assert msg["tool_name"] == "search_file", (
            f"tool_name 应为 search_file，实际: {msg.get('tool_name')}"
        )

    def test_list_mode_tool_message_has_tool_name(self):
        """list 模式工具消息应包含 tool_name 字段。"""
        from neurova.tool_executor import ToolExecutor

        mock_agent = MagicMock()
        mock_agent._tool_messages_list = []
        executor = ToolExecutor(mock_agent)

        async def _execute_single_tool(name, args):
            return {"ok": True}

        executor._execute_single_tool = AsyncMock(side_effect=_execute_single_tool)

        tool_calls = [
            {
                "id": "call_1",
                "function": {"name": "search_file", "arguments": '{"q": "test"}'},
            }
        ]
        asyncio.run(executor.execute_text_tool_calls(tool_calls, []))

        assert len(mock_agent._tool_messages_list) == 1, (
            f"应写入 1 条工具消息，实际: {mock_agent._tool_messages_list}"
        )
        msg = mock_agent._tool_messages_list[0]
        assert "tool_name" in msg, (
            f"工具消息应包含 tool_name 字段（post_chat_pipeline 用此字段统计工具使用），"
            f"实际字段: {list(msg.keys())}"
        )
        assert msg["tool_name"] == "search_file", (
            f"tool_name 应为 search_file，实际: {msg.get('tool_name')}"
        )


# ═══════════════════════════════════════════════════════════════
# A-6: GeneticEngine 进化工具未注册 (genetic_engine.py + post_chat_pipeline.py)
# ═══════════════════════════════════════════════════════════════

class TestA6GeneticEngineNotRegistered:
    """Bug A-6: ToolGeneticEngine 进化产出的高适应度工具基因未注册到 SkillRegistry。

    现状（genetic_engine.py）:
    - ToolGeneticEngine.register_if_valid (line 444) 仅调用 add_to_population，
      把基因型塞进内部种群，**从不向 SkillRegistry 注册**
    - ToolGenotype 没有 to_skill()/to_manifest() 方法
    - post_chat_pipeline.py::_step_genetic_evolution (line 1285) 调用
      genetic_engine.evolve() 后只更新 tool_weights，**也不注册**

    后果: 进化算法产生的高适应度工具组合永远停留在遗传引擎内部种群，
    下次对话时 chat_pipeline._check_nl_synthesis 仍会因 has_tool=False 触发重复合成。

    修复模板: 仿照 evolution/skill_encapsulation.py:441-487
    AutoSkillBuilder.register_to_skill_registry，给 ToolGeneticEngine 增加
    register_to_skill_registry 方法，并在 post_chat_pipeline 桥接调用。
    """

    def test_register_to_skill_registry_method_exists(self):
        """ToolGeneticEngine 应暴露 register_to_skill_registry 方法。"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine

        engine = ToolGeneticEngine()
        assert hasattr(engine, "register_to_skill_registry"), (
            "ToolGeneticEngine 应实现 register_to_skill_registry 方法，"
            "以便将高适应度工具基因注册到 SkillRegistry，避免进化成果停留在内部种群"
        )
        assert callable(getattr(engine, "register_to_skill_registry")), (
            "register_to_skill_registry 应为可调用方法"
        )

    def test_high_fitness_genotype_registered_to_skill_registry(self):
        """高适应度 ToolGenotype 应被注册到 SkillRegistry。"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
        from neurova.skills.models import SkillSource
        from neurova.skills.registry import SkillRegistry

        # SkillRegistry 是单例，保存/恢复原状态
        skill_registry = SkillRegistry()
        saved_skills = dict(skill_registry._skills)
        skill_registry._skills.clear()

        try:
            engine = ToolGeneticEngine(validation_threshold=0.5)

            # 高适应度基因型（success_rate 高 + 含可识别工具序列）
            high_fit = ToolGenotype(
                tool_sequence=["file_read", "memory_store"],
                success_rate=0.95,
                execution_time_ms=100.0,
                reuse_count=5,
                generation=2,
            )
            # 低适应度基因型（应被过滤）
            low_fit = ToolGenotype(
                tool_sequence=["file_write"],
                success_rate=0.1,
                execution_time_ms=2000.0,
                reuse_count=0,
                generation=1,
            )
            engine.add_to_population(high_fit)
            engine.add_to_population(low_fit)

            registered_count = engine.register_to_skill_registry(skill_registry)

            assert registered_count >= 1, (
                f"至少应注册 1 个高适应度基因型，实际注册 {registered_count} 个；"
                f"种群={[g.to_dict() for g in engine.population]}"
            )

            # 验证注册的是高适应度个体
            registered_ids = set(skill_registry._skills.keys())
            assert registered_ids, "SkillRegistry 应包含注册的进化工具"

            # 检查注册的 manifest 字段
            for skill_id, (manifest, _path) in skill_registry._skills.items():
                assert manifest.source == SkillSource.LOCAL, (
                    f"进化工具 {skill_id} source 应为 LOCAL，实际: {manifest.source}"
                )
                assert manifest.config, (
                    f"进化工具 {skill_id} config 不应为空，应携带 tool_sequence/fingerprint 等元数据"
                )
                assert "tool_sequence" in manifest.config, (
                    f"进化工具 {skill_id} config 应包含 tool_sequence 字段，"
                    f"实际字段: {list(manifest.config.keys())}"
                )
        finally:
            skill_registry._skills.clear()
            skill_registry._skills.update(saved_skills)

    def test_low_fitness_genotype_not_registered(self):
        """低适应度 ToolGenotype 不应被注册到 SkillRegistry。"""
        from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype
        from neurova.skills.registry import SkillRegistry

        skill_registry = SkillRegistry()
        saved_skills = dict(skill_registry._skills)
        skill_registry._skills.clear()

        try:
            engine = ToolGeneticEngine(validation_threshold=0.5)

            low_fit = ToolGenotype(
                tool_sequence=["file_read"],
                success_rate=0.1,
                execution_time_ms=2000.0,
                reuse_count=0,
            )
            engine.add_to_population(low_fit)

            registered_count = engine.register_to_skill_registry(skill_registry)

            assert registered_count == 0, (
                f"低适应度基因型不应被注册，但注册了 {registered_count} 个"
            )
            assert len(skill_registry._skills) == 0, (
                "SkillRegistry 应为空，实际包含注册项"
            )
        finally:
            skill_registry._skills.clear()
            skill_registry._skills.update(saved_skills)
