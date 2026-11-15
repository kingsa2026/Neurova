# -*- coding: utf-8 -*-
"""knowledge/data 双就绪探针（对照研究 P2-2，2026-11-15）。

对方 `check_readiness` 的本仓对应物：一个部署能不能答问题，不是任何单一
端点能回答的——术语空、事实空、目录空、源未启用，任何一项缺着都能让上层
「看起来能答」。这里把四类事实合成两个判据，全部只读、零网络：

- knowledge_ready：术语已登记 **且** 事实非空（本租户）；
- data_ready：目录已摄取 **且** 存在启用中的企业源（answerability/NL2SQL
  的前置）。

这是探针不是开关：只报现值，不提供任何启停动作。
"""

from __future__ import annotations

from typing import Any, Dict


def knowledgeReadiness(store: Any, tenantId: str = "default") -> Dict[str, Any]:
    """复合就绪读数（只读，零网络）。检查项各自给现值，判据在合成层。"""
    tenant = str(tenantId or "default")

    from .rule_engine import ForwardChainingEngine
    from .term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store)
    termsCount = len(registry.terms(tenantId=tenant))
    rulesCount = len(engine.rules(tenantId=tenant))

    factRows = store.queryReadOnly(
        "SELECT COUNT(*) AS n FROM knowledge_facts WHERE tenant_id = ?", (tenant,))
    factsCount = int(factRows[0]["n"]) if factRows else 0

    catalogSources = catalogTables = 0
    try:
        from ..enterprise.schema_catalog import SchemaCatalogStore

        counts = SchemaCatalogStore(store).counts(tenant)
        catalogSources = int(counts.get("sources") or 0)
        catalogTables = int(counts.get("tables") or 0)
    except Exception:  # noqa: BLE001 - 目录面缺席（未升级库）如实报 0
        pass

    sourcesConfigured = sourcesEnabled = 0
    try:
        from ..enterprise.registry import EnterpriseIngestor

        configs = EnterpriseIngestor(store).listConfigs(tenant)
        sourcesConfigured = len(configs)
        sourcesEnabled = sum(1 for c in configs if c.get("enabled"))
    except Exception:  # noqa: BLE001 - 配置面缺席如实报 0
        pass

    return {
        "tenant_id": tenant,
        "checks": {
            "terms_registered": termsCount,
            "rules_registered": rulesCount,
            "facts_present": factsCount,
            "catalog_sources": catalogSources,
            "catalog_tables": catalogTables,
            "enterprise_sources_configured": sourcesConfigured,
            "enterprise_sources_enabled": sourcesEnabled,
        },
        "knowledge_ready": bool(termsCount > 0 and factsCount > 0),
        "data_ready": bool(catalogSources > 0 and sourcesEnabled > 0),
    }
