# -*- coding: utf-8 -*-
"""租户过滤统一助手（S5 集中化，拍板 D-S3：试点三处、行为逐字节一致）。

租户过滤此前散落 31 文件 192 处、三种形态，本模块先收拢三种形态的共性：
  - 形态一 SQL 拼接（core/agent_run_store.py list_runs_for_audit）→ tenant_sql_where
  - 形态二 内存谓词（api/endpoints/teams_api.py list_teams）→ tenant_matches
  - 形态三 行级取值比较（api/endpoints/knowledge_core.py _factStoreForTenant）→ tenant_matches

缺省语义与 api/auth.py 的身份缺省同源：无 tenant_id 落 "default"
（auth.py 本体不动，另有卡片处置）。余量 28 文件的迁移另行分批。
"""
from __future__ import annotations

from typing import Any, List, Tuple

DEFAULT_TENANT = "default"


def resolve_tenant(user: Any) -> str:
    """从 user dict/对象解析租户键；缺失/空/None 一律落 "default"。

    与迁移前各试点公式逐字节一致：str((user or {}).get("tenant_id") or "default")；
    对象形态按属性取值，缺省规则相同。
    """
    if isinstance(user, dict):
        raw = user.get("tenant_id")
    else:
        raw = getattr(user, "tenant_id", None)
    return str(raw or DEFAULT_TENANT)


def tenant_matches(user: Any, row: Any) -> bool:
    """内存/行级统一判定：row 与 user 是否同租户。

    row 为 None 时恒不匹配——调用方对"行不存在"的既有短路（如 404 不泄露
    存在性）保持不变，这里只是不再把 None 行读成 default 租户。
    """
    if row is None:
        return False
    return resolve_tenant(row) == resolve_tenant(user)


def tenant_sql_where(tenant_id: Any, alias: str = "") -> Tuple[str, List[Any]]:
    """形态一的 SQL where 片段与参数；tenant_id 空白时返回 ("", []) 表示不过滤。

    返回 ("tenant_id=?", [tenant]) 形态；alias 非空时拼作 "<alias>.tenant_id=?"。
    参数取 str(tenant_id).strip()，与迁移前拼接公式逐字节一致。
    """
    tid = str(tenant_id or "").strip()
    if not tid:
        return "", []
    column = "%s.tenant_id" % alias if alias else "tenant_id"
    return "%s=?" % column, [tid]
