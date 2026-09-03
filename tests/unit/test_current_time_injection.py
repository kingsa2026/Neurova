"""
TDD 测试:agent 当前时间感知 bug

 Bug 现象:用户问"现在时间",agent 回答 2025 年 4 月(训练截止日期),
           实际是 2026 年 6 月 26+。

 根因:context/orchestrator.py 的 build_system_prompt() 不注入当前时间,
      LLM 无从得知真实当前日期,只能依赖训练时的知识截止日期。

 修复:在 build_system_prompt() 末尾追加"当前时间"上下文段。
"""
import datetime
import re
from unittest.mock import MagicMock, patch

import pytest


def _make_orchestrator():
    """构造一个最小可用的 ContextOrchestrator 用于测试 build_system_prompt。

    ContextOrchestrator 的 soul/personality/config 等都是 property,从 agent_ref 代理。
    所以这里用 MagicMock 模拟 agent_ref,通过正常 __init__ 构造 orchestrator。
    context_builder 设为 None,触发 build_context 降级路径(返回 system_instructions 拼接),
    便于测试时间注入是否生效。
    """
    from neurova.context.orchestrator import ContextOrchestrator

    agent_ref = MagicMock()
    agent_ref.soul = "你是 Neurova 助手。"
    agent_ref.personality = "性格友善。"
    agent_ref.config.constitution = "遵守法律法规。"
    agent_ref.config.behavior_rules = ["礼貌回复。"]
    agent_ref.config.llm_model = "gpt-4"
    agent_ref.user_id = "test_user"
    agent_ref.agent_id = "test_agent"
    # context_builder = None 触发 build_context 降级路径
    agent_ref.context_builder = None

    # 走正常 __init__,但禁用 ContextPool 避免依赖外部组件
    orchestrator = ContextOrchestrator(agent_ref, use_pool=False)
    return orchestrator


class TestCurrentTimeInjection:
    """#T-1: build_system_prompt 必须包含当前时间上下文。"""

    def test_system_prompt_contains_current_date(self):
        """系统提示必须包含当前日期(YYYY年MM月DD日 格式)。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        # 提取 prompt 中出现的日期,应包含真实当前日期
        today = datetime.date.today()
        expected_patterns = [
            f"{today.year}年{today.month}月{today.day}日",  # 中文格式
            today.isoformat(),  # ISO 格式 YYYY-MM-DD
        ]
        assert any(p in prompt for p in expected_patterns), (
            f"build_system_prompt 未注入当前日期。"
            f"期望包含:{expected_patterns},实际 prompt:{prompt!r}"
        )

    def test_system_prompt_contains_current_weekday(self):
        """系统提示应包含当前星期(便于 LLM 回答"今天星期几")。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        weekdays_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        today_weekday = datetime.date.today().weekday()
        expected = weekdays_zh[today_weekday]
        assert expected in prompt, (
            f"build_system_prompt 未注入当前星期。"
            f"期望包含:{expected},实际 prompt:{prompt!r}"
        )

    def test_system_prompt_contains_current_time_label(self):
        """系统提示应包含明确的"当前时间"标签(避免 LLM 误解为其他日期)。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        # 应有明确的标签说明这是当前时间
        time_labels = ["当前时间", "当前日期", "Current date", "Current time", "今天的日期"]
        assert any(label in prompt for label in time_labels), (
            f"build_system_prompt 缺少'当前时间'标签。"
            f"期望包含:{time_labels} 之一,实际 prompt:{prompt!r}"
        )

    def test_system_prompt_time_is_not_hardcoded_2025(self):
        """系统提示中的日期不应是硬编码的 2025 年(防止回归到训练截止日期)。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        today = datetime.date.today()
        # 如果当前是 2025 年,此测试自动跳过(不适用)
        if today.year == 2025:
            pytest.skip("当前系统时间就是 2025 年,此测试不适用")
        # 当前不是 2025 年,prompt 不应误报 2025
        assert "2025年4月" not in prompt, (
            f"build_system_prompt 仍包含硬编码 2025年4月。prompt:{prompt!r}"
        )


