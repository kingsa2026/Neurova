"""
多轮对话上下文时序回归测试

回归背景（截图证据）：
用户只发送了一条新消息，但 LLM 推理显示它把 4 条历史问题当作当前输入
逐条回答（"用户输入了多条内容，需要分点回应"）。

根因：
ContextOrchestrator.build_context() 曾把 USER_INPUT(优先级90) 和
CONVERSATION(优先级60) 全部放进语义池，而 ContextCollector.collect()
按 (-priority, tokens) 排序：
1. 历史中与当前/过往输入同文的 user 消息，在去重时被高优先级的
   USER_INPUT 条目吞并，以 user 角色重新出现在上下文中；
2. 全部 user 消息（90）聚在全部 assistant 消息（60）之前，
   user/assistant 交替时序被摧毁；
3. 同优先级内按 token 数排序，进一步打乱历史顺序。

修复：
对话历史与当前用户输入不再进语义池，draw() 之后按原始时序拼接，
当前输入保证是最后一条 user 消息。
"""

import asyncio
from unittest.mock import MagicMock

from neurova.context.orchestrator import ContextOrchestrator


def make_orchestrator() -> ContextOrchestrator:
    """构建使用真实字符串配置的 ContextOrchestrator（use_pool=True）"""
    mock_agent = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.user_id = "tester"
    mock_agent.agent_id = "test_agent"
    mock_agent.memory_manager = None
    mock_agent.growth_log_manager = None
    return ContextOrchestrator(mock_agent, use_pool=True)


def conv_messages(context: list) -> list:
    """提取上下文中的 user/assistant 消息（排除 system 富化内容）"""
    return [m for m in context if m["role"] in ("user", "assistant")]


class TestConversationOrdering:
    """对话历史时序回归"""

    def test_single_round_current_input_is_last_user_message(self):
        """单轮：当前输入是唯一的 user 消息且位于末尾"""
        orch = make_orchestrator()
        ctx = asyncio.run(
            orch.build_context(user_input="Q1", relevant_memories=[])
        )
        assert conv_messages(ctx) == [{"role": "user", "content": "Q1"}]
        assert ctx[-1] == {"role": "user", "content": "Q1"}

    def test_second_round_no_duplication_and_order_preserved(self):
        """第二轮：历史问答按原顺序出现一次，当前输入在末尾"""
        orch = make_orchestrator()

        history = [
            {"role": "user", "content": "为什么会返回500错误？"},
            {"role": "assistant", "content": "500 是服务器内部错误。"},
        ]
        ctx = asyncio.run(
            orch.build_context(
                user_input="请告诉我你使用的模型名称",
                relevant_memories=[],
                session_context=history,
            )
        )

        # 当前输入必须是最后一条消息
        assert ctx[-1] == {"role": "user", "content": "请告诉我你使用的模型名称"}

        conv = conv_messages(ctx[:-1])
        # 历史 user 消息只出现一次（不因 USER_INPUT/CONVERSATION 双份而重复）
        assert conv.count({"role": "user", "content": "为什么会返回500错误？"}) == 1
        # 时序：Q1 在 A1 之前
        assert conv == history

    def test_four_rounds_full_sequence(self):
        """四轮对话：每轮上下文中历史严格按时间排列，无任何重复"""
        orch = make_orchestrator()
        questions = ["为什么会返回500错误？", "请告诉我模型名称", "重新加载工具层", "持久化测试消息"]
        answers = ["A1", "A2", "A3", "A4"]
        history = []

        for i, q in enumerate(questions):
            ctx = asyncio.run(
                orch.build_context(
                    user_input=q,
                    relevant_memories=[],
                    session_context=history or None,
                )
            )
            # 当前输入是最后一条，且全上下文仅出现一次
            assert ctx[-1] == {"role": "user", "content": q}, f"round {i+1}: 当前输入不在末尾"
            assert sum(1 for m in ctx if m.get("content") == q) == 1, f"round {i+1}: 当前输入重复"

            # 历史部分与真实历史完全一致（顺序 + 无重复 + 交替）
            conv = conv_messages(ctx[:-1])
            assert conv == history, f"round {i+1}: 历史时序被破坏\n期望: {history}\n实际: {conv}"

            # 不应出现连续两条同角色消息
            for j in range(1, len(conv)):
                assert conv[j]["role"] != conv[j - 1]["role"], (
                    f"round {i+1}: 出现连续 {conv[j]['role']} 消息，时序被破坏"
                )

            history = history + [
                {"role": "user", "content": q},
                {"role": "assistant", "content": answers[i]},
            ]

    def test_system_enrichment_still_present(self):
        """修复后 system 富化内容（记忆等）仍然存在"""
        orch = make_orchestrator()
        ctx = asyncio.run(
            orch.build_context(
                user_input="Q1",
                relevant_memories=[{"content": "用户喜欢蓝色"}],
            )
        )
        system_msgs = [m["content"] for m in ctx if m["role"] == "system"]
        assert any("用户喜欢蓝色" in c for c in system_msgs), "记忆富化内容丢失"
