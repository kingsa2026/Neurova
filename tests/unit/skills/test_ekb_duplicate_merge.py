# -*- coding: utf-8 -*-
"""存量重复行清理（去重门 NULL 失效期的遗产）——`EKB.mergeDuplicateRecords`。

来历：2026-11-12 活体验证现场抓获的去重门 NULL bug（`success = ?` 绑 NULL 永不
成立）在生产库攒下 300+ 行同句 "hello"。门修好（`success IS ?`）后不再新增，但
存量还在：检索面对 359 行同问打同一串分，纯噪声。本方法按**与去重门完全相同的
身份与合并语义**（教义第 6 条：合并口径只有一处定义）做一次性清理：

- 身份 = (agent_id, skill_name, success, content_key)（content_key 空串不参与——
  与写入门同口径：算不出内容身份的行各自成行）；
- 保留组内最旧行，seen_count 取**和**（重复次数是事实，不许丢）；
- result/timestamp 刷新为最新一次（与写入门合并路径同语义）；
- evidence_state 按 evidenced 优先、verifiability_state 按非 unchecked 优先
  （信息不回退）；
- adoption_outcome / operator_disposition：保留行非空则保留，否则从被并行继承
  最新非空值（人工处置与采纳结论是资产，不许因合并蒸发）。

幂等：合并后同身份只剩一行，第二次调用零删除。
"""
from __future__ import annotations

import json

import pytest

QUESTION = "清理验证探针问题QQ77"


def _ekb(tmp_path):
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _legacy_dup(ekb, user_input, *, success=None, structure="legacy", skill="chat",
                evidence_state="unevidenced", verifiability="unchecked",
                adoption=None, disposition=None, created="2026-11-12T10:00:00+00:00",
                agent="default", seen=1):
    """按存量形态直插一行（同问同 content_key——生产 hello 行的真实形态）。

    `structure` 只区分 result 文本与插入顺序，不进 context：纯对话轮的
    structure_key 恒空串（`_turn_structure_key` 对无步轮返回 ""），生产 359 行
    "hello" 的 content_key 因此全同。
    """
    with ekb._lock:
        cur = ekb._conn.cursor()
        cur.execute(
            """
            INSERT INTO experience_records
                (skill_name, context, result, success, timestamp, feedback,
                 agent_id, session_id, confidence_score, tags, created_at,
                 content_key, seen_count, evidence_state, verifiability_state,
                 adoption_outcome, operator_disposition)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, '[]', ?, ?, ?, ?, ?,
                    ?, ?)
            """,
            (skill,
             json.dumps({"user_input": user_input},
                        ensure_ascii=False, sort_keys=True),
             json.dumps({"reply_excerpt": f"r-{structure}"}, ensure_ascii=False),
             success, created, user_input[:100], agent,
             created, json.dumps({"user_input": user_input},
                                 ensure_ascii=False, sort_keys=True),
             seen, evidence_state, verifiability, adoption, disposition),
        )
        return cur.lastrowid


def _row(ekb, record_id):
    with ekb._lock:
        cur = ekb._conn.cursor()
        cur.execute("SELECT * FROM experience_records WHERE id = ?", (record_id,))
        return dict(cur.fetchone())


