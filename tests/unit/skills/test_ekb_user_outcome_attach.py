# -*- coding: utf-8 -*-
"""用户回执补喂 EKB 成败位（T1 证据供给增强，对齐结晶器 attachTurnOutcome 先例）。

被接的缺口是实算出来的（2026-11-12 生产库读数）：EKB 382 条沉淀里 **374 条是纯
对话轮**（skill_name="chat"），success 三态恰好 374 条 NULL——纯对话轮没有工具回执；
服务端票据又只认「同**参数值**结构的历史票」（`creation_governance.structure_key`
把参数值一起进哈希，参数一变结构身份就变，自由文本参数的工具轮同样永远查无票）。
于是这些行的成败位**永远**停在「未测量」，质量评估面无料可评。

用户赞踩（`POST /api/v1/console/chat/feedback`）是该轮唯一真实已知的结局信号。
结晶器已有同款先例（`attachTurnOutcome`，§6-209 第四面扇出——只补工具条目，裁定甲）。
本批把同一信号接进 EKB，但**没有裁定甲那条排除**：EKB 行是逐轮沉淀不是结晶模式，
"寒暄被赞"在这里不成模式、只把那一行的成败位从未测量变成已测量。

三条机制约束（与结晶器先例同形）各自有格：
- **只填 NULL 成败位**——工具回执（002）与服务端票据（010）的结论优先级更高，
  主观回执无权改判客观结论（两个方向都不许翻）；
- **不碰 evidence_state**——工单 010：证据只认服务端票据，用户回执不是票据，
  填它等于稀释「无证据占比」这个告警读数；
- **按 agent 隔离、按原文精确匹配**——对不上就不动，错配比一次失败更难发现。
"""
from __future__ import annotations

import pytest

QUESTION = "帮我对比一下 SQLite 与 PostgreSQL 的适用场景"


def _ekb(tmp_path):
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _add_chat(ekb, user_input, agent_id="default", success=None, session_id=None):
    from neurova.skills.experience_knowledge_base import ExperienceRecord

    return ekb.add_experience_record(
        skill_name="chat",
        exp=ExperienceRecord(
            skill_name="chat",
            context={"user_input": user_input, "structure_key": None},
            result={"reply_excerpt": "r"},
            success=success,
            timestamp="2026-11-12T10:00:00+00:00",
        ),
        agent_id=agent_id,
        session_id=session_id,
    )


def _row(ekb, record_id):
    with ekb._lock:
        cur = ekb._conn.cursor()
        cur.execute("SELECT * FROM experience_records WHERE id = ?", (record_id,))
        return dict(cur.fetchone())


