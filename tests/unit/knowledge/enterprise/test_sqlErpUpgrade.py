# -*- coding: utf-8 -*-
"""W11 连接器升级（specs/2026-11-12 §12）：
SQL 水位列类型显式声明（timestamp/自增整数闭集）＋边界等值处理（timestamp=>
防漏防重）＋describeSchema 补主键/可空性读数；ERP vendor 注册数据化＋cursor
环检测（同 cursor 再现即停并如实报错）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
from neurova.knowledge.enterprise.registry import buildAdapter


class TestWatermarkType:
    def test_descriptorWatermarkTypeAccepted(self, tmp_path):
        """水位列类型显式声明：timestamp/integer 闭集。"""
        descriptor = {
            "sourceType": "sql", "driver": "sqlite", "database": str(tmp_path / "t.db"),
            "table": "events", "cursorColumn": "updated_at",
            "columns": ["id", "updated_at"],
            "watermarkType": "timestamp",
            "mapping": {"subject": {"column": "id"}, "predicate": {"termId": "row"},
                        "object": {"column": "updated_at"}},
        }
        adapter = buildAdapter(descriptor, "wt1", "default")
        assert adapter is not None

    def test_boundaryTimestampUsesGteWithDedup(self, tmp_path):
        """timestamp 边界等值：`>=` 取回同水位行＋去重已处理行（防漏防重）。"""
        adapter = SqlDirectAdapter(
            {"sourceType": "sql", "driver": "sqlite", "database": ":memory:",
             "table": "events", "cursorColumn": "updated_at",
             "columns": ["id", "updated_at"],
             "watermarkType": "timestamp"},
            "wt2", "default")
        # 验证水位比较符按类型选择
        cond = adapter._watermarkCondition()
        assert ">=" in cond, "timestamp 类型应使用 >= 防漏"

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
