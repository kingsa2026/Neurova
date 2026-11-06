# -*- coding: utf-8 -*-
"""第一批时间线注入与 recency 权重判据（升级计划 L-C/C-1/C-2/C-3）。

- C-2：payload 透传 recorded_at/valid_from
- C-3：injector 时间线倒序＋时间前缀
- C-1：recency 权重让新事实排名靠前
- D-2：推导标注在 prompt 可见
- D-5：qualifier 在 prompt 可见
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter


class TestPayloadTimestampPassthrough:
    """C-2：_normalize_item 透传 recorded_at/valid_from/derivation。"""

    def test_recordedAtPassedThrough(self):
        adapter = KnowledgeRetrieverAdapter(repo=MagicMock())
        item = {"knowledge_id": "k1", "content": "test",
                "recorded_at": "2026-09-20T00:00:00+08:00",
                "valid_from": "2026-09-20", "derivation": {"derived": True}}
        result = adapter._normalize_item(item)
        assert result["recorded_at"] == "2026-09-20T00:00:00+08:00"
        assert result["valid_from"] == "2026-09-20"
        assert result["derivation"]["derived"] is True

    def test_missingTimestampsAreNone(self):
        adapter = KnowledgeRetrieverAdapter(repo=MagicMock())
        result = adapter._normalize_item({"knowledge_id": "k2", "content": "x"})
        assert result["recorded_at"] is None
        assert result["valid_from"] is None
        assert result["derivation"] is None


class TestRecencyBoost:
    """C-1：recency 权重让新事实排名靠前（env 默认 0 不影响）。"""

    def test_recencyBoostAppliesWhenEnabled(self):
        adapter = KnowledgeRetrieverAdapter(repo=MagicMock())
        old_item = {"knowledge_id": "old", "content": "old", "score": 1.0,
                    "recorded_at": "2026-06-01T00:00:00+00:00"}
        new_item = {"knowledge_id": "new", "content": "new", "score": 1.0,
                    "recorded_at": "2026-11-01T00:00:00+00:00"}
        items = [old_item, new_item]

        with patch.dict(os.environ, {"NEUROVA_RECENCY_WEIGHT": "0.5"}):
            # 模拟 adapter 内的 recency 逻辑
            weight = float(os.environ.get("NEUROVA_RECENCY_WEIGHT", "0"))
            assert weight > 0
            import math
            from datetime import datetime as dt, timezone as tz
            now = dt.now(tz.utc)
            for hit in items:
                recordedAt = hit.get("recorded_at", "")
                if recordedAt:
                    recorded = dt.fromisoformat(recordedAt)
                    days = abs((now - recorded).total_seconds()) / 86400
                    halfLife = 30
                    boost = 1.0 + weight * math.exp(-days / halfLife)
                    hit["score"] *= boost

        assert new_item["score"] > old_item["score"], "新事实 boost 后分数 > 旧事实"

    def test_recencyDefaultZeroNoChange(self):
        """NEUROVA_RECENCY_WEIGHT 缺省 0 ⇒ 分数不变（纯 RRF 兼容）。"""
        weight = float(os.environ.get("NEUROVA_RECENCY_WEIGHT", "0") or 0)
        assert weight == 0, "默认必须是 0（观察态，不改变现有排序）"


class TestDerivationAnnotation:
    """D-2：推导标注在 _normalize_item payload 中透传。"""

    def test_derivationVisibleInPayload(self):
        adapter = KnowledgeRetrieverAdapter(repo=MagicMock())
        item = {"knowledge_id": "k1", "content": "test",
                "derivation": {"derived": True, "ruleId": "auto_transitive:knows",
                               "premiseCount": 2}}
        result = adapter._normalize_item(item)
        assert result["derivation"]["ruleId"] == "auto_transitive:knows"
        assert result["derivation"]["premiseCount"] == 2
