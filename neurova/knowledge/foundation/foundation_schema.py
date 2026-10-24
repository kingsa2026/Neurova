"""`knowledge_foundation` 版本域的单主注册处。

为什么要有这个文件：`db_migration.register_migration` 要求同一版本域内版本号**按注册序
严格递增**，而一个 SQLite 文件只有一个 `user_version` 整数——所以"一个库文件 = 一个版本域
= 一个注册顺序"。本域的迁移本来分散在 `knowledge_facts`（v1–v3）与 `narratives`（v4）里，
加进 v5 之后两条注册序一定会互撞（实测在导入期直接 ValueError）。

规矩：**往本域加迁移只改这个文件**，SQL 仍由各自的模块持有；版本号只增不减，
已发布的版本号与其 SQL 文本永不改写（零停机迁移纪律）。
"""

from __future__ import annotations

from typing import List

from neurova.core.db_migration import migrate as applyMigrations, register_migration

from .knowledge_facts import (
    _SCHEMA,
    _SCHEMA_V2,
    _SCHEMA_V3,
    _SCHEMA_V5,
    _SCHEMA_V13,
    _SCHEMA_V14,
    _SCHEMA_V15,
    _SCHEMA_V16,
    _SCHEMA_V17,
    _SCHEMA_V18,
    _SCHEMA_V19,
    _SCHEMA_V20,
    _SCHEMA_V21,
    _SCHEMA_V22,
    _SCHEMA_V23,
)
from .digest_chain import _SCHEMA_V11
from ..ontology.derivation_ledger import _SCHEMA_V10
from ..ontology.rule_engine import _SCHEMA_V9
from ..ontology.term_registry import _SCHEMA_V8, _SCHEMA_V12
from .narratives import NARRATIVE_DOMAIN, _SCHEMA_V4, _SCHEMA_V6, _SCHEMA_V7

_STEPS: List[tuple] = [
    (1, _SCHEMA),
    (2, _SCHEMA_V2),
    (3, _SCHEMA_V3),
    (4, _SCHEMA_V4),
    (5, _SCHEMA_V5),
    (6, _SCHEMA_V6),
    (7, _SCHEMA_V7),
    (8, _SCHEMA_V8),
    (9, _SCHEMA_V9),
    (10, _SCHEMA_V10),
    (11, _SCHEMA_V11),
    # v12：谓词值域可按类别声明（`range_kinds`）——`is_a` 的客体合法性随类型表增长自动跟随
    (12, _SCHEMA_V12),
    # v13：条目擦除的落点（批次 K2）——断言行留在链上，正文置空并打 `erased_at` 标记
    (13, _SCHEMA_V13),
    # v14：按知识命中的 token 归因（均分，attribution 注明）
    (14, _SCHEMA_V14),
    # v15：每轮唯一 turn_id + 成本阶段（修复同会话第二轮被 v14 幂等跳过）
    (15, _SCHEMA_V15),
    # v16：每轮总量/已归因/未归因摘要（引用/加权/均分之外的部分不丢）
    (16, _SCHEMA_V16),
    # v17：检索侧未归因 token（文档命中不能摊到 fact，但成本总数不丢）
    (17, _SCHEMA_V17),
    # v18：entry 级 token 账（文档条目与 fact 分表；轮总量加 entry_attributed_tokens）
    (18, _SCHEMA_V18),
    # v19：事实变更历史（create/supersede/retract/expire/revive/rollback）与业务基线
    (19, _SCHEMA_V19),
    # v20：租户分区（事实/活动列 + 唯一索引带 tenant）
    (20, _SCHEMA_V20),
    # v21：事实冲突账按租户分区
    (21, _SCHEMA_V21),
    # v22：业务基线按租户分区
    (22, _SCHEMA_V22),
    # v23：主体消解字典按租户分区
    (23, _SCHEMA_V23),
]

_registered = False


def ensureRegistered() -> None:
    """按版本号升序注册整条链。重复调用幂等（注册表本身也挡重复版本）。"""
    global _registered
    if _registered:
        return
    for version, step in sorted(_STEPS, key=lambda t: t[0]):
        register_migration(version, step, domain=NARRATIVE_DOMAIN)
    _registered = True


def applyTo(conn) -> List[int]:
    """把链应用到给定连接上（各存储构造时调用）。"""
    ensureRegistered()
    return applyMigrations(conn, NARRATIVE_DOMAIN)
