"""
活水上下文池三目标回归测试

设计目标（用户定义）：
1. 节省 token   —— 视图只包含与当前输入语义相关的归档内容
2. 永不丢失     —— 池是无损归档：不 clear、不驱逐、不裁剪、不过期
3. 缓存命中率   —— 稳定前缀：system 块逐轮字节级一致；
                   对话窗口 append-only；调取块按 created_at 稳定排序；
                   调取块位于对话之后、当前输入之前（变化不破坏前缀缓存）
"""

import asyncio
import hashlib
from unittest.mock import MagicMock

from neurova.context.orchestrator import ContextOrchestrator


def make_orchestrator() -> ContextOrchestrator:
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


def build(orch: ContextOrchestrator, **kwargs):
    return asyncio.run(orch.build_context(**kwargs))


def fingerprint(messages) -> str:
    """上下文字节级指纹（模拟 LLM 前缀缓存键）"""
    return hashlib.sha256(repr(messages).encode()).hexdigest()


class TestLosslessArchive:
    """目标②：池是无损归档"""

    def test_pool_survives_across_builds(self):
        """build_context 不再清空池：跨轮归档持续累积"""
        orch = make_orchestrator()

        build(orch, user_input="第一轮问题", relevant_memories=[{"content": "记忆甲"}])
        size_after_r1 = len(orch.context_pool.get_contexts())
        assert size_after_r1 > 0, "归档后池不应为空"

        build(orch, user_input="第二轮问题", relevant_memories=[])
        size_after_r2 = len(orch.context_pool.get_contexts())
        assert size_after_r2 >= size_after_r1, "池在轮次间被清空/缩小，违反无损归档"

    def test_no_size_eviction(self):
        """超过 max_size 不驱逐最旧条目（永不丢失）"""
        orch = make_orchestrator()
        pool = orch.context_pool
        # max_size 默认 100：塞入 150 条不同内容
        for i in range(150):
            pool.add_context(
                __import__("neurova.context_pool", fromlist=["ContextInput"]).ContextInput(
                    source=__import__("neurova.context_pool", fromlist=["ContextSource"]).ContextSource.MEMORY,
                    content=f"独有记忆内容编号{i:03d}",
                    priority=70,
                )
            )
        contexts = pool.get_contexts()
        assert len(contexts) == 150, f"条目被驱逐：{len(contexts)}/150"
        assert any(c.content == "独有记忆内容编号000" for c in contexts), "最旧条目被驱逐，违反永不丢失"

    def test_collector_never_truncates_content(self):
        """归档条目内容永不被截断"""
        from neurova.context.collector import ContextCollector
        from neurova.context_pool import ContextInput, ContextSource

        collector = ContextCollector(max_tokens=10)  # 极小预算
        long_content = "这是一段很长的记忆内容" * 50
        collector.add_context(ContextInput(source=ContextSource.MEMORY, content=long_content, priority=70))
        collected = collector.collect()
        assert len(collected) == 1
        assert collected[0].content == long_content, "归档内容被截断，违反无损归档"

    def test_drawer_skips_instead_of_slicing(self):
        """视图层超预算条目整条跳过（不切片），内容完整保留在池中"""
        from neurova.context_pool import ContextInput, ContextSource
        from neurova.context.semantic_drawer import SemanticMatchDrawer

        drawer = SemanticMatchDrawer(max_tokens=50)
        drops = [
            ContextInput(source=ContextSource.MEMORY, content="短记忆A", priority=70),
            ContextInput(source=ContextSource.MEMORY, content="超长记忆" * 100, priority=69),
            ContextInput(source=ContextSource.MEMORY, content="短记忆B", priority=68),
        ]
        drawn = drawer.draw(drops, need="记忆")
        # 超长条目被整条跳过，两条短条目都被保留（skip-and-continue，非 break）
        contents = [d.content for d in drawn]
        assert "短记忆A" in contents and "短记忆B" in contents
        assert all("..." not in c for c in contents), "视图内容被切片截断"


