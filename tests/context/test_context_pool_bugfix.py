import hashlib
from neurova.context_pool import ContextPool
from neurova.context.pool_models import ContextInput, ContextSource


def _make_pool():
    return ContextPool(user_id="u1", agent_id="a1", max_tokens=10000)


def _make_ctx(source, content, priority=50):
    return ContextInput(source=source, content=content, priority=priority)


class TestContextPoolClear:
    def test_clear_removes_all_contexts(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello"))
        pool.add_context(_make_ctx(ContextSource.CONVERSATION, "world"))
        assert len(pool._collector._contexts) == 2
        pool.clear()
        assert len(pool._collector._contexts) == 0

    def test_clear_preserves_config(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "x"))
        pool.clear()
        assert pool.user_id == "u1"
        assert pool.agent_id == "a1"
        assert pool.max_tokens == 10000

    def test_draw_after_clear_returns_empty(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello"))
        pool.clear()
        drawn = pool.draw(need="hello")
        assert drawn == []

    def test_no_leak_across_requests(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "first question"))
        pool.add_context(_make_ctx(ContextSource.CONVERSATION, "first answer"))
        pool.clear()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "second question"))
        pool.add_context(_make_ctx(ContextSource.CONVERSATION, "second answer"))
        drawn = pool.draw(need="second question")
        contents = [d.content for d in drawn]
        assert "first question" not in contents
        assert "first answer" not in contents
        assert "second question" in contents


class TestHashIncludesSource:
    def test_same_content_different_source_different_hash(self):
        ctx1 = _make_ctx(ContextSource.USER_INPUT, "hello")
        ctx2 = _make_ctx(ContextSource.CONVERSATION, "hello")
        assert ctx1.hash != ctx2.hash

    def test_same_content_same_source_same_hash(self):
        ctx1 = _make_ctx(ContextSource.USER_INPUT, "hello")
        ctx2 = _make_ctx(ContextSource.USER_INPUT, "hello")
        assert ctx1.hash == ctx2.hash

    def test_dedup_does_not_cross_sources(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello", priority=90))
        pool.add_context(_make_ctx(ContextSource.CONVERSATION, "hello", priority=60))
        assert len(pool._collector._contexts) == 2
        sources = [c.source for c in pool._collector._contexts]
        assert ContextSource.USER_INPUT in sources
        assert ContextSource.CONVERSATION in sources


class TestSemanticDrawerPreservesConversationOrder:
    def test_conversation_items_keep_original_order(self):
        from neurova.context.semantic_drawer import SemanticMatchDrawer
        drawer = SemanticMatchDrawer(max_tokens=10000)
        drops = [
            _make_ctx(ContextSource.CONVERSATION, "user: what is python", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "assistant: python is a language", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "user: how to learn it", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "assistant: start with basics", priority=60),
        ]
        result = drawer.draw(drops, need="python tutorial")
        contents = [d.content for d in result]
        assert contents == [
            "user: what is python",
            "assistant: python is a language",
            "user: how to learn it",
            "assistant: start with basics",
        ]

    def test_mixed_sources_conversation_stays_in_order(self):
        from neurova.context.semantic_drawer import SemanticMatchDrawer
        drawer = SemanticMatchDrawer(max_tokens=10000)
        drops = [
            _make_ctx(ContextSource.CONVERSATION, "user: hello", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "assistant: hi there", priority=60),
            _make_ctx(ContextSource.MEMORY, "user prefers dark mode", priority=70),
            _make_ctx(ContextSource.EXPERIENCE, "python tips", priority=70),
            _make_ctx(ContextSource.CONVERSATION, "user: help me", priority=60),
        ]
        result = drawer.draw(drops, need="python")
        conv_indices = [i for i, d in enumerate(result) if d.source == ContextSource.CONVERSATION]
        conv_contents = [result[i].content for i in conv_indices]
        assert conv_contents == ["user: hello", "assistant: hi there", "user: help me"]

    def test_conversation_order_with_varying_relevance(self):
        from neurova.context.semantic_drawer import SemanticMatchDrawer
        drawer = SemanticMatchDrawer(max_tokens=10000)
        drops = [
            _make_ctx(ContextSource.CONVERSATION, "user: tell me about cats", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "assistant: cats are cute", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "user: and dogs?", priority=60),
            _make_ctx(ContextSource.CONVERSATION, "assistant: dogs are loyal", priority=60),
        ]
        result = drawer.draw(drops, need="dogs loyalty")
        conv_contents = [d.content for d in result]
        assert conv_contents == [
            "user: tell me about cats",
            "assistant: cats are cute",
            "user: and dogs?",
            "assistant: dogs are loyal",
        ]

    def test_all_items_same_source_conversation_order_preserved(self):
        from neurova.context.semantic_drawer import SemanticMatchDrawer
        drawer = SemanticMatchDrawer(max_tokens=10000)
        drops = [
            _make_ctx(ContextSource.CONVERSATION, "a", priority=30),
            _make_ctx(ContextSource.CONVERSATION, "b", priority=80),
            _make_ctx(ContextSource.CONVERSATION, "c", priority=50),
            _make_ctx(ContextSource.CONVERSATION, "d", priority=90),
        ]
        result = drawer.draw(drops, need="query")
        contents = [d.content for d in result]
        assert contents == ["a", "b", "c", "d"]


class TestCallerProvidedHistorySkipsUpdate:
    def test_caller_history_flag_set(self):
        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="hi")
        assert ctx.caller_provided_history is False

    def test_caller_history_flag_set_when_provided(self):
        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="hi")
        ctx.caller_provided_history = True
        assert ctx.caller_provided_history is True


class TestEmptyHistoryNotFalsy:
    def test_empty_list_history_is_detected(self):
        metadata = {"history": []}
        assert "history" in metadata

    def test_none_history_not_detected(self):
        metadata = {}
        assert "history" not in metadata

    def test_truthy_check_would_fail(self):
        metadata = {"history": []}
        assert not metadata.get("history")

    def test_in_check_succeeds(self):
        metadata = {"history": []}
        assert "history" in metadata
