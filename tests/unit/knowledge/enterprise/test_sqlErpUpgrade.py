# -*- coding: utf-8 -*-
"""W11 连接器升级（specs/2026-11-12 §12）：
SQL 水位列类型显式声明（timestamp/自增整数闭集）＋timestamp 稳定键分页
＋describeSchema 补主键/可空性读数；ERP vendor 注册数据化＋cursor
环检测（同 cursor 再现即停并如实报错）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
from neurova.knowledge.enterprise.registry import buildAdapter
from neurova.knowledge.enterprise.schema_mapping import MappingError


class TestWatermarkType:
    def test_descriptorWatermarkTypeAccepted(self, tmp_path):
        """水位列类型显式声明：timestamp/integer 闭集。"""
        descriptor = {
            "sourceType": "sql", "driver": "sqlite", "database": str(tmp_path / "t.db"),
            "table": "events", "cursorColumn": "updated_at",
            "columns": ["id", "updated_at"],
            "watermarkType": "timestamp", "tiebreakerColumn": "id",
            "mapping": {"subject": {"column": "id"}, "predicate": {"termId": "row"},
                        "object": {"column": "updated_at"}},
        }
        adapter = buildAdapter(descriptor, "wt1", "default")
        assert adapter is not None

    def test_timestampWatermarkRequiresStableTiebreaker(self, tmp_path):
        with pytest.raises(MappingError, match="tiebreakerColumn"):
            SqlDirectAdapter(
                {"sourceType": "sql", "driver": "sqlite", "database": str(tmp_path / "t.db"),
                 "table": "events", "cursorColumn": "updated_at",
                 "columns": ["id", "updated_at"], "watermarkType": "timestamp"},
                "wt-missing-key", "default")

    def test_timestampUsesLexicographicWatermarkAndTiebreaker(self, tmp_path):
        """同时间戳多行按稳定唯一键推进，不用会重复首批的 `>=`。"""
        adapter = SqlDirectAdapter(
            {"sourceType": "sql", "driver": "sqlite", "database": ":memory:",
             "table": "events", "cursorColumn": "updated_at",
             "columns": ["id", "updated_at"],
             "watermarkType": "timestamp", "tiebreakerColumn": "id"},
            "wt2", "default")
        sql, params = adapter._buildFetchSql(("2026-11-26T00:00:00", 2), 3)
        assert "updated_at > ? OR (updated_at = ? AND id > ?)" in sql
        assert "ORDER BY updated_at, id" in sql
        assert params == ("2026-11-26T00:00:00", "2026-11-26T00:00:00", 2, 3)

    def test_boundaryIntegerUsesGt(self, tmp_path):
        """自增整数：`>` 保持不变（唯一值不漏不重）。"""
        adapter = SqlDirectAdapter(
            {"sourceType": "sql", "driver": "sqlite", "database": ":memory:",
             "table": "events", "cursorColumn": "id",
             "columns": ["id"],
             "watermarkType": "integer"},
            "wt3", "default")
        cond = adapter._watermarkCondition()
        assert ">" in cond and ">=" not in cond, "integer 类型保持 >"

    def test_defaultIntegerZeroDrift(self, tmp_path):
        """未声明 watermarkType 的存量行为零漂移（回退 integer → `>`）。"""
        adapter = SqlDirectAdapter(
            {"sourceType": "sql", "driver": "sqlite", "database": ":memory:",
             "table": "events", "cursorColumn": "id",
             "columns": ["id"]},
            "wt4", "default")
        cond = adapter._watermarkCondition()
        assert ">" in cond and ">=" not in cond


class TestErpVendorDataify:
    def test_erpVendorRegistryDataified(self):
        """vendor 注册数据化：kind→适配器工厂表是数据（新 vendor 接入不改分支）。

        完整 dataification 需同步 VARIANT_CLOSED_SETS——当前批次只落工厂表
        单源（buildAdapter 经表查找而非硬编码分支），闭集同步留后续。"""
        from neurova.knowledge.enterprise.connectors_erp import ERP_VENDOR_ADAPTERS

        assert "kingdee" in ERP_VENDOR_ADAPTERS, "工厂表应含 kingdee"
        assert "yongyou" in ERP_VENDOR_ADAPTERS, "工厂表应含 yongyou"
        assert ERP_VENDOR_ADAPTERS["kingdee"] is ERP_VENDOR_ADAPTERS["yongyou"],             "同适配器类不同 vendor 实例（分页语义在类内按 vendor 分）"

    def test_cursorLoopDetected(self, tmp_path):
        """分页 cursor 环检测：同 cursor 再现即停并如实报错。"""
        from neurova.knowledge.enterprise.connectors_erp import ErpRestAdapter

        adapter = ErpRestAdapter(
            {"sourceType": "erp_api", "vendor": "kingdee",
             "base_url": "https://erp.example", "credential_env": "P_ERP"},
            "erp2", "default")
        # 模拟同 cursor 连续出现
        with pytest.raises(RuntimeError, match="环"):
            adapter._checkCursorLoop("page_5")
            adapter._checkCursorLoop("page_5")

class TestClosedSetDataification:
    def test_sqlDriversFromSingleSource(self):
        """SQL driver 闭集从 _DRIVER_MODULES 派生（非硬编码）。"""
        from neurova.knowledge.enterprise.connectors_sql import _DRIVER_MODULES
        from neurova.knowledge.enterprise.schema_mapping import VARIANT_CLOSED_SETS

        closed = VARIANT_CLOSED_SETS["sql"][1]
        assert set(closed) == set(_DRIVER_MODULES.keys()),             "SQL driver 闭集应从 _DRIVER_MODULES 单源派生"

    def test_erpVendorsFromSingleSource(self):
        """ERP vendor 闭集从 ERP_VENDOR_ADAPTERS 派生（非硬编码）。"""
        from neurova.knowledge.enterprise.connectors_erp import ERP_VENDOR_ADAPTERS
        from neurova.knowledge.enterprise.schema_mapping import VARIANT_CLOSED_SETS

        closed = VARIANT_CLOSED_SETS["erp_api"][1]
        assert set(closed) == set(ERP_VENDOR_ADAPTERS.keys()),             "ERP vendor 闭集应从 ERP_VENDOR_ADAPTERS 单源派生"

    def test_lakehouseKindsHaveNoEnumerableVariant(self):
        """湖仓 kind 无可枚举变体——不进变体闭集（U-conn 扩展批修正）。

        旧条目把 base_url 的值对 kind 名闭集做成员判定，任何可保存的真实
        描述符（base_url=https://…）都会被拒——变体机制被误用；必填字段由
        适配器自身 health/fetch 判缺。
        """
        from neurova.knowledge.enterprise.connectors_lakehouse import _LAKEHOUSE_KINDS
        from neurova.knowledge.enterprise.schema_mapping import VARIANT_CLOSED_SETS

        for kind in _LAKEHOUSE_KINDS:
            assert kind not in VARIANT_CLOSED_SETS, \
                f"湖仓 kind {kind} 无枚举变体，不应有闭集条目"

    def test_httpPullHasNoEnumerableVariant(self):
        from neurova.knowledge.enterprise.schema_mapping import VARIANT_CLOSED_SETS

        assert "http_pull" not in VARIANT_CLOSED_SETS