class TestAttachUserOutcome:
    def test_fills_only_null_success_and_reports_count(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            unmeasured = _add_chat(ekb, QUESTION, success=None)
            measured = _add_chat(ekb, QUESTION + "（已测轮）", success=False)

            attached = ekb.attachUserOutcome("default", QUESTION, True)

            assert attached == 1, "只该补那一条未测量行"
            assert _row(ekb, unmeasured)["success"] == 1
            assert _row(ekb, measured)["success"] == 0, "已有客观结论的行被主观回执改判"
        finally:
            ekb.close()

    def test_objective_conclusion_is_never_flipped_either_way(self, tmp_path):
        """工单 002/010 优先级：回执/票据结论不为赞踩让路，反之亦然。"""
        ekb = _ekb(tmp_path)
        try:
            success_row = _add_chat(ekb, QUESTION, success=True)
            fail_row = _add_chat(ekb, QUESTION + "（败轮）", success=False)

            assert ekb.attachUserOutcome("default", QUESTION, False) == 0
            assert ekb.attachUserOutcome("default", QUESTION + "（败轮）", True) == 0
            assert _row(ekb, success_row)["success"] == 1
            assert _row(ekb, fail_row)["success"] == 0
        finally:
            ekb.close()

    def test_evidence_state_is_untouched(self, tmp_path):
        """工单 010：用户回执不是服务端票据——evidence_state 必须原样留在 unevidenced，
        「无证据占比」这个告警读数不许被赞踩洗绿。"""
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, success=None)

            ekb.attachUserOutcome("default", QUESTION, True)

            assert _row(ekb, rid)["evidence_state"] == "unevidenced"
            assert _row(ekb, rid)["verifiability_state"] == "unchecked"
        finally:
            ekb.close()

    def test_agent_isolation(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            other = _add_chat(ekb, QUESTION, agent_id="kai", success=None)

            assert ekb.attachUserOutcome("default", QUESTION, True) == 0
            assert _row(ekb, other)["success"] is None, "别的 agent 的行被跨库补票"
        finally:
            ekb.close()

    def test_exact_text_match_only(self, tmp_path):
        """原文精确匹配：近似句不算同一轮——错配的经验比没有经验更坏。"""
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, success=None)

            assert ekb.attachUserOutcome("default", QUESTION + "？", True) == 0
            assert _row(ekb, rid)["success"] is None
        finally:
            ekb.close()

    def test_no_match_returns_zero(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            assert ekb.attachUserOutcome("default", "从没问过的一句话", True) == 0
            assert ekb.attachUserOutcome("default", "", True) == 0, "空原文不许全表命中"
        finally:
            ekb.close()

    def test_session_scoping_when_given(self, tmp_path):
        """给出 session_id 时收窄到该会话。

        同句行经 011 去重门修好后**按设计合并**（身份不含会话），新写入不再产生
        跨会话同句多行；收窄防的是**存量**——去重门修好前（`success = ?` 绑 NULL
        时代）落库的同句多行 content_key 各异、不会合并，一次点赞不许把它们全部
        洗成同一结局。故这里用原始 SQL 构造存量形态（同句、异 content_key）。
        """
        ekb = _ekb(tmp_path)
        try:
            with ekb._lock:
                cur = ekb._conn.cursor()
                import json as _json

                for i, sid in enumerate(("s1", "s2", None)):
                    cur.execute(
                        """
                        INSERT INTO experience_records
                            (skill_name, context, result, success, timestamp, feedback,
                             agent_id, session_id, confidence_score, tags, created_at,
                             content_key, seen_count, evidence_state, verifiability_state)
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL, '[]', ?, ?, 1,
                                'unevidenced', 'unchecked')
                        """,
                        ("chat",
                         _json.dumps({"user_input": QUESTION,
                                      "structure_key": f"legacy-{i}"},
                                     ensure_ascii=False, sort_keys=True),
                         '{"reply_excerpt": "r"}',
                         "2026-11-12T10:00:00+00:00", QUESTION,
                         "default", sid,
                         "2026-11-12T10:00:00+00:00",
                         f"legacy-key-{i}"),
                    )
                ekb._conn.commit()

            attached = ekb.attachUserOutcome("default", QUESTION, True, session_id="s1")

            assert attached == 1, "跨会话误伤＝一次点赞污染存量全部同句行"
            rows = ekb.get_experience_records(agent_id="default", limit=10)
            by_session = {r.get("session_id"): r.get("success") for r in rows}
            assert by_session.get("s1") == 1
            assert by_session.get("s2") is None, "别的会话的同句行被顺带翻转"
            assert by_session.get(None) is None, "无会话的存量行被顺带翻转"
        finally:
            ekb.close()

    def test_seen_count_and_timestamp_survive(self, tmp_path):
        """补票是评估不是新发生：seen_count（重复问的次数）与写入时间不许被刷。"""
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, success=None)
            before = _row(ekb, rid)

            ekb.attachUserOutcome("default", QUESTION, True)

            after = _row(ekb, rid)
            assert after["seen_count"] == before["seen_count"]
            assert after["timestamp"] == before["timestamp"]
        finally:
            ekb.close()


