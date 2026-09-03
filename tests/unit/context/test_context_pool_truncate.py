"""
ContextPool 视图层预算测试

[无损归档] 语义变更：视图层（SemanticMatchDrawer）超预算时**整条跳过**，
绝不切片截断内容（归档永不裁剪）；容量控制只决定"取不取"，不修改内容。
原 _truncate_drop 截断路径已随无损归档设计移除。
"""

import pytest
from neurova.context_pool import ContextInput, ContextSource, ContextPool, ContextPoolUtils, SemanticMatchDrawer


class TestWholeItemSelection:
    """[无损归档] 视图层整条选取：不切片、内容原样"""

    def test_no_id_field(self):
        """ContextInput 没有 id 字段"""
        drop = ContextInput(
            source=ContextSource.MEMORY,
            content="x" * 1000,
            priority=50,
        )
        assert not hasattr(drop, 'id')

    def test_oversized_item_skipped_not_sliced(self):
        """超预算条目整条跳过，内容不被切片"""
        drawer = SemanticMatchDrawer(max_tokens=200)
        drop = ContextInput(
            source=ContextSource.MEMORY,
            content="word " * 500,
            priority=50,
            tokens=1000,
        )
        result = drawer.draw([drop], "query")
        assert result == [], "超预算条目应被整条跳过"
        assert drop.content == "word " * 500, "原条目内容被修改，违反无损归档"

    def test_skip_continues_to_smaller_items(self):
        """大条目跳过后继续尝试更小的条目（skip-and-continue，非 break）"""
        drawer = SemanticMatchDrawer(max_tokens=100)
        big = ContextInput(source=ContextSource.MEMORY, content="query big " * 100, priority=90, tokens=500)
        small1 = ContextInput(source=ContextSource.MEMORY, content="query s1 " * 10, priority=70, tokens=30)
        small2 = ContextInput(source=ContextSource.MEMORY, content="query s2 " * 10, priority=60, tokens=30)
        result = drawer.draw([big, small1, small2], "query")
        contents = [d.content for d in result]
        assert big.content not in contents, "超预算大条目不应进入视图"
        assert small1.content in contents and small2.content in contents, (
            "大条目跳过后应继续选取小条目（skip-and-continue）"
        )

    def test_metadata_preserved_on_selected_items(self):
        """被选取条目的元数据原样保留"""
        drawer = SemanticMatchDrawer(max_tokens=200)
        meta = {"key": "value", "nested": {"a": 1}}
        drop = ContextInput(
            source=ContextSource.CONVERSATION,
            content="query related content " * 5,
            priority=80,
            metadata=meta,
            tokens=50,
        )
        result = drawer.draw([drop], "query")
        assert len(result) == 1
        assert result[0].metadata == meta
        assert result[0].source == ContextSource.CONVERSATION
        assert result[0].hash == drop.hash, "选取不应改变条目指纹"

    def test_hash_never_rewritten_by_draw(self):
        """draw 不重写条目 hash（无切片即无重指纹）"""
        drawer = SemanticMatchDrawer(max_tokens=200)
        drop = ContextInput(
            source=ContextSource.MEMORY,
            content="a " * 500,
            priority=50,
            tokens=1000,
        )
        original_hash = drop.hash
        result = drawer.draw([drop], "query")
        assert result == []
        assert drop.hash == original_hash


class TestDrawTokenBudgetOverflow:
    """SemanticMatchDrawer.draw() 超预算整条跳过集成测试"""

    def test_draw_overflow_never_exceeds_budget(self):
        """超预算时 draw 整条跳过，视图总量不超预算"""
        drops = [
            ContextInput(
                source=ContextSource.SYSTEM_INSTRUCTION,
                content="You are helpful.",
                priority=100,
            ),
            ContextInput(
                source=ContextSource.MEMORY,
                content="word " * 500,
                priority=80,
                tokens=1000,
            ),
            ContextInput(
                source=ContextSource.EXPERIENCE,
                content="knowledge " * 300,
                priority=60,
                tokens=600,
            ),
        ]

        drawer = SemanticMatchDrawer(max_tokens=100)
        result = drawer.draw(drops, "helpful")
        assert isinstance(result, list)
        total = sum(
            drop.tokens if drop.tokens > 0 else ContextPoolUtils.estimate_tokens(drop.content)
            for drop in result
        )
        assert total <= 100

    def test_draw_skips_second_when_budget_exhausted(self):
        """预算耗尽后后续条目整条跳过"""
        drops = [
            ContextInput(
                source=ContextSource.SYSTEM_INSTRUCTION,
                content="query word " * 200,
                priority=100,
                tokens=400,
            ),
            ContextInput(
                source=ContextSource.MEMORY,
                content="query data " * 200,
                priority=80,
                tokens=400,
            ),
        ]

        drawer = SemanticMatchDrawer(max_tokens=500)
        result = drawer.draw(drops, "query")
        assert len(result) == 1
        assert result[0].source == ContextSource.SYSTEM_INSTRUCTION

    def test_draw_empty_drops(self):
        """空列表不报错"""
        drawer = SemanticMatchDrawer(max_tokens=100)
        result = drawer.draw([], "query")
        assert result == []


class TestContextInputConstructor:
    """ContextInput 构造函数验证"""

    def test_no_id_field(self):
        """确认 ContextInput 无 id 字段"""
        drop = ContextInput(source=ContextSource.MEMORY, content="test")
        assert not hasattr(drop, 'id')

    def test_constructor_rejects_id_kwarg(self):
        """传入 id= 应抛 TypeError"""
        with pytest.raises(TypeError):
            ContextInput(
                source=ContextSource.MEMORY,
                content="test",
                id="should_fail",
            )

    def test_all_valid_fields(self):
        """所有有效字段正常工作"""
        drop = ContextInput(
            source=ContextSource.TOOL_CALL,
            content="test content",
            priority=90,
            metadata={"test": True},
            tokens=42,
            tags=["tag1", "tag2"],
            hash="abc123",
        )
        assert drop.source == ContextSource.TOOL_CALL
        assert drop.content == "test content"
        assert drop.priority == 90
        assert drop.metadata == {"test": True}
        assert drop.tokens == 42
        assert drop.tags == ["tag1", "tag2"]
        assert drop.hash == "abc123"

    def test_auto_hash_generation(self):
        """未指定 hash 时自动生成"""
        drop = ContextInput(source=ContextSource.MEMORY, content="hello")
        assert drop.hash is not None
        assert len(drop.hash) == 64  # SHA-256 hex digest

    def test_auto_timestamp(self):
        """未指定时间时自动生成"""
        drop = ContextInput(source=ContextSource.MEMORY, content="hello")
        assert drop.created_at is not None
        assert drop.updated_at is not None
