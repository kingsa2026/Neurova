"""011 · 经验写入内容门 —— EKB `add_experience_record` 归一化去重键（红绿灯 TDD）。

根因（生产实测）：去重键是 `context`/`result` 的**完全相同 JSON 元组**，而
`result.reply_excerpt` 每次都是新的 LLM 回复 ⇒ 键必然不同，于是同一句"你好"
连存 7 行（`data/experience_knowledge.db` id 16/17/73/74/75/87/88）。

落定契约（本文件逐条锁定）：
1. 身份 = `(agent_id, skill_name, success, content_key)`，`content_key` 由
   `normalized_payload_key(context)` 得出（NFKC + 小写 + 去标点/空白）；
   **`result` 退出身份键** —— 回复文本是证据内容，不是身份；
2. 合并语义择一写明：命中 ⇒ 保留既有行、`seen_count` +1、`result`/`timestamp`
   刷新为最新一次（last-write-wins），返回既有 id；
3. `success` 仍在键内：同问一成一败是两条语义不同的经验，不合并（失败证据
   必须能与成功证据并存，供 006/007 的证伪回路读取）；
4. 空键不坍缩：归一后为空的 context（无字符串叶子/纯标点）不参与去重；列内以
   `''` 表示"无身份"，`NULL` 只留给未回填的存量行；
5. 存量行在 `_migrate_schema` 时回填 `content_key`，因此旧行同样进门，
   不会在升级后再开一行。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from neurova.skills.experience_knowledge_base import ExperienceRecord


@pytest.fixture()
def ekb(tmp_path):
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

    db = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    yield db
    db.close()


def _rows(ekb):
    conn = sqlite3.connect(ekb._db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, skill_name, success, context, result, seen_count, content_key "
            "FROM experience_records ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _exp(reply: str, user_input: str = "你好", success: bool = True) -> ExperienceRecord:
    return ExperienceRecord(
        skill_name="chat",
        context={"user_input": user_input},
        result={"reply_excerpt": reply},
        success=success,
    )


VARIANT_INPUTS = ["你好", " 你好 ", "你好!", "你好。", "你　好"]


class TestSameInputSingleRow:
    def test_five_input_variants_one_row(self, ekb):
        ids = [
            ekb.add_experience_record("chat", _exp(f"回复{i}", user_input=text), agent_id="a1")
            for i, text in enumerate(VARIANT_INPUTS)
        ]
        assert len(set(ids)) == 1, f"归一化后同一句必须返回既有 id，实际 {ids}"
        rows = _rows(ekb)
        assert len(rows) == 1, f"同一句无信息复述不得反复成行，实际 {len(rows)} 行"
        assert rows[0]["seen_count"] == 5, "合并必须留下重复计数（1 行 + 计数 +4）"

    def test_latest_reply_wins_on_merge(self, ekb):
        """命中既有行时刷新 result：首条是报错回复不能被永久钉死。"""
        ekb.add_experience_record("chat", _exp("[LLM Error] boom"), agent_id="a1")
        ekb.add_experience_record("chat", _exp("你好呀，有什么可以帮你"), agent_id="a1")
        stored = json.loads(_rows(ekb)[0]["result"])
        assert stored["reply_excerpt"] == "你好呀，有什么可以帮你"

    def test_row_to_dict_exposes_seen_count(self, ekb):
        ekb.add_experience_record("chat", _exp("r1"), agent_id="a1")
        ekb.add_experience_record("chat", _exp("r2"), agent_id="a1")
        rec = ekb.get_experience_records(skill_name="chat", agent_id="a1")[0]
        assert rec["seen_count"] == 2


class TestIdentityKeyDiscriminates:
    def test_failure_and_success_never_merge(self, ekb):
        """同问一成一败是两条经验（失败证据必须能与成功证据并存）。"""
        ekb.add_experience_record("chat", _exp("成", success=True), agent_id="a1")
        ekb.add_experience_record("chat", _exp("败", success=False), agent_id="a1")
        assert len(_rows(ekb)) == 2

    def test_semantically_different_inputs_stay_distinct(self, ekb):
        ekb.add_experience_record("chat", _exp("r1", user_input="帮我查北京天气"), agent_id="a1")
        ekb.add_experience_record("chat", _exp("r2", user_input="帮我查上海天气"), agent_id="a1")
        assert len(_rows(ekb)) == 2, "长度相近、语义不同的输入不得误合并"

    def test_scope_still_isolated_by_agent_and_skill(self, ekb):
        ekb.add_experience_record("chat", _exp("r1"), agent_id="agent-a")
        ekb.add_experience_record("chat", _exp("r2"), agent_id="agent-b")
        ekb.add_experience_record("translate", _exp("r3"), agent_id="agent-a")
        rows = _rows(ekb)
        assert len(rows) == 3, f"跨 agent / 跨技能不得被内容门合并，实际 {len(rows)} 行"

    def test_empty_context_inputs_do_not_collapse(self, ekb):
        ids = [
            ekb.add_experience_record(
                "chat",
                ExperienceRecord(skill_name="chat", context=ctx, result={"r": i}, success=True),
                agent_id="a1",
            )
            for i, ctx in enumerate([{}, {"user_input": ""}, {"page": 3}, {"user_input": "。！"}])
        ]
        assert len(set(ids)) == 4, f"无内容身份的写入不得坍缩进同一个桶，实际 {ids}"
        assert all(r["content_key"] == "" for r in _rows(ekb)), "空身份以 '' 落列（NULL 只表示未回填）"


class TestRetrievalSide:
    def test_similar_search_not_crowded_by_duplicates(self, ekb):
        for i, text in enumerate(VARIANT_INPUTS):
            ekb.add_experience_record("chat", _exp(f"回复{i}", user_input=text), agent_id="a1")
        ekb.add_experience_record(
            "chat", _exp("无关经验", user_input="帮我写一份周报"), agent_id="a1"
        )
        hits = ekb.find_similar_experiences(
            skill_name="chat", context={"user_input": "你好"}, agent_id="a1", limit=5
        )
        assert len(hits) == 1, f"检索面必须只见一条去重后的经验，实际 {len(hits)} 条"


class TestLegacyRowsBackfilled:
    def test_pre_migration_row_joins_the_gate(self, tmp_path):
        """存量行（无 content_key 列时代写入）在 _migrate_schema 回填后同样进门。"""
        from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

        path = str(tmp_path / "legacy.db")
        first = ExperienceKnowledgeBase(db_path=path)
        legacy_id = first.add_experience_record("chat", _exp("旧回复"), agent_id="a1")
        first.close()

        # 模拟升级前落库：抹掉身份键，等价于老版本写入的行
        conn = sqlite3.connect(path)
        conn.execute("UPDATE experience_records SET content_key = NULL")
        conn.commit()
        conn.close()

        reopened = ExperienceKnowledgeBase(db_path=path)
        try:
            again = reopened.add_experience_record("chat", _exp("新回复"), agent_id="a1")
            rows = _rows(reopened)
            assert again == legacy_id, "回填后旧行必须继续充当身份，不得另开一行"
            assert len(rows) == 1
            assert rows[0]["seen_count"] == 2
        finally:
            reopened.close()
