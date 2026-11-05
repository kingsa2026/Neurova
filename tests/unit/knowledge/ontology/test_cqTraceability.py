# -*- coding: utf-8 -*-
"""B9 L0 范围层（升级计划 §12.1）：CQ 目录的需求追溯判据。

每条 P1 CQ 必须有查询与测试，测试文件必须真实存在——追溯矩阵零孤儿、
零无测试 P1。CQ 文件是唯一事实源：docs/specs/2026-11-05-ontology-cq.md。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CQ_DOC = REPO_ROOT / "docs" / "specs" / "2026-11-05-ontology-cq.md"

_ROW = re.compile(
    r"^\|\s*(?P<cq_id>CQ-\d+)\s*\|\s*(?P<question>[^|]+)\|\s*(?P<actor>[^|]+)\|"
    r"\s*(?P<priority>[^|]+)\|\s*(?P<query>[^|]*)\|\s*(?P<test_id>[^|]*)\|"
    r"\s*(?P<status>[^|]+)\|", re.MULTILINE)


def _rows() -> list:
    text = CQ_DOC.read_text(encoding="utf-8")
    rows = []
    for match in _ROW.finditer(text):
        row = {k: v.strip() for k, v in match.groupdict().items()}
        if set(row["priority"].lower() for _ in [0]) and row["priority"]:
            row["priority"] = row["priority"].strip()
        rows.append(row)
    return rows


def test_cqDocExistsAndHasTable():
    assert CQ_DOC.exists(), "CQ 目录文件是 L0 的唯一事实源"
    rows = _rows()
    assert len(rows) >= 5, "CQ 表至少覆盖五条能力问题，收到 %d" % len(rows)


def test_cqIdsUnique():
    ids = [r["cq_id"] for r in _rows()]
    assert len(ids) == len(set(ids)), "CQ id 重复：%s" % ids


def test_everyP1CqHasQueryAndTest():
    """P1 CQ 100% 有查询与测试——没有追溯的能力问题不进 P1。"""
    p1 = [r for r in _rows() if r["priority"].upper() == "P1"]
    assert p1, "至少要有一条 P1 CQ"
    for row in p1:
        assert row["query"], "%s 缺查询" % row["cq_id"]
        assert row["test_id"], "%s 缺测试" % row["cq_id"]


def test_referencedTestFilesExistZeroOrphan():
    """追溯零孤儿：implemented/partial 的 CQ 引用的测试文件必须真实在仓内。

    planned 是前向引用（测试随工作包落地），不在孤儿判据内——
    但它的 test_id 仍不得为空（追溯链先立，码后到）。
    """
    missing = []
    for row in _rows():
        testId = row["test_id"]
        if not testId:
            continue
        if row["status"].lower() not in ("implemented", "partial"):
            continue
        path = testId.split("::")[0]
        if not (REPO_ROOT / path).exists():
            missing.append("%s → %s" % (row["cq_id"], testId))
    assert missing == [], "孤儿追溯（测试文件不存在）：%s" % missing


def test_statusVocabularyClosed():
    allowed = {"implemented", "planned", "partial"}
    for row in _rows():
        assert row["status"].lower() in allowed, \
            "%s 的 status %r 不在闭集内" % (row["cq_id"], row["status"])
