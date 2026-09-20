"""006 · 回写通路 —— 知道本轮注入了哪几条经验，并把事后成败写回去（红绿灯 TDD）。

根因：`experience_knowledge_base.py` 原本全文零条 `UPDATE`——经验只写不改，
一条经验被采纳后到底是帮了还是坏了，库里永远没有证据；检索侧想降权也无处可降。

落定契约：
1. 三条新列：`injected_count`（命中次数）、`last_injected_at`（最近使用）、
   `adoption_outcome`（采纳后结果）。`adoption_outcome IS NULL` ＝ **从未回写**，
   `'unevidenced'` ＝ 注入过但这轮没有客观回执（002 的第三态）—— 两者必须分得开（D1）；
2. 注入侧带身份：`chat_pipeline._retrieve_ekb_experience` 把 EKB 行 id 写进
   `ctx.experience_items`，并经 `turn_context` 立起本轮注入集；`growth_lesson`
   条目住在另一张表，不得混进回写 id 集；
3. 回合结束按身份集回写，成败取 002 之后的真实语义；
4. 反向锁：本轮未注入任何经验 ⇒ UPDATE 数必须为 0，
   不得把"没注入"写成"采纳后失败"。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from neurova.core.turn_context import (
    get_turn_injected_experiences,
    set_turn_injected_experiences,
)
from neurova.skills.experience_knowledge_base import ExperienceRecord


@pytest.fixture(autouse=True)
def _clean_turn_injection_set():
    """本轮注入集是 ContextVar，测试线程内不自动隔离 —— 前后都清空。"""
    set_turn_injected_experiences(None)
    yield
    set_turn_injected_experiences(None)


@pytest.fixture()
def ekb(tmp_path):
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

    db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    yield db
    db.close()


def _seed(db, user_input: str = "把报告导出成 PDF", success: bool = True) -> int:
    return db.add_experience_record(
        "pdf_export",
        ExperienceRecord(
            skill_name="pdf_export",
            context={"user_input": user_input},
            result={"reply_excerpt": "已导出"},
            success=success,
        ),
        agent_id="agent-06",
    )


def _adoption_row(db_path: str, rid: int) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(
            "SELECT injected_count, last_injected_at, adoption_outcome "
            "FROM experience_records WHERE id = ?", (rid,)
        ).fetchone())
    finally:
        conn.close()


class TestAdoptionColumns:
    def test_new_row_starts_as_never_written_back(self, ekb):
        rid = _seed(ekb)
        row = _adoption_row(ekb._db_path, rid)
        assert row["injected_count"] == 0
        assert row["last_injected_at"] is None
        assert row["adoption_outcome"] is None, "NULL 专用于'从未回写'"

    def test_unevidenced_is_distinct_from_never_written_back(self, ekb):
        """D1：'注入过但没回执'与'从没注入过'在读侧必须分得开。"""
        rid = _seed(ekb)
        ekb.record_injection_adoption([rid], None)
        assert _adoption_row(ekb._db_path, rid)["adoption_outcome"] == "unevidenced"


class TestRecordInjectionAdoption:
    def test_failed_turn_marks_the_row_worse(self, ekb):
        rid = _seed(ekb)
        updated = ekb.record_injection_adoption([rid], False)
        row = _adoption_row(ekb._db_path, rid)
        assert updated == 1
        assert row["adoption_outcome"] == "failure", "客观失败必须回写成 failure"
        assert row["injected_count"] == 1
        assert row["last_injected_at"], "回写必须带上最近使用时间"

    def test_success_turn_marks_the_row_better(self, ekb):
        rid = _seed(ekb)
        ekb.record_injection_adoption([rid], True)
        assert _adoption_row(ekb._db_path, rid)["adoption_outcome"] == "success"

    def test_repeated_injections_accumulate(self, ekb):
        rid = _seed(ekb)
        ekb.record_injection_adoption([rid], True)
        ekb.record_injection_adoption([rid], False)
        row = _adoption_row(ekb._db_path, rid)
        assert row["injected_count"] == 2, "命中次数按注入累计，不按首次覆盖"
        assert row["adoption_outcome"] == "failure", "结果位反映最近一次采纳"

    def test_empty_injection_set_writes_nothing(self, ekb):
        """反向锁：没注入就不许写"采纳后失败"。"""
        rid = _seed(ekb)
        assert ekb.record_injection_adoption([], False) == 0
        assert ekb.record_injection_adoption(None, True) == 0
        row = _adoption_row(ekb._db_path, rid)
        assert row["adoption_outcome"] is None and row["injected_count"] == 0

    def test_unknown_ids_are_not_counted_as_writes(self, ekb):
        rid = _seed(ekb)
        updated = ekb.record_injection_adoption([rid, 999999], True)
        assert updated == 1, "回写数只统计真实存在的行"


class TestTurnChain:
    """端到端：注入身份 → 本轮客观成败 → 回写，全走生产链（001 探针 + 单例库）。"""

    def test_injected_row_is_marked_by_a_failing_turn(self, experience_probe, tool_records):
        from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

        rid = _seed(get_experience_knowledge_base())
        set_turn_injected_experiences([rid])
        experience_probe.run_turn(tool_messages=[
            tool_records.result("pdf_export", False, result="导出失败：模板缺失"),
        ])
        row = _adoption_row(str(experience_probe.db_path), rid)
        assert row["adoption_outcome"] == "failure"
        assert row["injected_count"] == 1

    def test_turn_without_injection_writes_zero_rows(self, experience_probe, tool_records):
        from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

        rid = _seed(get_experience_knowledge_base())
        set_turn_injected_experiences(None)
        result = experience_probe.run_turn(tool_messages=[
            tool_records.result("pdf_export", False),
        ])
        step_data = experience_probe.pipeline._step_results[-1].data
        assert step_data["adoption_writeback"] == 0, "反向锁：本轮未注入 ⇒ UPDATE 数为 0"
        assert _adoption_row(str(experience_probe.db_path), rid)["adoption_outcome"] is None
        assert result["rows"], "对照：本轮经验本身仍照常入库（回写门不影响写入）"

    def test_no_objective_receipt_marks_unevidenced(self, experience_probe, tool_records):
        """只有 tool_call 记录（无回执）⇒ 注入条目记 unevidenced，不记成功。"""
        from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

        rid = _seed(get_experience_knowledge_base())
        set_turn_injected_experiences([rid])
        experience_probe.run_turn(tool_messages=[tool_records.call("pdf_export")])
        assert _adoption_row(
            str(experience_probe.db_path), rid
        )["adoption_outcome"] == "unevidenced"

    def test_step_data_reports_writeback_count(self, experience_probe, tool_records):
        from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

        rid = _seed(get_experience_knowledge_base())
        set_turn_injected_experiences([rid])
        experience_probe.run_turn(tool_messages=[tool_records.result("pdf_export", True)])
        assert experience_probe.pipeline._step_results[-1].data["adoption_writeback"] == 1


class TestInjectionIdentityPlumbing:
    """注入侧必须带身份：EKB 行 id 进 ctx 与本轮注入集。"""

    def _pipeline(self, agent_id: str = "agent-06", queue=None):
        from neurova.agent.chat_pipeline import ChatPipeline

        agent = SimpleNamespace(
            config=SimpleNamespace(agent_id=agent_id),
            question_queue_manager=queue,
        )
        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent
        return pipeline

    def _ctx(self, user_input: str, items=None):
        return SimpleNamespace(
            user_input=user_input, experience_items=list(items or []), metadata={},
        )

    @pytest.fixture()
    def patched_ekb(self, ekb, monkeypatch):
        from neurova.skills import experience_knowledge_base as ekb_mod

        monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: ekb)
        return ekb

    def test_ekb_hits_carry_row_ids_and_register_the_turn(self, patched_ekb):
        rid = _seed(patched_ekb, user_input="把报告导出成 PDF")
        pipeline = self._pipeline()
        ctx = self._ctx("把报告导出成 PDF")
        pipeline._retrieve_ekb_experience(ctx)

        assert ctx.experience_items, "检索必须命中种子经验"
        assert ctx.experience_items[0]["id"] == rid, "条目要带得回写的行 id"
        # 007：注入侧优先级吃的就是这格证据，检索到了却没带出来 ⇒ 永远回落基线
        assert ctx.experience_items[0]["adoption_outcome"] is None
        assert ctx.experience_items[0]["similarity_score"] > 0
        assert get_turn_injected_experiences() == [rid], "本轮注入集必须立起来"

    def test_growth_lessons_do_not_enter_the_writeback_set(self, patched_ekb):
        """growth_lesson 住在 growth_lessons 表，混进 id 集会回写到错误的行。"""
        rid = _seed(patched_ekb, user_input="把报告导出成 PDF")
        queue = SimpleNamespace(retrieve_lessons=lambda db, query, agent_id, user_id: [{
            "question_id": "q-1", "revision": 1, "question": "怎么导出", "answer": "用 pdf_export",
        }])
        pipeline = self._pipeline(queue=queue)
        ctx = self._ctx("把报告导出成 PDF")
        ctx.metadata = {"user_id": "u1"}
        pipeline._retrieve_ekb_experience(ctx)

        lessons = [i for i in ctx.experience_items if i.get("source") == "growth_lesson"]
        assert lessons, "对照：growth_lesson 条目确实进来了（否则本断言无意义）"
        assert "id" not in lessons[0], "growth_lesson 不得伪装成可回写的经验行"
        assert get_turn_injected_experiences() == [rid], "回写集里只该有 EKB 行 id"

    def test_no_hits_clears_the_turn_set(self, patched_ekb):
        rid = _seed(patched_ekb, user_input="完全不同的问题")
        pipeline = self._pipeline()
        set_turn_injected_experiences([rid])
        ctx = self._ctx("一句检索不到的话")
        pipeline._retrieve_ekb_experience(ctx)
        assert get_turn_injected_experiences() == [], "无命中必须清场，不得沿用上一轮注入集"