class TestMergeDuplicateRecords:
    def test_merges_same_identity_keeps_oldest_and_sums_seen(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            first = _legacy_dup(ekb, QUESTION, structure="a", created="2026-11-01T00:00:00+00:00")
            _legacy_dup(ekb, QUESTION, structure="b", created="2026-11-02T00:00:00+00:00",
                        seen=4)

            outcome = ekb.mergeDuplicateRecords()

            assert outcome["removed"] == 1 and outcome["groups"] == 1
            assert _row(ekb, first)["seen_count"] == 5, "重复次数是事实：seen_count 取和"
            with ekb._lock:
                n = ekb._conn.execute(
                    "SELECT count(*) FROM experience_records WHERE content_key LIKE ?",
                    (f"%{QUESTION}%",)).fetchone()[0]
            assert n == 1, "被并行未删除"
        finally:
            ekb.close()

    def test_result_and_timestamp_refresh_to_latest(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            first = _legacy_dup(ekb, QUESTION, structure="a", created="2026-11-01T00:00:00+00:00")
            _legacy_dup(ekb, QUESTION, structure="b", created="2026-11-03T00:00:00+00:00")

            ekb.mergeDuplicateRecords()

            row = _row(ekb, first)
            assert row["created_at"] == "2026-11-03T00:00:00+00:00", "合并后取最新一次"
            assert json.loads(row["result"])["reply_excerpt"] == "r-b", "result 刷新为最新"
        finally:
            ekb.close()

    def test_information_never_regresses(self, tmp_path):
        """证据/可核/采纳/处置四列只升不降：保留行缺的从被并行的最新非空值继承。"""
        ekb = _ekb(tmp_path)
        try:
            kept = _legacy_dup(ekb, QUESTION, structure="a",
                               evidence_state="unevidenced", verifiability="unchecked",
                               adoption=None, disposition=None,
                               created="2026-11-01T00:00:00+00:00")
            _legacy_dup(ekb, QUESTION, structure="b",
                        evidence_state="evidenced", verifiability="violated",
                        adoption="success", disposition="endorsed",
                        created="2026-11-02T00:00:00+00:00")

            ekb.mergeDuplicateRecords()

            row = _row(ekb, kept)
            assert row["evidence_state"] == "evidenced", "证据态被合并清掉"
            assert row["verifiability_state"] == "violated", "可核结论被合并清掉"
            assert row["adoption_outcome"] == "success", "采纳结论被合并清掉"
            assert row["operator_disposition"] == "endorsed", "人工处置被合并清掉"
        finally:
            ekb.close()

    def test_identity_dimensions_stay_split(self, tmp_path):
        """身份四元组任一维不同就各成一行：异成败/异 agent/异 content_key 不合并。"""
        ekb = _ekb(tmp_path)
        try:
            _legacy_dup(ekb, QUESTION, structure="a", success=None)
            _legacy_dup(ekb, QUESTION, structure="b", success=True)
            _legacy_dup(ekb, QUESTION, structure="c", success=None, agent="kai")
            _legacy_dup(ekb, "另一个问题", structure="d", success=None)

            outcome = ekb.mergeDuplicateRecords()

            assert outcome["removed"] == 0, "不同身份的行被吞并＝失败证据丢失"
        finally:
            ekb.close()

    def test_blank_content_key_rows_never_merge(self, tmp_path):
        """content_key 空串＝算不出内容身份，与写入门同口径：各自成行不参与合并。"""
        ekb = _ekb(tmp_path)
        try:
            rid_a = _legacy_dup(ekb, QUESTION, structure="a")
            with ekb._lock:
                ekb._conn.execute(
                    "UPDATE experience_records SET content_key = '' WHERE id = ?", (rid_a,))
                ekb._conn.commit()
            _legacy_dup(ekb, QUESTION, structure="b")
            with ekb._lock:
                ekb._conn.execute(
                    "UPDATE experience_records SET content_key = '' WHERE id = ?",
                    (rid_a + 1,))
                ekb._conn.commit()

            outcome = ekb.mergeDuplicateRecords()

            assert outcome["removed"] == 0, "空键行被互吞＝写入门口径被破坏"
        finally:
            ekb.close()

    def test_idempotent_second_run_is_noop(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            _legacy_dup(ekb, QUESTION, structure="a")
            _legacy_dup(ekb, QUESTION, structure="b")

            first = ekb.mergeDuplicateRecords()
            second = ekb.mergeDuplicateRecords()

            assert first["removed"] == 1
            assert second == {"groups": 0, "removed": 0}, "幂等性破坏＝运维工具不可复跑"
        finally:
            ekb.close()

    def test_write_gate_and_cleanup_divide_the_labor(self, tmp_path):
        """分工契约：新重复由写入门当场合并（不再产生），存量重复由本方法清理。
        修复后的真实写入路径对同问只落一行，清理方法对它必须是 no-op。"""
        from neurova.skills.experience_knowledge_base import ExperienceRecord

        ekb = _ekb(tmp_path)
        try:
            for i in range(2):
                ekb.add_experience_record(
                    skill_name="chat",
                    exp=ExperienceRecord(
                        skill_name="chat",
                        context={"user_input": QUESTION},
                        result={"reply_excerpt": f"r{i}"},
                        success=None, timestamp="2026-11-12T10:00:00+00:00"),
                    agent_id="default")

            with ekb._lock:
                n = ekb._conn.execute(
                    "SELECT count(*) FROM experience_records WHERE content_key LIKE ?",
                    (f"%{QUESTION}%",)).fetchone()[0]
            assert n == 1, "修好的写入门又让同问落了两行"
            assert _row(ekb, 1)["seen_count"] == 2

            outcome = ekb.mergeDuplicateRecords()
            assert outcome == {"groups": 0, "removed": 0}, "写入门已合并的行被二次清理误伤"
        finally:
            ekb.close()
