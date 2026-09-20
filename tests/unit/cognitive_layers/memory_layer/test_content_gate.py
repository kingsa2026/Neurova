"""011 · 记忆写入内容门 —— `remember()` 归一化去重（红绿灯 TDD）。

根因：`remember()` 全路径无 dedup / 相似度 / 冲突判断，任何调用都直达
`return mem_id`，于是同一句无信息复述反复成行（生产 EKB 实测同一 context 最高 7 行）。

落定契约（本文件逐条锁定）：
1. 身份 = 作用域三元组 + `normalized_key(content)`；命中既有活跃记忆 ⇒ 返回既有 id，
   **不再新增行**（语义择一：首条为准 + 刷新 updated_at，见 `remember` docstring）；
2. 反向锁：语义不同的近长输入各自成行（折叠口径只吃大小写/全半角/标点/空白/说话人前缀）；
3. 空键不坍缩：归一后为空的输入（纯空白/纯标点）无内容身份，各自成行 —— 不得共用一个桶；
4. 作用域隔离：A 用户与 B 用户的同一句互不去重；
5. 显式 `id=` 是身份寻址写入（M-25 自定义 id / 恢复路径），内容门不得改道；
6. 已遗忘（软遗忘）的旧行不充当门拦截目标 —— 重新学到同一句必须能再落一行。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

SENTENCE = "用户偏好深色模式。"
VARIANTS = [
    "用户偏好深色模式",
    " 用户偏好深色模式 ",
    "用户偏好深色模式!",
    "用户偏好深色模式。",
    "用户偏好深色模式？",
]


@pytest.fixture()
def mgr_factory(tmp_path):
    """同一 tmp 目录内构造 MemoryManager；持久库按目录共享，可按需重开验证重启。"""
    made = []

    def _make(user_id: str = "default", agent_id: str = "gate-agent") -> MemoryManager:
        m = MemoryManager(
            db_path=str(tmp_path / "mem.db"),
            agent_id=agent_id,
            neuser_id="neu",
            user_id=user_id,
            enable_buffer=False,
        )
        made.append(m)
        return m

    yield _make
    for m in made:
        m.close()


def _persist_rows(mgr: MemoryManager, tmp_path):
    conn = sqlite3.connect(str(tmp_path / "neurova_memories_persist.db"))
    try:
        return conn.execute("SELECT id, content FROM memories").fetchall()
    finally:
        conn.close()


class TestSameSentenceSingleRow:
    def test_five_normalizing_variants_one_row(self, mgr_factory, tmp_path):
        mgr = mgr_factory()
        ids = [mgr.remember(text, category="user_preference") for text in VARIANTS]

        assert len(set(ids)) == 1, f"命中内容门必须返回既有 id，实际 {ids}"
        assert len(mgr.get_all_memories()) == 1, "同一句归一化后相同的输入不得存成多行"
        assert len(_persist_rows(mgr, tmp_path)) == 1, "持久层同样只有一行"

    def test_remember_count_stats_not_inflated_by_duplicates(self, mgr_factory):
        mgr = mgr_factory()
        for text in VARIANTS:
            mgr.remember(text)
        assert mgr._stats["remember_count"] == 1

    def test_gate_holds_across_restart(self, mgr_factory, tmp_path):
        first = mgr_factory()
        for text in VARIANTS[:3]:
            first.remember(text)
        assert len(_persist_rows(first, tmp_path)) == 1

        reopened = mgr_factory()
        again = reopened.remember(VARIANTS[4])
        assert len(_persist_rows(reopened, tmp_path)) == 1, f"重启后同一句不得再开一行：{again}"

    def test_repeated_confirmation_refreshes_updated_at(self, mgr_factory):
        """被反复确认的事实不得因去重而比改动前更早衰减掉。"""
        mgr = mgr_factory()
        mid = mgr.remember(SENTENCE)
        stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
        mgr._memories[mid].updated_at = stale
        again = mgr.remember(SENTENCE)

        assert again == mid
        assert mgr._memories[mid].updated_at > stale, "命中门必须刷新 updated_at（再确认语义）"


class TestNoOverMerge:
    def test_semantically_different_inputs_stay_distinct(self, mgr_factory):
        mgr = mgr_factory()
        mgr.remember("用户住在北京")
        mgr.remember("用户住在上海")
        assert len(mgr.get_all_memories()) == 2, "长度相近但语义不同的输入不得误合并"

    def test_empty_and_punctuation_only_inputs_do_not_collapse(self, mgr_factory):
        mgr = mgr_factory()
        ids = [mgr.remember(text) for text in ["", "   ", "。！？", ""]]
        assert len(set(ids)) == 4, f"归一后为空的输入不得坍缩进同一个桶，实际 {ids}"
        assert len(mgr.get_all_memories()) == 4

    def test_scope_isolation_defeats_cross_user_dedup(self, mgr_factory, tmp_path):
        """内容门走作用域三元组：A 用户的同一句不得吃掉 B 用户的行。

        业务 id 跨作用域可同值（M-25 由作用域限定行 id 承载区分），故判据落在
        持久层行数与各作用域视图上，不看返回 id。
        """
        a = mgr_factory(user_id="userA")
        b = mgr_factory(user_id="userB")
        a.remember(SENTENCE)
        b.remember(SENTENCE)
        assert len(_persist_rows(a, tmp_path)) == 2, "跨用户同一句各自成行（三层隔离优先于内容门）"
        assert len(a._scoped_memories()) == 1
        assert len(b._scoped_memories()) == 1

    def test_explicit_id_write_bypasses_gate(self, mgr_factory):
        """显式 id 是身份寻址写入，内容门不得把它改道到既有行。"""
        mgr = mgr_factory()
        mgr.remember(SENTENCE)
        mid = mgr.remember(SENTENCE, id="custom-anchor-1")
        assert mid == "custom-anchor-1"
        assert len(mgr.get_all_memories()) == 2


class TestForgottenDoesNotBlock:
    def test_soft_forgotten_key_is_not_a_dedup_target(self, mgr_factory):
        """链 B 的 supersede 语义：软遗忘旧行后，同一句必须能重新落库。"""
        mgr = mgr_factory()
        old = mgr.remember(SENTENCE)
        assert mgr.forget(old, soft=True) is True
        new = mgr.remember(SENTENCE)
        assert new != old, "内容门不得把新学到的事实改道回已遗忘的旧行"

    def test_hard_delete_frees_the_key(self, mgr_factory):
        mgr = mgr_factory()
        old = mgr.remember(SENTENCE)
        mgr.forget(old, soft=False)
        assert mgr.remember(SENTENCE) != old


class TestClassificationDimensionKeepsRows:
    """门键含读取侧据以区分行的分类维度——同文本不同维度是两条记忆。"""

    def test_same_text_different_origin_stays_distinct(self, mgr_factory):
        mgr = mgr_factory()
        mgr.remember("Neurova 是一个 AI 助手平台", origin="untrusted")
        mgr.remember("Neurova 是一个 AI 助手平台", origin="owner")
        assert len(mgr.get_all_memories()) == 2, "origin 是检索降权依据，合并等于丢一条"

    def test_same_text_different_category_stays_distinct(self, mgr_factory):
        mgr = mgr_factory()
        mgr.remember("喜欢深色模式", category="user_preference")
        mgr.remember("喜欢深色模式", category="knowledge")
        assert len(mgr.get_all_memories()) == 2, "recall(category=...) 按分类过滤，两行各有视图"

    def test_same_text_different_memory_type_stays_distinct(self, mgr_factory):
        mgr = mgr_factory()
        mgr.remember("先抓取再总结", memory_type="semantic")
        mgr.remember("先抓取再总结", memory_type="episodic")
        assert len(mgr.get_all_memories()) == 2, "memory_type 是类型隔离依据，不得被内容门吃掉"


class TestIndexFollowsEdit:
    def test_content_edit_moves_the_gate_key(self, mgr_factory):
        """`update_memory` 改内容后门键必须跟着走：旧键让开、新键接上。"""
        mgr = mgr_factory()
        mid = mgr.remember("用户住在北京")
        assert mgr.remember("用户住在北京") == mid

        assert mgr.update_memory(mid, content="用户住在上海") is True
        assert mgr.remember("用户住在上海。") == mid, "改后的内容要继续进门，不得另开一行"
        assert mgr.remember("用户住在北京") != mid, "旧键让开后，原句可重新学成一行"
        assert len(mgr.get_all_memories()) == 2


class TestRetrievalSide:
    def test_recall_returns_single_deduped_hit(self, mgr_factory):
        mgr = mgr_factory()
        for text in VARIANTS:
            mgr.remember(text)
        hits = mgr.recall("用户偏好深色模式", limit=10)
        assert len(hits) == 1, f"检索面不得被同源重复行占位，实际 {len(hits)} 条"
