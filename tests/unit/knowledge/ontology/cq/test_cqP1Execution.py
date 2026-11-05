# -*- coding: utf-8 -*-
"""B13 L9：P1 CQ 全量执行（升级计划 §12.10）——CQ 表里每条 implemented 的
P1 问题在本目录有对应执行用例并真实通过。CQ 文件是唯一事实源。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CQ_DOC = REPO_ROOT / "docs" / "specs" / "2026-11-05-ontology-cq.md"

_ROW = re.compile(
    r"^\|\s*(CQ-\d+)\s*\|\s*([^|]+)\|\s*[^|]+\|\s*(P\d)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*(\w+)\s*\|",
    re.MULTILINE)


def _implementedP1():
    text = CQ_DOC.read_text(encoding="utf-8")
    return [(m.group(1), m.group(4).strip(), m.group(5).strip())
            for m in _ROW.finditer(text)
            if m.group(3) == "P1" and m.group(6) == "implemented"]


@pytest.mark.parametrize("cqId,query,testId", _implementedP1(),
                         ids=[r[0] for r in _implementedP1()])
def test_p1CqExecution(cqId, query, testId):
    """每条 P1 CQ：查询面存在 + 判据测试真实在仓（L9 追溯零孤儿）。"""
    assert query, "%s 缺查询" % cqId
    path = testId.split("::")[0]
    assert (REPO_ROOT / path).exists(), "%s 引用的测试不存在: %s" % (cqId, path)
