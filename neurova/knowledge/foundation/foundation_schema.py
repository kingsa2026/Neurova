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
    _SCHEMA_V24,
    _SCHEMA_V25,
    _SCHEMA_V26,
    _SCHEMA_V27,
)
from .digest_chain import _SCHEMA_V11
from ..categories_registry import _SCHEMA_V38_CATEGORIES
from ..enterprise.schema_mapping import SCHEMA_V34 as _SCHEMA_V34_ENTERPRISE
from ..fts_index import _SCHEMA_V37_FTS
from ..ontology.action_registry import _SCHEMA_V42_ACTIONS, _SCHEMA_V45_ACTION_SEMANTICS
from ..ontology.change_log import _SCHEMA_V33
from ..ontology.function_registry import _SCHEMA_V43_FUNCTIONS
from ..community_graph import _SCHEMA_V48_COMMUNITIES
from ..enterprise.webhook_receiver import _SCHEMA_V49_WEBHOOK_DEDUP
from ..ontology.artifact_store import _SCHEMA_V50_ARTIFACTS
from ..ontology.decision_ledger import _SCHEMA_V47_DECISIONS
from ..ontology.simulation import _SCHEMA_V46_SIMULATIONS
from ..ontology.state_machine_registry import _SCHEMA_V44_STATE_MACHINES
from ..ontology.derivation_ledger import _SCHEMA_V10
from ..ontology.relation_candidates import _SCHEMA_V29_CANDIDATES
from ..ontology.rule_engine import _SCHEMA_V28, _SCHEMA_V35, _SCHEMA_V9
from ..ontology.shapes import _SCHEMA_V31_SHAPES
from ..ontology.term_registry import (
    _SCHEMA_V29_TERMS,
    _SCHEMA_V30_TERMS,
    _SCHEMA_V31_TERMS,
    _SCHEMA_V32_TERMS,
    _SCHEMA_V39_EXTERNAL_IRI,
    _SCHEMA_V40_TERMS,
    _SCHEMA_V41_TERMS,
    _SCHEMA_V8,
    _SCHEMA_V12,
)
from .knowledge_facts import _SCHEMA_V36
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
    # v24：事实带条目分类（基线 category 维度）
    (24, _SCHEMA_V24),
    # v25：本体按租户分区（已拍板），两表重建为 (tenant_id, id) 复合主键
    (25, _SCHEMA_V25),
    # v26：MCP 信息源配置表（B 方案）
    (26, _SCHEMA_V26),
    # v27：检索脱靶登记（specs/2026-10-30 W2）——候选别名只进人工审批面
    (27, _SCHEMA_V27),
    # v28：条件类规则（specs/2026-11-05 B1）——ontology_rules 带形状（relay/conjunction）
    #      与 head 客体常量；relay 为缺省，存量行零漂移
    (28, _SCHEMA_V28),
    # v29：关系映射层（specs/2026-11-05 B8）——术语表加关系特征/别名/外部 IRI 列
    #      ＋未知关系候选表；加列不删列，可回滚
    (29, _SCHEMA_V29_TERMS + "\n" + _SCHEMA_V29_CANDIDATES),
    # v30：身份判据（specs/2026-11-05 B9 L1）——类型级 identity_keys
    (30, _SCHEMA_V30_TERMS),
    # v31：SKOS 多语言/模块化（specs/2026-11-05 B10 L2）——labels/alt_labels/module/
    #      namespace/iri_base ＋形状注册表 ontology_shapes（L4，写入前/dry-run 同求值器）
    (31, _SCHEMA_V31_TERMS + "\n" + _SCHEMA_V31_SHAPES),
    # v32：限定关系 schema（specs/2026-11-05 B11 L3）——qualifier 键/类型/必填
    (32, _SCHEMA_V32_TERMS),
    # v33：本体变更审计账（specs/2026-11-05 B12 L8）——只追加，不删除
    (33, _SCHEMA_V33),
    # v34：企业源配置表（specs/2026-11-05 B14）——接口预留，默认关
    (34, _SCHEMA_V34_ENTERPRISE),
    # v35：物化档位（specs/2026-11-05 B11 §12.6 设计 3）——ontology_rules 加
    #      materialization（observe/enforce）；缺省 observe，存量行零行为漂移
    (35, _SCHEMA_V35),
    # v36：facts 侧源钟（K-09，台账 §6-570 裁定 2026-11-07）——knowledge_facts 加
    #      source_created_at/source_modified_at 两列；无源时间回退 recorded_at，
    #      valid_from 职责不动（temporal 分类与窗口判定照旧）
    (36, _SCHEMA_V36),
    # v37：FTS 搬主库（K-09，2026-11-07 裁定：FTS 搬进主库）——knowledge_fts_docs/
    #      knowledge_fts 虚表归 foundation 版本域，独立 knowledge_fts.db 与
    #      fts_index 自建 DDL 退役；docs 表带 source_modified_at（同分 tie-break 消费）
    (37, _SCHEMA_V37_FTS),
    # v38：知识库自定义分类注册表（specs/2026-11-07 批 A）——受控分类清单单一事实源，
    #      分组白名单/前端下拉/导入选择全部引用；不做租户切分（部门开放由分组白名单表达）
    (38, _SCHEMA_V38_CATEGORIES),
    # v39：外部 IRI 映射结构化（GB/T 48000.3 评估档 G3 拍板 2026-11-10）——
    #      external_iris_json 从 dict 整体重构为 [{"kind": 闭集, "iri": IRI}] 列表；
    #      存量 dict 行统一转 skos_exactMatch（导出同步从替换改附加断言）
    (39, _SCHEMA_V39_EXTERNAL_IRI),
    # v40：术语 Definition 描述项（GB/T 48000.3 评估档 G1）——表 1/表 2 必要项，
    #      quality「缺定义」判据的消费源；导出面非空才出断言
    (40, _SCHEMA_V40_TERMS),
    # v41：数据属性基本数据类型（GB/T 48000.3 评估档 G2，5.5 表 3）——
    #      仅 kind='property' 有意义；xsd 映射在 export/owl.py
    (41, _SCHEMA_V41_TERMS),
    # v42：本体动作注册表（Ontology 接入 Agent 评估档 A4）——动作声明表
    #      （绑工具/参数模板/风险档），治理侧元数据读数，不改判定逻辑
    (42, _SCHEMA_V42_ACTIONS),
    # v43：函数层（specs/2026-11-12 §4 W2）——ontology_functions 表（可计算业务
    #      语义登记，受限 AST 表达式）＋推导账本加 source_kind 列（rule|function，
    #      函数结论与规则结论同一张账本，不建第二账本）
    (43, _SCHEMA_V43_FUNCTIONS),
    # v44：状态机（specs/2026-11-12 §5 W3）——ontology_state_machines 表
    #      （states/transitions/event_bindings 闭集登记）＋企业源
    #      sync_interval_seconds 列（interval 同步间隔，D3 最小闭合）
    (44, _SCHEMA_V44_STATE_MACHINES),
    # v45：动作语义三列（specs/2026-11-12 §6 W4）——precondition/impact/
    #      state_change（执行成功后经 admission 写 has_state）
    (45, _SCHEMA_V45_ACTION_SEMANTICS),
    # v46：推演台账（specs/2026-11-12 §7 W5）——ontology_simulations 只追加
    #      （先演后决审计互链的台账本体；推演过程零生产写）
    (46, _SCHEMA_V46_SIMULATIONS),
    # v47：决策台账（specs/2026-11-12 §8 W7，D7 必选）——ontology_decisions
    #      ＋ontology_decision_links（决策一等对象；问责台账不经事实门）
    (47, _SCHEMA_V47_DECISIONS),
    # v48：GraphRAG 工艺（specs/2026-11-12 §9 W8）——切块策略注册表
    #      ＋社区表＋术语行 conflict_policy 列（冲突策略数据化）
    (48, _SCHEMA_V48_COMMUNITIES),
    # v49：webhook 幂等去重（specs/2026-11-12 §11 W10）——
    #      unique(source_id, idempotency_key)，拒签不消耗键
    (49, _SCHEMA_V49_WEBHOOK_DEDUP),
    # v50：工件级内容地址存储（specs/2026-11-12 §18 C1/C2）——
    #      ontology_artifacts 主键＝SHA-256(content)，write-once 不可变面
    (50, _SCHEMA_V50_ARTIFACTS),
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