class TestTimeInjectionFormat:
    """#T-2: 时间注入格式稳定可解析。"""

    def test_time_section_is_identifiable(self):
        """时间注入段应有清晰边界(便于后续维护 + 压缩器识别)。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        # 应有形如 ## 当前时间 或 ## 当前日期 的 section header
        section_patterns = [r"##\s*当前时间", r"##\s*当前日期", r"##\s*Current", r"当前时间[:：]"]
        assert any(re.search(p, prompt) for p in section_patterns), (
            f"build_system_prompt 缺少时间 section header。"
            f"期望匹配:{section_patterns},实际 prompt:{prompt!r}"
        )

    def test_time_injection_does_not_break_existing_sections(self):
        """时间注入不应破坏既有的 soul/personality/constitution/behavior_rules section。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("工具描述")
        assert "Neurova 助手" in prompt, "soul 段丢失"
        assert "性格友善" in prompt, "personality 段丢失"
        assert "遵守法律法规" in prompt, "constitution 段丢失"
        assert "礼貌回复" in prompt, "behavior_rules 段丢失"
        assert "工具描述" in prompt, "tools_desc 段丢失"

    def test_time_injection_works_without_tools_desc(self):
        """无 tools_desc 时也应注入时间(tools_desc 是可选的)。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("")
        today = datetime.date.today()
        assert f"{today.year}年{today.month}月" in prompt, (
            f"无 tools_desc 时未注入时间。prompt:{prompt!r}"
        )


class TestTimeInjectionWithTools:
    """#T-3: 时间注入与工具描述共存。"""

    def test_time_injection_with_tools_desc(self):
        """同时有 tools_desc 时,时间注入仍正常。"""
        orch = _make_orchestrator()
        prompt = orch.build_system_prompt("## 可用工具\n- weather: 查天气")
        today = datetime.date.today()
        assert f"{today.year}年{today.month}月" in prompt
        assert "weather" in prompt


class TestTimeInjectionDeterminism:
    """#T-4: 时间注入是动态的(每次调用反映当前时间)。"""

    def test_time_changes_between_calls(self):
        """多次调用应反映调用时刻(不是构造时刻的快照)。"""
        orch = _make_orchestrator()

        # 第一次调用
        prompt1 = orch.build_system_prompt("")
        today = datetime.date.today()

        # 模拟时间前进 100 天(用 patch)
        future_date = today + datetime.timedelta(days=100)
        with patch("neurova.context.orchestrator.datetime") as mock_dt:
            mock_dt.date.today.return_value = future_date
            mock_dt.datetime.now.return_value = datetime.datetime.combine(
                future_date, datetime.time(12, 0, 0)
            )
            prompt2 = orch.build_system_prompt("")

        # 两次调用的日期应不同
        assert f"{today.year}年{today.month}月{today.day}日" in prompt1
        assert f"{future_date.year}年{future_date.month}月{future_date.day}日" in prompt2
        assert prompt1 != prompt2, (
            f"时间注入不是动态的,两次调用结果相同。\n"
            f"prompt1:{prompt1!r}\nprompt2:{prompt2!r}"
        )


class TestBuildContextTimeInjection:
    """#T-5: build_context(实际 chat 流程调用的路径)也必须注入当前时间。

    Bug T-1 根因:build_system_prompt() 只是工具方法,chat_pipeline 实际调用 build_context()。
    早期修复只改了 build_system_prompt,build_context 路径未注入时间,LLM 仍说"没有系统时间工具"。
    """

    @pytest.mark.asyncio
    async def test_build_context_injects_current_time(self):
        """build_context 返回的 messages 中必须包含当前时间。"""
        orch = _make_orchestrator()

        # build_context 是 async 方法,需要 await
        messages = await orch.build_context(
            user_input="现在几点了",
            relevant_memories=None,
            session_context=None,
            crystallized_patterns=None,
        )

        # 把所有 message content 拼接起来检查
        all_content = "\n".join(
            m.get("content", "") for m in messages if isinstance(m, dict)
        )

        today = datetime.date.today()
        expected_date = f"{today.year}年{today.month}月{today.day}日"
        assert expected_date in all_content, (
            f"build_context 未注入当前时间。\n"
            f"期望包含:{expected_date}\n"
            f"实际 messages:{messages!r}"
        )

    @pytest.mark.asyncio
    async def test_build_context_time_has_section_header(self):
        """build_context 注入的时间应有 ## 当前时间 section header(便于 LLM 识别)。"""
        orch = _make_orchestrator()
        messages = await orch.build_context(
            user_input="今天星期几",
            relevant_memories=None,
            session_context=None,
            crystallized_patterns=None,
        )
        all_content = "\n".join(
            m.get("content", "") for m in messages if isinstance(m, dict)
        )
        assert "## 当前时间" in all_content, (
            f"build_context 注入的时间缺少 ## 当前时间 section header。\n"
            f"实际 messages:{messages!r}"
        )

    @pytest.mark.asyncio
    async def test_build_context_time_includes_weekday(self):
        """build_context 注入的时间应包含星期(便于回答"今天星期几")。"""
        orch = _make_orchestrator()
        messages = await orch.build_context(
            user_input="今天星期几",
            relevant_memories=None,
            session_context=None,
            crystallized_patterns=None,
        )
        all_content = "\n".join(
            m.get("content", "") for m in messages if isinstance(m, dict)
        )
        weekdays_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        today_weekday = datetime.date.today().weekday()
        expected = weekdays_zh[today_weekday]
        assert expected in all_content, (
            f"build_context 未注入星期。期望:{expected}\n实际:{all_content!r}"
        )