class TestDedupGateCoversUnmeasuredRows:
    """工单 011 去重门对 NULL 成败行失效的根修（2026-11-12 活体验证现场抓获）。

    生产库 382 行里 **300+ 行是同一句 "hello"**——去重 SQL 写的是
    `success = ?` 绑 NULL，而 SQL 里 `= NULL` 永不成立（同一查询里 agent_id
    那格用的正是 NULL 安全的 `IS ?`），于是成败位未测量的纯对话轮**永远**
    各自成行。三态里 NULL 恰是生产多数派（374/382），去重门对它失效＝对
    多数失效。修法：`success IS ?`（NULL 安全等值），量纲与 agent_id 格一致。
    """

    def test_identical_unmeasured_writes_merge_with_seen_count(self, tmp_path):
        ekb = _ekb(tmp_path)
        try:
            first = _add_chat(ekb, QUESTION, success=None)
            second = _add_chat(ekb, QUESTION, success=None)

            assert second == first, "同句同态第二次写入落了新行（NULL 去重失效）"
            assert _row(ekb, first)["seen_count"] == 2, "合并必须以 seen_count 记账"
        finally:
            ekb.close()

    def test_different_success_still_split(self, tmp_path):
        """成败位留在身份键里的初衷（011）不许被破坏：同问一成一败仍是两行。"""
        ekb = _ekb(tmp_path)
        try:
            a = _add_chat(ekb, QUESTION, success=None)
            b = _add_chat(ekb, QUESTION, success=True)
            assert b != a, "NULL 行被无差别吞并＝失败证据丢失（证伪回路断）"
        finally:
            ekb.close()

    def test_measured_rows_merge_as_before(self, tmp_path):
        """已测量行的既有合并行为零回归（同句同成败仍合并）。"""
        ekb = _ekb(tmp_path)
        try:
            a = _add_chat(ekb, QUESTION, success=True)
            b = _add_chat(ekb, QUESTION, success=True)
            assert b == a
            c = _add_chat(ekb, QUESTION, success=False)
            assert c != a, "同句异败不许并进成功行"
        finally:
            ekb.close()


class TestFeedbackFanOutReachesEkb:
    """HTTP 面那一跳：`POST /console/chat/feedback` 的扇出真的接到 EKB。

    形状照抄同族先例 `test_crystallizerTurnEvidenceFromUserFeedback.py`
    （在端点接缝上装桩，不新建第二套假 app）。
    """

    def _fakeRequest(self):
        from fastapi import Request

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        return Request({"type": "http", "method": "POST",
                        "path": "/api/v1/console/chat/feedback", "headers": [],
                        "query_string": b""}, receive)

    def _wire(self, monkeypatch, ekb):
        import types

        import neurova.api.endpoints.console as consoleModule
        import neurova.skills.experience_knowledge_base as ekbModule

        agent = types.SimpleNamespace(crystallizer=None, memory_agent=None,
                                      intrinsic_motivation=None)

        class _Repo:
            def find_session(self, session_id):
                return {"agent_id": "default", "session_id": session_id, "user_id": "u1"}

            def update_message_metadata(self, **kw):
                return True

            def get_round(self, **kw):
                return {"user": {"content": QUESTION}, "assistant": {"content": "A"}}

        monkeypatch.setattr(consoleModule, "_get_user_id", lambda *a: "u1")
        monkeypatch.setattr(consoleModule, "get_session_repository", lambda: _Repo())
        monkeypatch.setattr(consoleModule, "get_agent_instance", lambda agent_id="": agent)
        monkeypatch.setattr(ekbModule, "get_experience_knowledge_base", lambda: ekb)
        return consoleModule

    def _post(self, consoleModule, feedback):
        import asyncio

        body = consoleModule.FeedbackRequest(session_id="s1", timestamp="2026-11-12T10:00:00",
                                             feedback=feedback)
        return asyncio.run(consoleModule.post_chat_feedback(
            body, self._fakeRequest(), {"id": "u1", "username": "u1"}))

    def test_like_fills_the_chat_rows_success_bit(self, tmp_path, monkeypatch):
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, agent_id="default", success=None,
                            session_id="s1")
            consoleModule = self._wire(monkeypatch, ekb)

            resp = self._post(consoleModule, "like")

            assert resp["code"] == 0
            assert _row(ekb, rid)["success"] == 1, "反馈端点的 EKB 扇出腿没接上"
        finally:
            ekb.close()

    def test_dislike_records_failure(self, tmp_path, monkeypatch):
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, agent_id="default", success=None,
                            session_id="s1")
            consoleModule = self._wire(monkeypatch, ekb)

            self._post(consoleModule, "dislike")

            assert _row(ekb, rid)["success"] == 0
        finally:
            ekb.close()

    def test_cancelling_feedback_changes_nothing(self, tmp_path, monkeypatch):
        """取消反馈不撤票也不补票——「取消」既不是成功也不是失败（三态不许塌成两态）。"""
        ekb = _ekb(tmp_path)
        try:
            rid = _add_chat(ekb, QUESTION, agent_id="default", success=None,
                            session_id="s1")
            consoleModule = self._wire(monkeypatch, ekb)
            self._post(consoleModule, "like")
            assert _row(ekb, rid)["success"] == 1

            self._post(consoleModule, None)

            assert _row(ekb, rid)["success"] == 1, "取消反馈撤了票（三态被写成两态）"
        finally:
            ekb.close()
