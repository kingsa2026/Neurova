# -*- coding: utf-8 -*-
"""冲突四象限标注评估：准确率、误合并率、无样本诚实报。"""
from __future__ import annotations

import json
from pathlib import Path

from neurova.knowledge.evaluation.conflict_eval import evaluateConflictCases


def _fixture():
    path = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_conflict_eval_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def testLabeledFixtureIsClassifiedAndScored():
    report = evaluateConflictCases(_fixture())

    assert report["measure_state"] == "measured"
    assert report["evaluated_count"] == 6
    assert report["accuracy"] == 1.0
    assert report["false_merge_rate"] == 0.0
    assert report["confusion"]["conflict"]["conflict"] == 1


def testEmptyCasesIsUnevidenced():
    report = evaluateConflictCases([])

    assert report["measure_state"] == "unevidenced"
    assert report["missing_reason"]


def testInvalidLabelsDoNotCountAsPass():
    report = evaluateConflictCases([
        {"case_id": "bad", "left": "a", "right": "b", "expected": "maybe"},
    ])

    assert report["measure_state"] == "unevidenced"
    assert report["invalid_cases"][0]["case_id"] == "bad"


def testMissedConflictShowsInFalseMergeRate():
    report = evaluateConflictCases([{
        "case_id": "m1", "left": "Alpha budget", "right": "Alpha budget detail",
        "vector_similarity": 0.9, "subject_similarity": 0.95, "expected": "conflict",
    }])

    assert report["false_merge_rate"] == 1.0
    assert report["confusion"]["conflict"]["similar"] == 1
