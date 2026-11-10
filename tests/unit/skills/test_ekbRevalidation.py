# -*- coding: utf-8 -*-
"""H4 EKB 陈旧复验通道（survey §10.2）——低置信/超期进队列，复验回写。

红灯判据两半：复验缺席保持现值不冒充（未复验条目 evidence_state 不变，
队列纯读数不改库）；复验结果可回写（唯一写口走 EKB 本体）。
"""

from pathlib import Path

import pytest

from neurova.skills.ekb_revalidation import (
    applyRevalidation,
    revalidationQueue,
)
from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)


def _mk_ekb(tmp_path: Path) -> ExperienceKnowledgeBase:
    base = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
    base.add_experience_record(
        "skill-a",
        ExperienceRecord(skill_name="skill-a", context={"topic": "t"},
                         result={"ok": True}, success=True),
        confidence_score=0.2,
    )
    base.add_experience_record(
        "skill-b",
        ExperienceRecord(skill_name="skill-b", context={"topic": "t"},
                         result={"ok": True}, success=True),
        confidence_score=0.9,
    )
    return base


@pytest.fixture
def ekb(tmp_path):
    return _mk_ekb(tmp_path)


def test_low_confidence_entries_enter_queue(ekb):
    """低置信条目进队列（高置信的没进去）。"""
    readout = revalidationQueue(ekb)
    assert readout["queue_size"] == 1, f"队列形态异常：{readout}"
    assert readout["queue"][0]["skill_name"] == "skill-a"
    assert readout["queue"][0]["confidence_score"] == pytest.approx(0.2)


def test_queue_is_pure_read(ekb):
    """复验缺席保持现值：队列读数不改库（纯读数）。"""
    before = revalidationQueue(ekb)
    after = revalidationQueue(ekb)
    assert before == after, "队列读数有副作用——复验缺席却被改动"


def test_revalidation_writes_back(ekb):
    """复验回写：verdict 经唯一写口落 evidence_state。"""
    queue = revalidationQueue(ekb)
    record_id = queue["queue"][0]["id"]
    assert applyRevalidation(ekb, record_id, verdict="unevidenced") is True
    after = revalidationQueue(ekb)
    entry = next(q for q in after["queue"] if q["id"] == record_id)
    assert entry["evidence_state"] == "unevidenced"


def test_invalid_verdict_rejected(ekb):
    with pytest.raises(ValueError, match="非法"):
        applyRevalidation(ekb, 1, verdict="maybe")
