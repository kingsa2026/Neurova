# -*- coding: utf-8 -*-
"""CQ 追溯现值读数面（名册＋探针＋端点）：撤前端静态表的服务端供数。

页面 CQ 表的数据形态（照 default-off 读数面先例）：
- 元数据（cqId/question/actor/priority/query/testId）照抄唯一事实源
  docs/specs/2026-11-05-ontology-cq.md 的追溯矩阵，对拍判据钉"第二份抄本不许漂移"；
- status **不抄文档票面**——specs 的 status 列是计划态（人管），名册的 status 由
  探针查产品面符号（端点处理函数、引擎方法、REST 参数签名）给现值，接线/退役
  自动翻转。CQ-10（asOf/knownAt REST 参数）是它的活证：签名里参数出现的那天，
  现值自动转 implemented，同时提醒把 specs 票面同步转正；
- 端点 GET /knowledge/ontology/cq-matrix 登录可读（能力现值不是配置面，
  与 default-off 的管理员门不同门）。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CQ_DOC = REPO_ROOT / "docs" / "specs" / "2026-11-05-ontology-cq.md"

_ROW = re.compile(
    r"^\|\s*(?P<cq_id>CQ-\d+)\s*\|\s*(?P<question>[^|]+)\|\s*(?P<actor>[^|]+)\|"
    r"\s*(?P<priority>[^|]+)\|\s*(?P<query>[^|]*)\|\s*(?P<test_id>[^|]*)\|"
    r"\s*(?P<status>[^|]+)\|", re.MULTILINE)


def _docRows() -> dict:
    text = CQ_DOC.read_text(encoding="utf-8")
    rows = {}
    for match in _ROW.finditer(text):
        row = {k: v.strip() for k, v in match.groupdict().items()}
        rows[row["cq_id"]] = row
    return rows


def _normalize(text: str) -> str:
    """query 列对拍用：剥显示修饰（反引号/空白/逗号）。

    名册的 query 是面向显示的转写——允许比文档票面多注解（如 CQ-10 的
    「REST 参数未接线」）、也可能丢过文档里的逗号；故判据是规范化后的
    文档文本为名册文本的**前缀**，主干抄错/抄漏当场红。
    """
    return re.sub(r"[`,\s，()（）]", "", text.replace("／", "/"))


def test_registryMetadataMatchesSpecDocRowByRow():
    """名册元数据与 specs 表逐行对拍——第二份抄本漂移当场红。"""
    from neurova.knowledge.ontology.cq_matrix import CQ_TRACE_ROWS

    docRows = _docRows()
    assert len(docRows) == 22, "specs 追溯矩阵应有 22 行"
    assert {row.cqId for row in CQ_TRACE_ROWS} == set(docRows), "名册与 specs 的 CQ 全集不一致"
    for row in CQ_TRACE_ROWS:
        doc = docRows[row.cqId]
        assert row.question == doc["question"], row.cqId
        assert row.actor == doc["actor"], row.cqId
        assert row.priority == doc["priority"], row.cqId
        # testId 是追溯键，逐字对拍（含 ::类名段）
        assert row.testId == doc["test_id"], row.cqId
        # query 主干对拍（显示注解不进判据）
        normalizedDoc = _normalize(doc["query"])
        normalizedRow = _normalize(row.query)
        assert normalizedRow.startswith(normalizedDoc), \
            "%s 的 query 主干与 specs 不对齐：%r vs %r" % (row.cqId, normalizedRow, normalizedDoc)


def test_probeStatusesMatchProductFace():
    """探针现值与产品面事实对拍——status 不是抄来的。"""
    from neurova.knowledge.ontology.cq_matrix import cqTraceRows

    rows = {r["cqId"]: r["status"] for r in cqTraceRows()}
    implemented = {
        "CQ-01", "CQ-02", "CQ-03", "CQ-04", "CQ-05",
        "CQ-06", "CQ-07", "CQ-08", "CQ-09", "CQ-10", "CQ-11", "CQ-12",
        "CQ-13", "CQ-14", "CQ-15", "CQ-16", "CQ-17", "CQ-18", "CQ-19", "CQ-20", "CQ-21", "CQ-22",
    }
    for cqId in sorted(implemented):
        assert rows[cqId] == "implemented", cqId
    # CQ-10 已随 W0-1 转正（specs/2026-11-12 §2）：accessQuery 签名含 asOf/knownAt，
    # MCP ontology_query 同名参数透传，非法时间显式 4xx——探针现值自动 implemented。
    # CQ-12 随 W2 转正（specs/2026-11-12 §4）：函数层登记/引擎/MCP/REST 四符号在册。


def test_statusVocabularyClosed():
    """status 闭集与 specs 票面词汇一致。"""
    from neurova.knowledge.ontology.cq_matrix import cqTraceRows

    allowed = {"implemented", "planned", "partial"}
    for row in cqTraceRows():
        assert row["status"] in allowed, "%s 的 status %r 不在闭集内" % (row["cqId"], row["status"])


def test_referencedTestFilesExistZeroOrphan():
    """名册 testId 指向的测试文件必须真实在仓（与 specs 孤儿守卫同判据）。"""
    from neurova.knowledge.ontology.cq_matrix import CQ_TRACE_ROWS

    missing = []
    for row in CQ_TRACE_ROWS:
        path = row.testId.split("::")[0]
        if not path:
            missing.append("%s → 空 testId" % row.cqId)
        elif not (REPO_ROOT / path).exists():
            missing.append("%s → %s" % (row.cqId, row.testId))
    assert missing == [], "孤儿追溯：%s" % missing


def test_readoutRowsExposeDisplayFields():
    """读数行带全显示字段；不回探针/模块等工程内部（页面不是工程面板）。"""
    from neurova.knowledge.ontology.cq_matrix import cqTraceRows

    rows = cqTraceRows()
    assert len(rows) == 22
    for row in rows:
        assert set(row) == {"cqId", "question", "actor", "priority", "query", "testId", "status"}
        assert row["question"] and row["query"] and row["testId"]


def test_endpointReadingsShapeAndGate():
    """端点登录可读（能力现值不是配置面，非 admin 也要拿得到全表）。"""
    from neurova.api.endpoints.knowledge_observability import getCqMatrix

    result = asyncio.run(getCqMatrix({"role": "user", "tenant_id": "default"}))
    assert result["code"] == 0
    items = result["data"]["items"]
    assert len(items) == 22
    assert {item["cqId"] for item in items} == set(_docRows())
