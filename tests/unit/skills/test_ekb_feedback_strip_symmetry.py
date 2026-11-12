# -*- coding: utf-8 -*-
"""P2-24 attachUserOutcome 匹配/存储 strip 不对称红测（全库断点审计 2026-11-12）。

缺陷：匹配侧把 user_input strip 后与库里的 context.user_input（**原始串**，
写入侧不 strip）做精确等值——含首尾空白的提问永远补不上票。
修复口径（审计开方）：匹配侧与存储侧同口径——绑原始串。
"""
import json

import pytest


@pytest.fixture
def ekb(tmp_path):
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _insert_raw(ekb, user_input: str) -> int:
    with ekb._lock:
        cur = ekb._conn.cursor()
        cur.execute(
            """
            INSERT INTO experience_records
                (skill_name, context, result, success, timestamp, feedback,
                 agent_id, session_id, confidence_score, tags, created_at,
                 content_key, seen_count, evidence_state, verifiability_state,
                 adoption_outcome, operator_disposition)
            VALUES (?, ?, ?, NULL, ?, NULL, ?, NULL, NULL, '[]', ?, ?, 1,
                    'unevidenced', 'unchecked', NULL, NULL)
            """,
            ("chat",
             json.dumps({"user_input": user_input}, ensure_ascii=False, sort_keys=True),
             json.dumps({"reply_excerpt": "r"}, ensure_ascii=False),
             "2026-11-12T10:00:00+00:00", "default",
             "2026-11-12T10:00:00+00:00",
             json.dumps({"user_input": user_input}, ensure_ascii=False, sort_keys=True)),
        )
        ekb._conn.commit()
        return cur.lastrowid


def test_feedback_with_surrounding_whitespace_still_matches(ekb):
    raw = "  带首尾空格的问题  "
    rid = _insert_raw(ekb, raw)

    updated = ekb.attachUserOutcome(agent_id="default", user_input=raw, success=True)

    assert updated == 1, "同串（含首尾空格）回执必须补上票"
    with ekb._lock:
        row = dict(ekb._conn.execute(
            "SELECT success FROM experience_records WHERE id = ?", (rid,)).fetchone())
    assert row["success"] == 1


def test_feedback_different_text_still_no_match(ekb):
    """反向对照：不同问题不误伤。"""
    _insert_raw(ekb, "问题甲")
    assert ekb.attachUserOutcome(agent_id="default", user_input="问题乙", success=True) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