class TestOnDemandRecall:
    """目标①：按最新用户语义调取，节省 token"""

    def test_irrelevant_archive_stays_out_of_view(self):
        """与当前输入无关的归档不进入视图（省 token）"""
        orch = make_orchestrator()

        # 第一轮：归档一条与"天气"无关的记忆
        build(orch, user_input="帮我写个爬虫", relevant_memories=[{"content": "用户喜欢Python爬虫编程"}])

        # 第二轮：问天气 → 爬虫记忆不应出现在视图
        ctx = build(orch, user_input="今天天气怎么样", relevant_memories=[])
        assert not any("Python爬虫" in m.get("content", "") for m in ctx), (
            "无关归档泄漏进视图，浪费 token"
        )

    def test_relevant_archive_is_recalled(self):
        """与当前输入相关的历史归档被召回（永不丢失的兑现）"""
        orch = make_orchestrator()

        # 第一轮：用户提到许昌
        history_r1 = [{"role": "user", "content": "我下周要去许昌出差"}]
        build(orch, user_input="我下周要去许昌出差", session_context=history_r1, relevant_memories=[])

        # 第二轮：窗口只保留最近一条无关消息，许昌轮次已"滚出"窗口但仍在池中
        history_r2 = [{"role": "user", "content": "今天心情不错"}, {"role": "assistant", "content": "那很好呀"}]
        ctx = build(orch, user_input="还记得我要去哪里出差吗", session_context=history_r2, relevant_memories=[])

        recalled = [m for m in ctx if "许昌" in m.get("content", "")]
        assert recalled, "相关历史轮次未被召回，违反永不丢失"
        assert any(m["content"].startswith("[历史回忆]") for m in recalled), "召回的历史轮次缺少 [历史回忆] 标记"

    def test_window_content_not_recalled_twice(self):
        """已在对话窗口中的轮次不会被调取块重复召回（去重）"""
        orch = make_orchestrator()
        history = [
            {"role": "user", "content": "许昌出差的行程安排是什么"},
            {"role": "assistant", "content": "你的许昌行程已经记录。"},
        ]
        ctx = build(orch, user_input="好的谢谢", session_context=history, relevant_memories=[])
        xuchang_count = sum(1 for m in ctx if "许昌出差的行程安排" in m.get("content", ""))
        assert xuchang_count == 1, f"窗口内容被重复召回 {xuchang_count} 次"


class TestCacheStability:
    """目标③：稳定前缀提高 LLM 缓存命中率"""

    def test_system_prefix_byte_identical_across_turns(self):
        """system 前缀跨轮字节级一致（时间注入只保留日期精度）"""
        orch = make_orchestrator()
        import time as _time

        ctx1 = build(orch, user_input="问题一", relevant_memories=[])
        _time.sleep(1.1)  # 跨过秒级边界，若注入秒级时刻前缀必变
        ctx2 = build(orch, user_input="问题二", relevant_memories=[])

        sys1 = [m for m in ctx1 if m["role"] == "system" and "[历史回忆]" not in m["content"]]
        sys2 = [m for m in ctx2 if m["role"] == "system" and "[历史回忆]" not in m["content"]]
        assert fingerprint(sys1) == fingerprint(sys2), (
            "system 前缀跨轮变化（秒级时间注入？），缓存命中率归零"
        )
        assert not any("当前时刻" in m["content"] for m in ctx1 + ctx2), "仍存在秒级时刻注入"

    def test_conversation_is_prefix_extension(self):
        """对话窗口 append-only：上一轮上下文是本轮的前缀（缓存命中前提）"""
        orch = make_orchestrator()
        history = []
        turns = [("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")]

        prev_conv = None
        for q, a in turns:
            ctx = build(orch, user_input=q, session_context=history or None, relevant_memories=[])
            conv = [m for m in ctx if m["role"] in ("user", "assistant")][:-1]  # 去掉当前输入
            if prev_conv is not None:
                assert conv[: len(prev_conv)] == prev_conv, "对话窗口非 append-only，前缀被破坏"
            prev_conv = conv
            history = history + [{"role": "user", "content": q}, {"role": "assistant", "content": a}]

    def test_recalled_block_sits_between_conversation_and_input(self):
        """调取块位于对话之后、当前输入之前：调取变化不破坏前缀缓存"""
        orch = make_orchestrator()
        history = [
            {"role": "user", "content": "我下周要去许昌出差"},
            {"role": "assistant", "content": "已记录你的许昌行程。"},
        ]
        ctx = build(orch, user_input="还记得我要去哪里吗", session_context=history, relevant_memories=[])

        roles = [m["role"] for m in ctx]
        assert roles[-1] == "user", "当前输入不在末尾"
        # 找到调取块位置（若有），必须在最后一条窗口消息之后
        recall_idx = [i for i, m in enumerate(ctx) if m.get("content", "").startswith("[历史回忆]")]
        if recall_idx:
            assert all(i > roles.index("assistant") for i in recall_idx), "调取块插在对话中间，破坏前缀缓存"

    def test_recalled_order_stable_by_created_at(self):
        """同一批调取条目按 created_at 稳定排序（分数只决定取不取）"""
        from neurova.context_pool import ContextInput, ContextSource
        from neurova.context.semantic_drawer import SemanticMatchDrawer

        drawer = SemanticMatchDrawer(max_tokens=1000)
        drops = [
            ContextInput(source=ContextSource.MEMORY, content="记忆丙", priority=50),
            ContextInput(source=ContextSource.MEMORY, content="记忆甲", priority=90),
            ContextInput(source=ContextSource.MEMORY, content="记忆乙", priority=70),
        ]
        drawn1 = drawer.draw(drops, need="记忆")
        # 第二次以不同顺序传入同一批条目（模拟池内排序变化）
        drawn2 = drawer.draw(list(reversed(drops)), need="记忆")
        order1 = [d.content for d in drawn1]
        order2 = [d.content for d in drawn2]
        assert order1 == order2 == ["记忆丙", "记忆甲", "记忆乙"], (
            f"调取顺序不稳定: {order1} vs {order2}（应按 created_at 归档顺序）"
        )
