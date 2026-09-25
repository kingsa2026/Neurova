# -*- coding: utf-8 -*-
"""P0-3 视图层截断不得就地改写池内归档原文。

根因（三链路审计 P0-3）：
`context/collector.py` 的 `collect()` 返回的是 `self._contexts` 里的**同一批对象引用**
（注释同时声明"归档永不被裁剪"），而 `semantic_drawer.draw()` 对单条超预算条目执行
`drop.content = truncated; drop.tokens = _est(truncated)` —— 视图层的截断**直接写回
归档实体**。`pool_models.ContextInput.hash` 是"来源域 + 原文"指纹，改写 content 后
并不重算。

实测（本文件红灯即证）：归档一条 1140 字符中文原文、`drawer.max_tokens=500` 触发
截断分支后：池内现存 1015 字符、hash 与内容失配。

影响：
1. 违反池的硬契约"永不丢失"——截掉的部分**没有任何其他副本**（不同于窗口折叠，
   折叠前已按 turn 归档；截断发生在调取时，源就是它自己）；
2. 失配的 hash 让后续真正想归档原文时被 `add_context` 的 hash 去重当作"已存在"
   跳过 → 丢失变为**不可挽回**；
3. `_by_hash`/`_read_index` 仍持旧 hash，索引与内容从此不一致。

契约（修复后）：
- 归档实体**永不原地改写**：draw 返回的截断条目必须是视图副本
  （显式标注 `truncated_from`），池内原文与其 hash 保持自洽；
- 同一池连续两轮 draw 不得让池内条目累积劣化。
"""

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


def _long_chinese(content_len: int = 1140) -> ContextInput:
    return ContextInput(
        source=ContextSource.CONVERSATION,
        content="上下文压缩决定模型能否长期对话，" * (content_len // 17),
        priority=60,
        metadata={"role": "user"},
    )


class TestDrawNeverMutatesArchive:
    """draw 是视图层：它产出的只能是副本。"""

    def test_archive_survives_truncating_draw(self):
        chunk = _long_chinese()
        original_content = chunk.content
        original_hash = chunk.hash
        pool_entity = chunk  # collect() 返回同一对象引用，这里直接代表归档实体

        drawer = SemanticMatchDrawer(max_tokens=500)
        selected = drawer.draw([pool_entity], need=None)

        assert selected, "超预算条目被整条丢弃——本用例没打到截断分支"
        assert pool_entity.content == original_content, (
            f"归档实体被视图层截断改写：{len(original_content)} → {len(pool_entity.content)} 字符"
            "——截掉的部分没有任何其他副本，违反'永不丢失'硬契约"
        )
        assert ContextInput.compute_hash(pool_entity.source, pool_entity.content) == original_hash, (
            "归档实体的 hash 与其内容失配"
        )

    def test_returned_item_is_a_view_copy_not_the_archive(self):
        chunk = _long_chinese()
        original_content = chunk.content

        drawer = SemanticMatchDrawer(max_tokens=500)
        selected = drawer.draw([chunk], need=None)
        assert selected

        returned = selected[0]
        assert returned.content != original_content, "本用例前提是发生了截断"
        assert returned is not chunk, "截断产出的是视图副本，不得是归档实体本身"
        assert returned.metadata.get("truncated_from") == chunk.hash, (
            "视图副本必须显式标注来源 hash（可追溯、可重调取）"
        )

    def test_pool_entity_stays_pristine_across_repeated_draws(self):
        """连续两轮 draw 不得让池内条目累积劣化。"""
        chunk = _long_chinese()
        original_content, original_hash = chunk.content, chunk.hash

        for _ in range(3):
            drawer = SemanticMatchDrawer(max_tokens=500)
            drawer.draw([chunk], need=None)

        assert chunk.content == original_content, "多轮 draw 后归档实体被反复截短"
        assert ContextInput.compute_hash(chunk.source, chunk.content) == original_hash


class TestArchiveDedupStillWorksAfterTruncatingDraw:
    """被截断过的 hash 不得让真原文的后续归档被去重跳过（丢失不可挽回）。"""

    def test_original_content_is_accepted_by_pool_after_truncating_draw(self):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        chunk = _long_chinese()
        pool.add_context(chunk)
        before = len(pool.get_contexts())

        pool.draw(need="")  # 触发一次调取（池侧联动抽屉预算）

        # 再归档同一条原文：hash 未变，应仍被识别为"已存在"（内容也没漂移）
        from neurova.context.pool_models import ContextInput as CI, ContextSource as CS

        dup = CI(source=CS.CONVERSATION, content=chunk.content, priority=60,
                 metadata={"role": "user"})
        pool.add_context(dup)
        after = len(pool.get_contexts())
        assert after == before, (
            "原文归档后池内条数变化——归档实体已被视图层改写，hash 与内容失配"
        )
