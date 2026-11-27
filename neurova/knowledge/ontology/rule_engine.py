"""Datalog 形状的前向链（工单 021，G09）：规则是数据，推理可解释。

明确不做（写在这里，免得后来者以为是"还没做完"）：SPARQL 文本查询、OWL DL 完整语义、
外部推理服务、任意嵌套聚合。规则形状固定为一个 Datalog 片段：

    head(X, Z) :- body1(X, Y), body2(Y, Z)          # 二元接力
    head(X, Y) :- body(X, Y)                        # 直接搬移
    head(X, Z) :- body1(X, Y), body2(Y, Z), not body3(X, Z)   # 带否定的分层规则
    传递闭包 = 同一谓词自接力的特例，交给 SQLite 递归 CTE，不在 Python 里迭代到不动点

为什么是这个片段：底座的事实就是 (主体, 谓词, 客体) 三元组，任何"多跳结论"都能写成
三元组上的接力；超出这个形状的规则（聚合、算术、存在量化的新实体）需要的不是推理引擎
而是函数层，那是另一件事，不该偷偷塞进规则语言里。

分层与否定：**否定只能指向本层之前已经算完的谓词**。绕过层序就会推出
"A 且 非 A"这种双结论，而双结论在治理层是两条 active 事实互相矛盾——
比没有推导更糟。所以注册时算层、循环即报错并指出环在哪。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .term_registry import IS_A_PREDICATE
from ..foundation.knowledge_facts import KnowledgeFactStore
from neurova.core.time_utils import nowIso as _now
from neurova.core.tenant_scope import tenant_sql_where

_SCHEMA_V9 = """
CREATE TABLE IF NOT EXISTS ontology_rules (
    rule_id TEXT PRIMARY KEY,
    head_predicate TEXT NOT NULL,
    head_subject_var TEXT NOT NULL,
    body_json TEXT NOT NULL DEFAULT '[]',
    negated_predicates TEXT NOT NULL DEFAULT '[]',
    stratification_level INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_head ON ontology_rules(head_predicate, enabled);
"""

# v28：条件类（specs/2026-11-05 B1）——规则行带形状与 head 客体常量。
# relay（既有接力形状）为缺省值；conjunction 是"同主体合取"：全部正原子共享 head
# 主语变元、客体钉死为常量（body 原子里的 objectConst），head 客体也是常量
# （head_object_const）。语义即 `X is_a 条件类 :- X is_a Base, X <谓词> <常量>`。
_SCHEMA_V28 = """
ALTER TABLE ontology_rules ADD COLUMN shape TEXT NOT NULL DEFAULT 'relay';
ALTER TABLE ontology_rules ADD COLUMN head_object_const TEXT NOT NULL DEFAULT '';
"""

_VAR = re.compile(r"^[A-Z]$")
_TERM_KINDS_IN_BODY = ("atom", "not")

# v35：物化档位（specs/2026-11-05 B11 §12.6 设计 3）——按**规则类**决定推导结论
# 是否进检索主路：observe（缺省，登记即推导但只作解释链/审计可见）/
# enforce（灰度 off 时也进主路）。缺省值取 observe ⇒ 存量行一行行为不变。
_SCHEMA_V35 = """
ALTER TABLE ontology_rules ADD COLUMN materialization TEXT NOT NULL DEFAULT 'observe';
"""

#: 档位闭集：写错一个字母就当没写过，等于偷偷把一条规则转正——所以在写入处拒。
MATERIALIZATION_MODES = ("observe", "enforce")

# v58：Rete v2 求值档（U5）——规则行带注册档位 evaluation_strategy。
# 空串＝默认语言（≤2 正原子）；rete_network＝显式放宽到 ≤3 正原子（relay 链/合取）。
# 档位只放宽 authoring，不改求值语义：同一规则在 full_replay 与 rete_network 下
# 结论集逐条相等（test_reteNetwork 对拍钉住）。
_SCHEMA_V58 = """
ALTER TABLE ontology_rules ADD COLUMN evaluation_strategy TEXT NOT NULL DEFAULT '';
"""


#: 求值策略闭集（specs/2026-11-12 §10 W9，D9：策略是数据不是第二引擎）——
#: full_replay＝既有全量重放（缺省，存量零漂移）；rete＝alpha 预筛（单原子
#: 命中缓存过滤，同一规则表同一账本同一 fireFor 契约）；rete_network（U5）＝
#: AlphaNode/BetaNode/TerminalNode 网络（rete_network.py），只换匹配段、同咽喉
#: 同账本。NEUROVA_RULE_EVALUATION_STRATEGY 翻 rete/rete_network 须等价性判据
#: （test_semiNaiveEquivalence / test_reteNetwork 对拍不齐不翻）。
EVALUATION_STRATEGIES = ("full_replay", "rete", "rete_network")


class RuleError(ValueError):
    pass


# 随装配一起落地的种子规则。存在的理由（Issue #73）：`ontology_rules` 此前 0 行，
# 前向链每轮空转——021 把引擎建齐了，却没有任何生产调用方登记过一条规则。
#
# 为什么是 `is_a` 传递而不是别的：类型断言是全库唯一由结构层固定的关系写法
# （`term_registry.IS_A_PREDICATE`），"路由器是设备、设备是硬件 ⇒ 路由器是硬件"
# 是本体最基础的一条蕴含，且它推出来的结论正好是 `validation.py` 判定义域要读的东西
# （`isSubtypeOf` 沿父类链走，`assertedTypesOf` 读 `is_a` 断言集）。
_SEED_RULES: List[Dict[str, Any]] = [
    {
        "ruleId": "is_a_transitive",
        "headPredicate": IS_A_PREDICATE,
        "body": [{"atom": IS_A_PREDICATE, "subject": "X", "object": "Y"},
                 {"atom": IS_A_PREDICATE, "subject": "Y", "object": "Z"}],
    },
]


def seedBuiltinRules(engine: "ForwardChainingEngine", tenantId: str = "default") -> int:
    """把种子规则登记进引擎。幂等：同 id 同版本已在表里就跳过，不重写。

    只在**生产装配点**被调用（`admission.productionAdmissionGate`，default 租户）
    与咽喉写入首跳（非 default 租户按本租户补种）。裸造引擎仍是空规则表——
    "种子只有一个 owner"这条判据由测试钉着，两处各落一次就成了两套规则事实源。
    """
    planted = 0
    for spec in _SEED_RULES:
        existing = engine.rule(spec["ruleId"], tenantId=tenantId)
        if existing and existing.get("version") == spec.get("version", "v1"):
            continue
        engine.registerRule(
            spec["ruleId"], spec["headPredicate"], spec["body"],
            headSubjectVar=spec.get("headSubjectVar", "X"),
            version=spec.get("version", "v1"),
            tenantId=tenantId,
        )
        planted += 1
    return planted


def _premiseIds(pairsRaw: Optional[str]) -> List[str]:
    """`GROUP_CONCAT` 出来的 `a+b,a+c` 还原成前提 id 列表（保序去重）。"""
    out: List[str] = []
    for token in str(pairsRaw or "").split(","):
        out.extend(p for p in token.split("+") if p and p not in out)
    return out


class ForwardChainingEngine:
    """规则的登记与求值。推导出的事实**经咽喉入库**，不直插 SQL。

    直插等于造出一批"没有主体消解、没有血缘、没有置信"的孤儿子——那正是 B03/G12
    要灭的病，只是换了个入口复活。
    """

    def __init__(self, store: Any, gateFactory: Any = None) -> None:
        self._store = store
        self._gateFactory = gateFactory
        import os

        raw = str(os.environ.get("NEUROVA_RULE_EVALUATION_STRATEGY")
                  or "full_replay").strip().lower()
        self._evaluationStrategy = raw if raw in EVALUATION_STRATEGIES else "full_replay"
        self._ensureTable()

    def _ensureTable(self) -> None:
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 登记 ──────────────────────────────────────────────────

    def registerRule(self, ruleId: str, headPredicate: str, body: List[Dict[str, Any]], *,
                    headSubjectVar: str = "X", enabled: bool = True,
                    version: str = "v1",
                    tenantId: str = "default",
                    headObjectConst: str = "",
                    shape: str = "",
                    materialization: str = "observe",
                    evaluationStrategy: str = "") -> Dict[str, Any]:
        """登记一条规则。形状、变量、层序在这里一次判完——坏规则进不了表。

        body 元素：`{"atom": predicate, "subject": var, "object": var}` 或
        `{"not": predicate, "subject": var, "object": var}`；条件类原子把客体钉成
        常量：`{"atom": predicate, "subject": "X", "objectConst": "Order"}`。
        规则归属租户，分层/引用/撤回都只在同租户内计算。

        形状（`shape`，缺省按入参推断：`headObjectConst` 非空即 conjunction）：
        - relay：正原子按"上一跳客体 = 下一跳主体"接力，head 客体取末原子客体；
        - conjunction：正原子共享 head 主语变元、客体全为常量，head 客体是常量
          concept 术语（语义 = 同主体合取 ⇒ `X is_a 条件类`，§5 B1）；登记即对
          存量事实触发一次推导；
        - inverse（B8）：恰好 1 个正原子，head 主语变元 = 正原子**客体**变元、
          head 客体 = 正原子主语变元——`X A Y ⇒ Y <head> X` 的变元映射由求值器
          显式落 head，反向补边不散落到消费方。

        规则归属租户，分层/引用/撤回都只在同租户内计算。

        物化档位（`materialization`，v35）：`observe` 的结论只在解释链/审计里看得见，
        检索主路按观察态排除；`enforce` 的结论即便全局灰度 `NEUROVA_CONDITION_CLASSES_ROUTE`
        仍为 off 也进主路（并照旧带 `via_derived`）。一条结论被多条规则共同推出时按
        保守侧处理——只要有任一来源是 observe 就不进（见 `test_materializationModes`）。

        注册档位（`evaluationStrategy`，v58/U5）：空串＝默认语言（≤2 个正原子）；
        `rete_network`＝显式放宽到 ≤3 个正原子（relay 链式/同主体合取）。放宽必须
        在注册时显式声明，默认语言语义不因此改变；其余取值在写入处拒。
        """
        ruleId = str(ruleId or "").strip()
        tenant = str(tenantId or "default")
        if not ruleId or not headPredicate:
            raise RuleError("rule_id 与 head 谓词都不能为空")
        # 物化档位闭集（v35，§12.6 设计 3）：拼错一个字母就当没写过，等于把一条
        # 规则偷偷转正进检索主路——这种"默认放行"的方向性错误必须在写入处挡。
        mode = str(materialization or "observe").strip() or "observe"
        if mode not in MATERIALIZATION_MODES:
            raise RuleError(
                "规则 %s 的物化档位 %r 不在闭集（%s）"
                % (ruleId, mode, " / ".join(MATERIALIZATION_MODES)))
        # 注册档位（U5）：3 原子放宽只在 rete_network 档，且必须显式声明——
        # 默认语言（空档位）语义不动，拼错档位名不许被当成"没写过"放行。
        tier = str(evaluationStrategy or "").strip()
        if tier and tier not in EVALUATION_STRATEGIES:
            raise RuleError(
                "规则 %s 的注册档位 %r 不在闭集（%s）"
                % (ruleId, tier, " / ".join(EVALUATION_STRATEGIES)))
        if tier and tier != "rete_network":
            raise RuleError(
                "规则 %s 的注册档位只能是 rete_network（3 原子放宽仅该档），收到 %r"
                % (ruleId, tier))
        headConst = str(headObjectConst or "").strip()
        shape = str(shape or "").strip() or ("conjunction" if headConst else "relay")
        if shape not in ("relay", "conjunction", "inverse"):
            raise RuleError("未知规则形状 %r（有效值: relay / conjunction / inverse）" % shape)
        if shape == "conjunction" and not headConst:
            raise RuleError("规则 %s 的 conjunction 形状缺 headObjectConst" % ruleId)
        if shape != "conjunction" and headConst:
            raise RuleError(
                "规则 %s 的 headObjectConst 只属于 conjunction 形状，收到 %s" % (ruleId, shape))
        atoms = self._parseBody(ruleId, body)
        positive = [a for a in atoms if a["kind"] == "atom"]
        negated = [a for a in atoms if a["kind"] == "not"]
        if not positive:
            raise RuleError("规则 %s 没有任何肯定正文——没有依据的推导不叫推理" % ruleId)
        atomLimit = 3 if tier == "rete_network" else 2
        if len(positive) > atomLimit:
            if atomLimit == 2:
                raise RuleError("规则 %s 正文超过 2 个原子；本引擎是三元组接力片段，"
                                "更长链条请写成多条规则逐层推" % ruleId)
            raise RuleError("规则 %s 正文超过 3 个原子；rete_network 档最多 3 个正原子，"
                            "更长链条请写成多条规则逐层推" % ruleId)
        if shape == "inverse":
            if len(positive) != 1:
                raise RuleError("规则 %s 的 inverse 形状恰好 1 个正原子，收到 %d"
                                % (ruleId, len(positive)))
            if headSubjectVar != positive[0]["object"]:
                raise RuleError(
                    "规则 %s 的 inverse 形状要求 head 主语变元 = 正原子客体变元"
                    "（%r），收到 %r" % (ruleId, positive[0]["object"], headSubjectVar))
        elif shape == "conjunction":
            self._validateConditionClass(ruleId, headPredicate, headConst,
                                         positive, negated, headSubjectVar, tenantId=tenant)
        else:
            # relay 链式：逐跳要求"上一跳客体 = 下一跳主体"（2 原子是既有判据，
            # 3 原子只在 rete_network 档放行，接法判据同源）
            for i in range(len(positive) - 1):
                if positive[i]["object"] != positive[i + 1]["subject"]:
                    raise RuleError("规则 %s 的两个原子接不上（%s 与 %s 不是同一个变元）"
                                    % (ruleId, positive[i]["object"],
                                       positive[i + 1]["subject"]))
            if positive[-1]["object"] not in {headSubjectVar} | {a["object"] for a in positive}:
                raise RuleError("规则 %s 的 head 客体未在正文中出现" % ruleId)
            for atom in atoms:
                if not _VAR.match(atom["subject"]) or not _VAR.match(atom["object"]):
                    raise RuleError("规则 %s 的变元必须是单个大写字母，收到 %s"
                                    % (ruleId, (atom["subject"], atom["object"])))

        stratum, cycles = self._stratify(ruleId, headPredicate,
                                        [a["predicate"] for a in negated],
                                        [a["predicate"] for a in positive],
                                        tenantId=tenant)
        stamp = _now()
        with self._store._lock, self._store._conn:
            existClause, existParams = tenant_sql_where(tenant)
            existing = self._store._conn.execute(
                "SELECT created_at, version FROM ontology_rules"
                " WHERE %s AND rule_id = ?" % existClause,
                (*existParams, ruleId)).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO ontology_rules (tenant_id, rule_id, head_predicate,"
                " head_subject_var, body_json, negated_predicates, stratification_level,"
                " enabled, version, created_at, updated_at, shape, head_object_const,"
                " materialization, evaluation_strategy)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tenant, ruleId, headPredicate, headSubjectVar, json.dumps(body, ensure_ascii=False),
                 json.dumps(sorted({a["predicate"] for a in negated}), ensure_ascii=False),
                 stratum, 1 if enabled else 0, version,
                 existing["created_at"] if existing else stamp, stamp, shape, headConst,
                 mode, tier),
            )
            if cycles:
                self._dropRule(ruleId, tenantId=tenant)
        if cycles:
            raise RuleError("规则 %s 经由否定形成循环，分层无解：%s" % (ruleId, " → ".join(cycles)))
        if existing and existing["version"] != version:
            # 改版即旧版结论作废：留着就是两版规则各推一套、同时对外检索。
            self._store._derivationLedger.retractRuleVersion(
                ruleId, keepVersion=version, tenantId=tenant)
        if headConst and enabled:
            # 事务外触发：推导照旧走咽喉，观察态过滤在检索读侧（不在写入侧拦）。
            self._fireConditionClassAcrossAgents(ruleId, tenantId=tenant)
        return self.rule(ruleId, tenantId=tenant) or {}

    def _validateConditionClass(self, ruleId: str, headPredicate: str, headConst: str,
                                positive: List[Dict[str, str]],
                                negated: List[Dict[str, str]],
                                headSubjectVar: str, tenantId: str = "default") -> None:
        """条件类的 authoring 闸：形状与术语登记在这里一次判完。

        术语必须已登记才许建规则——规则是作者刻意写下的工件，不是待收编的枚举；
        这与事实校验的"未登记≠违规"保守原则分工不同（`validation.py` 面向事实，
        规则面向作者）。
        """
        if headPredicate != IS_A_PREDICATE:
            raise RuleError(
                "规则 %s 的条件类 head 必须是类型断言 %r，收到 %r"
                % (ruleId, IS_A_PREDICATE, headPredicate))
        for atom in positive:
            if not _VAR.match(atom["subject"]) or atom["subject"] != headSubjectVar:
                raise RuleError(
                    "规则 %s 条件类正原子的主语必须是 head 变元 %r，收到 %s"
                    % (ruleId, headSubjectVar, atom["subject"]))
            if atom["object"]:
                raise RuleError(
                    "规则 %s 条件类正原子的客体必须是常量（objectConst），不许变元" % ruleId)
            if not atom["objectConst"]:
                raise RuleError("规则 %s 条件类正原子缺 objectConst" % ruleId)
        for atom in negated:
            if atom["subject"] != headSubjectVar or not atom["objectConst"]:
                raise RuleError(
                    "规则 %s 条件类的否定原子也必须钉在同主体与常量客体上" % ruleId)
        registry = self._conditionRegistry()
        headTerm = registry.term(headConst, tenantId=tenantId)
        if headTerm is None or headTerm.get("kind") != "concept":
            raise RuleError(
                "条件类 %s 未登记为 concept 术语（先登记类型，再建规则）" % headConst)
        for atom in list(positive) + list(negated):
            if registry.term(atom["predicate"], tenantId=tenantId) is None:
                raise RuleError("规则 %s 的正文谓词 %s 未登记" % (ruleId, atom["predicate"]))
            if atom["predicate"] == IS_A_PREDICATE and \
                    registry.term(atom["objectConst"], tenantId=tenantId) is None:
                raise RuleError("规则 %s 的基类 %s 未登记" % (ruleId, atom["objectConst"]))

    def _conditionRegistry(self):
        """术语注册表的惰性缓存（规则登记期检查用；构造幂等补种，无副作用）。"""
        cached = getattr(self, "_registryCache", None)
        if cached is None:
            from .term_registry import OntologyTermRegistry

            cached = OntologyTermRegistry(self._store)
            self._registryCache = cached
        return cached

    def _fireConditionClassAcrossAgents(self, ruleId: str,
                                        tenantId: str = "default") -> None:
        """登记后对存量事实逐 agent 触发一次。推导按 agent 隔离（admit 的 agentId
        是事实属主），跨 agent 的合取不许折进一个 default 里。"""
        rule = self.rule(ruleId, tenantId=tenantId)
        if not rule or not rule.get("enabled"):
            return
        preds = sorted({a["predicate"] for a in rule["body"] if a["predicate"]})
        with self._store._lock:
            agentsClause, agentsParams = tenant_sql_where(tenantId)
            currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
            agents = [r["agent_id"] for r in self._store._conn.execute(
                "SELECT DISTINCT agent_id FROM knowledge_facts"
                " WHERE %s AND predicate_term_id IN (%s) AND %s"
                % (agentsClause, ",".join("?" * len(preds)), currentClause),
                [*agentsParams, *preds, *currentParams]).fetchall()]
        for agentId in agents:
            self._fireRule(rule, agentId, tenantId=tenantId)

    def _dropRule(self, ruleId: str, tenantId: str = "default") -> None:
        with self._store._lock, self._store._conn:
            dropClause, dropParams = tenant_sql_where(str(tenantId or "default"))
            self._store._conn.execute(
                "DELETE FROM ontology_rules WHERE %s AND rule_id = ?" % dropClause,
                (*dropParams, ruleId))

    @staticmethod
    def toAuthoringBody(hydratedBody: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把读面形状（`_hydrate` 出的 kind/predicate）换回写面形状（atom/not）。

        PUT 改版"未提供 body 就保留现值"取的是读面那一份，直接回灌 `_parseBody`
        会被判成"原子必须是 atom 或 not"——同一条规则改版即 400，而这 400 长得像
        "调用方传了坏 body"，看不出来是读写两套形状在互相咬。
        """
        authoring: List[Dict[str, Any]] = []
        for atom in hydratedBody or []:
            key = "not" if str(atom.get("kind") or "") == "not" else "atom"
            entry: Dict[str, Any] = {key: atom.get("predicate", ""),
                                     "subject": atom.get("subject", "")}
            if atom.get("object"):
                entry["object"] = atom["object"]
            if atom.get("objectConst"):
                entry["objectConst"] = atom["objectConst"]
            authoring.append(entry)
        return authoring

    @staticmethod
    def _parseBody(ruleId: str, body: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        atoms: List[Dict[str, str]] = []
        for item in body or []:
            keys = set(item) - {"subject", "object", "objectConst"}
            if keys != {"atom"} and keys != {"not"}:
                raise RuleError("规则 %s 的正文元素必须是 atom 或 not 之一，收到 %s"
                                % (ruleId, sorted(keys)))
            predicate = str(item.get("atom") or item.get("not") or "").strip()
            if not predicate:
                raise RuleError("规则 %s 有正文原子的谓词为空" % ruleId)
            atoms.append({"kind": "atom" if "atom" in item else "not",
                          "predicate": predicate,
                          "subject": str(item.get("subject", "")),
                          "object": str(item.get("object", "")),
                          "objectConst": str(item.get("objectConst", ""))})
        return atoms

    def _stratify(self, ruleId: str, headPredicate: str, negated: List[str],
                  positive: List[str], tenantId: str = "default") -> Tuple[int, List[str]]:
        """层号 = 依赖链上最长的正边；否定边要求被否定谓词在**更浅**的层。"""
        rules = self.rules(includeDisabled=False, tenantId=tenantId)
        producers: Dict[str, List[str]] = {}
        for rule in rules:
            producers.setdefault(rule["head_predicate"], []).append(rule["rule_id"])
        producers.setdefault(headPredicate, []).append(ruleId)

        levelOf = self._levels(producers)
        if levelOf.get(headPredicate, 0) < 0:
            # 层号算不出＝谓词在正边上成环。正环不是分层无解：传递闭包本来就是
            # 自己定义自己的正环，收敛方式是求不动点。只有这一条规则自己还带否定
            # 时，环才真的无解（绕经否定的环会推出 A 且 非 A）。
            return 0, ([headPredicate, headPredicate] if negated else [])
        level = levelOf.get(headPredicate, 0)
        for target in negated:
            targetLevel = levelOf.get(target)
            if targetLevel is not None and targetLevel >= level:
                return level, [headPredicate, "not", target]
        return level, []

    def _levels(self, producers: Dict[str, List[str]]) -> Dict[str, int]:
        """谓词层号：正边取 max(依赖)+1；遇到回边返回 -1 标记成环。"""
        levels: Dict[str, int] = {}
        visiting: List[str] = []

        def resolve(predicate: str) -> int:
            if predicate in levels and levels[predicate] >= 0:
                return levels[predicate]
            if predicate in visiting:
                levels[predicate] = -1
                return -1
            visiting.append(predicate)
            best = 0
            for rule in self.rules(includeDisabled=False):
                if rule["head_predicate"] != predicate:
                    continue
                for dep in rule["depends_on"]:
                    value = resolve(dep)
                    if value < 0:
                        best = -1
                        break
                    best = max(best, value + 1)
                if best < 0:
                    break
            visiting.pop()
            levels[predicate] = best
            return best

        for predicate in list(producers):
            resolve(predicate)
        return levels

    def rule(self, ruleId: str, tenantId: str = "default") -> Optional[Dict[str, Any]]:
        with self._store._lock:
            getClause, getParams = tenant_sql_where(str(tenantId or "default"))
            row = self._store._conn.execute(
                "SELECT * FROM ontology_rules WHERE %s AND rule_id = ?" % getClause,
                (*getParams, ruleId)).fetchone()
        return self._hydrate(row) if row else None

    def rules(self, includeDisabled: bool = True,
              tenantId: str = "default") -> List[Dict[str, Any]]:
        tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
        sql = "SELECT * FROM ontology_rules WHERE " + tenantClause
        params: List[Any] = list(tenantParams)
        if not includeDisabled:
            sql += " AND enabled = 1"
        sql += " ORDER BY stratification_level, rule_id"
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()
        return [self._hydrate(r) for r in rows]

    def ensureRuleSeeds(self, tenantId: str = "default") -> int:
        """非 default 租户的种子在写入首跳幂等补齐：一次计数查询挡住逐条重复判。"""
        with self._store._lock:
            seedClause, seedParams = tenant_sql_where(str(tenantId or "default"))
            n = self._store._conn.execute(
                "SELECT COUNT(*) AS n FROM ontology_rules WHERE %s" % seedClause,
                seedParams).fetchone()["n"]
        if int(n) > 0:
            return 0
        return seedBuiltinRules(self, tenantId=tenantId)

    def ruleReferences(self, predicate: str, tenantId: str = "default") -> List[str]:
        """谓词被哪些规则引用（head 或正文原子）——影响分析的规则维度。"""
        predicate = str(predicate or "")
        out = []
        for rule in self.rules(includeDisabled=True, tenantId=tenantId):
            if rule["head_predicate"] == predicate:
                out.append(rule["rule_id"])
                continue
            for atom in rule.get("body") or []:
                if atom.get("predicate") == predicate:
                    out.append(rule["rule_id"])
                    break
        return sorted(out)

    def dropRule(self, ruleId: str, reason: str = "", tenantId: str = "default") -> None:
        """删除规则并撤回它推过的全部结论——规则没了，它的推导不能还在对外检索。"""
        ruleId = str(ruleId or "").strip()
        tenant = str(tenantId or "default")
        with self._store._lock:
            findClause, findParams = tenant_sql_where(tenant)
            row = self._store._conn.execute(
                "SELECT rule_id FROM ontology_rules WHERE %s AND rule_id = ?" % findClause,
                (*findParams, ruleId)).fetchone()
        if row is None:
            raise LookupError("规则未登记: %s" % ruleId)
        self._store._derivationLedger.retractAllFromRule(
            ruleId, reason or "规则 %s 已删除" % ruleId, tenantId=tenant)
        self._dropRule(ruleId, tenantId=tenant)

    @staticmethod
    def _hydrate(row) -> Dict[str, Any]:
        d = dict(row)
        raw = json.loads(d.pop("body_json") or "[]")
        # 存的是用户写的形状，读出来统一成判定用的形状（kind + predicate）——
        # 两处各认各的键，就会一个能注册、另一个永远匹配不上。
        # objectConst 是条件类（v28）的常量客体：relay 原子里恒为空串。
        d["body"] = [{"kind": "atom" if "atom" in a else "not",
                      "predicate": str(a.get("atom") or a.get("not") or ""),
                      "subject": str(a.get("subject", "")),
                      "object": str(a.get("object", "")),
                      "objectConst": str(a.get("objectConst", ""))} for a in raw]
        d["negated_predicates"] = json.loads(d.get("negated_predicates") or "[]")
        d["depends_on"] = sorted({a["predicate"] for a in d["body"] if a["predicate"]})
        d["enabled"] = bool(d.get("enabled"))
        # v28 之前落库的行没有这两列：缺省回 relay 形状，存量语义零漂移。
        d["shape"] = str(d.get("shape") or "relay")
        d["head_object_const"] = str(d.get("head_object_const") or "")
        # v35 之前落库的行同理：缺省 observe ⇒ 存量规则一律留在观察态。
        d["materialization"] = str(d.get("materialization") or "observe")
        # v58 之前落库的行没有这一列：缺省空串＝默认语言（≤2 个正原子）。
        d["evaluation_strategy"] = str(d.get("evaluation_strategy") or "")
        return d

    # ── 求值 ──────────────────────────────────────────────────

    @property
    def evaluationStrategy(self) -> str:
        return self._evaluationStrategy

    def setEvaluationStrategy(self, strategy: str) -> None:
        """切换求值策略（闭集校验；同规则表同账本同契约——结论集等价性由
        test_semiNaiveEquivalence 钉住）。"""
        strategy = str(strategy or "").strip().lower()
        if strategy not in EVALUATION_STRATEGIES:
            raise ValueError(
                "求值策略 %r 不在闭集 %s" % (strategy, "/".join(EVALUATION_STRATEGIES)))
        self._evaluationStrategy = strategy

    def fireAll(self, agentId: Optional[str] = None, maxIterations: int = 10,
                tenantId: str = "default") -> Dict[str, Any]:
        """按层号升序反复求值到不动点。返回每轮新增，0 新增即停。

        W9 semi-naive 增量：首轮全量，此后每轮只点燃 body 依赖谓词与上一轮
        delta 相交的规则（deltaPredicates 过滤）——结论集与全量重放逐字一致
        （等价性判据 test_semiNaiveEquivalence 钉住）。rete 策略＝alpha 单原子
        命中预筛（每轮先查各原子谓词有无事实，零命中的规则跳过）。"""
        tenant = str(tenantId or "default")
        # B8：每轮求值前把术语表上的关系特征幂等对齐成 auto_* 规则（声明即推理）。
        self.ensureAutoRules(tenantId=tenant)
        rounds: List[int] = []
        derived: List[str] = []
        deltaPredicates: Optional[set] = None  # None＝首轮全量
        network = None
        if self._evaluationStrategy == "rete_network":
            # U5：网络跨轮复用——TerminalNode 的激活去重集合覆盖整个 fireAll，
            # 同一（规则, 绑定）即使被后续 delta 轮重新匹配也不重复点火。
            from .rete_network import ReteNetwork

            network = ReteNetwork(self)
        for _ in range(max(int(maxIterations), 1)):
            produced = self._oneRound(agentId, tenantId=tenant,
                                      deltaPredicates=deltaPredicates, network=network)
            rounds.append(len(produced))
            if not produced:
                break
            derived.extend(produced)
            deltaPredicates = set(
                self.predicateOf(factId) for factId in produced)
        return {"derived": derived, "rounds": rounds,
                "iterations": len(rounds),
                "rules": [r["rule_id"] for r in self.rules(tenantId=tenant)]}

    def predicateOf(self, factId: str) -> str:
        fact = self._store.fact(factId)
        return str((fact or {}).get("predicate_term_id") or "")

    def fireFor(self, agentId: str, predicate: str,
                tenantId: str = "default") -> List[str]:
        """新事实落下后只点燃用得到它的规则——每写一条就全量重放到不动点，
        成本随事实数线性放大，那条路在对话链上不可接受。"""
        produced: List[str] = []
        for rule in sorted(self.rules(includeDisabled=False, tenantId=tenantId),
                           key=lambda r: (r["stratification_level"], r["rule_id"])):
            if predicate not in rule["depends_on"]:
                continue
            produced.extend(self._fireRule(rule, agentId, tenantId=tenantId))
        return produced

    def _oneRound(self, agentId: Optional[str], tenantId: str = "default",
                  deltaPredicates: Optional[set] = None,
                  network: Any = None) -> List[str]:
        # rete_network（U5）：整轮交给 Rete 网络——同一规则表同一咽喉，只换匹配段。
        if network is not None:
            # U14 同根因扫荡（教义第 5 条）：网络路径不经 _fireRule，否定退役
            # 必须同拍执行——否定前提已成立的既有结论先退场，再求值新增结论
            # （与 SQL 路径逐规则同一口径），增量态才停在分层不动点上。
            for rule in self.rules(includeDisabled=False, tenantId=tenantId):
                if any(a.get("kind") == "not" for a in rule.get("body") or []):
                    self._retireNegationBlocked(rule, tenantId=tenantId)
            return network.runRound(agentId=agentId, tenantId=tenantId,
                                    deltaPredicates=deltaPredicates)
        produced: List[str] = []
        allRules = sorted(self.rules(includeDisabled=False, tenantId=tenantId),
                          key=lambda r: (r["stratification_level"], r["rule_id"]))
        for rule in allRules:
            # semi-naive：非首轮只点燃 body 依赖谓词与 delta 相交的规则
            if deltaPredicates is not None and not (
                    set(rule["depends_on"]) & deltaPredicates):
                continue
            # rete：alpha 单原子命中预筛（零命中规则跳过——SQL 一次 COUNT）
            if self._evaluationStrategy == "rete" and not self._alphaHasMatches(
                    rule, agentId, tenantId):
                continue
            produced.extend(self._fireRule(rule, agentId, tenantId=tenantId))
        return produced

    def _alphaHasMatches(self, rule: Dict[str, Any], agentId: Optional[str],
                         tenantId: str) -> bool:
        """rete alpha 节点：规则 body 各原子的谓词在域内是否有 active 事实
        （单次 COUNT 命中即真——零命中规则跳过整轮求值）。"""
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
        alphaTenantClause, alphaTenantParams = tenant_sql_where(tenantId)
        for atom in rule.get("body") or []:
            pred = str(atom.get("predicate") or atom.get("atom") or "")
            if not pred:
                continue
            if str(atom.get("kind") or "atom") == "not":
                continue  # 否定原子反向命中不做 alpha 预筛（保守全量）
            sql = ("SELECT 1 FROM knowledge_facts WHERE predicate_term_id = ?"
                   " AND %s AND record_kind = 'triple'" % currentClause)
            params: List[Any] = [pred, *currentParams]
            if agentId:
                sql += " AND agent_id = ?"
                params.append(agentId)
            if alphaTenantClause:
                sql += " AND " + alphaTenantClause
                params.extend(alphaTenantParams)
            sql += " LIMIT 1"
            with self._store._lock:
                if self._store._conn.execute(sql, params).fetchone() is not None:
                    return True
        return False

    def _fireRule(self, rule: Dict[str, Any], agentId: Optional[str],
                  tenantId: str = "default") -> List[str]:
        # 分层否定的真值维护：否定前提已成立时，本规则被阻断的既有结论先退场，
        # 再求值新增结论——增量态才停在本规则的分层不动点上（U14 差分实测：
        # 否定前提晚于结论到达时，不退场就与全量重放逐条不一致）。
        self._retireNegationBlocked(rule, tenantId=tenantId)
        if rule.get("shape") == "conjunction":
            return self._fireConjunction(rule, agentId, tenantId=tenantId)
        if rule.get("shape") == "inverse":
            return self._fireInverse(rule, agentId, tenantId=tenantId)
        atoms = [a for a in rule["body"]]
        positive = [a for a in atoms if a["kind"] == "atom"]
        negated = [a for a in atoms if a["kind"] == "not"]
        params: List[Any] = []
        first, second = positive[0], (positive[1] if len(positive) > 1 else None)
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
        moment = currentParams[0]
        aCurrentClause, aCurrentParams = KnowledgeFactStore.currentFactWhere("a", now=moment)
        bCurrentClause, bCurrentParams = KnowledgeFactStore.currentFactWhere("b", now=moment)
        # KNOW-02：前提组合全链带租户——规则按租户分区，跨租户事实不得进入
        # 本租户规则的前提（否则他租户事实会推出本租户结论与血缘）。
        tenantClause, tenantParams = tenant_sql_where(tenantId)
        aTenantClause, aTenantParams = tenant_sql_where(tenantId, alias="a")
        bTenantClause, bTenantParams = tenant_sql_where(tenantId, alias="b")
        if len(positive) > 2:
            # rete_network 档放宽出的 3 原子接力链：与两原子路径同一接法逐跳 JOIN，
            # 结论集与 Rete 网络逐字一致（test_reteNetwork 对拍钉住）。
            sql, params = self._relayChainQuery(positive, agentId, tenantId=tenantId)
        elif second is None:
            scope = " AND agent_id = ?" if agentId else ""
            sql = ("SELECT subject_key, object_term, fact_id AS pair FROM knowledge_facts"
                   " WHERE predicate_term_id = ? AND %s AND record_kind = 'triple'%s AND %s"
                   % (currentClause, scope, tenantClause))
            params = ([first["predicate"], *currentParams]
                      + ([agentId] if agentId else []) + tenantParams)
        else:
            # 中项靠"上一跳的客体 = 下一跳主体的规范标签"接上。没被登记成主体的客体接不上，
            # 那是消解段（006）的活，不在推理层偷偷做字符串相似。
            scope = " AND a.agent_id = ?" if agentId else ""
            sql = ("SELECT a.subject_key AS subject_key, b.object_term AS object_term,"
                   " a.fact_id || '+' || b.fact_id AS pair"
                   " FROM knowledge_facts a"
                   " JOIN knowledge_subjects s2 ON s2.agent_id = a.agent_id"
                   "  AND s2.normalized_label = lower(trim(a.object_term)) AND s2.status = 'active'"
                   " JOIN knowledge_facts b ON b.subject_key = s2.subject_key"
                   "  AND b.agent_id = a.agent_id AND b.tenant_id = a.tenant_id"
                   " WHERE a.predicate_term_id = ? AND b.predicate_term_id = ?"
                   " AND %s AND %s AND a.record_kind = 'triple'"
                   " AND b.record_kind = 'triple'%s AND %s AND %s"
                   % (aCurrentClause, bCurrentClause, scope, aTenantClause, bTenantClause))
            params = ([first["predicate"], second["predicate"],
                       *aCurrentParams, *bCurrentParams]
                      + ([agentId] if agentId else [])
                      + aTenantParams + bTenantParams)
        sql = ("SELECT t.subject_key, t.object_term, MIN(s.canonical_label) AS label,"
               " GROUP_CONCAT(DISTINCT t.pair) AS pairs"
               " FROM (%s) t JOIN knowledge_subjects s ON s.subject_key = t.subject_key"
               " GROUP BY t.subject_key, t.object_term"
               " ORDER BY t.subject_key, t.object_term" % sql)
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()

        head = rule["head_predicate"]
        written: List[str] = []
        for row in rows:
            subjectKey, objectTerm, label = row["subject_key"], row["object_term"], row["label"]
            if self._negatedHolds(agentId, negated, subjectKey, objectTerm,
                                  tenantId=tenantId):
                continue
            factId = self._admitDerivedFact(rule, agentId, label, head, objectTerm,
                                            subjectKey, _premiseIds(row["pairs"]),
                                            tenantId=tenantId)
            if factId:
                written.append(factId)
        return written

    @staticmethod
    def _relayChainQuery(positive: List[Dict[str, str]], agentId: Optional[str],
                         tenantId: str = "default") -> Tuple[str, List[Any]]:
        """≥3 个正原子的接力链 SQL（rete_network 档放宽，登记闸限 3）。

        与两原子路径同一接法：上一跳客体按规范标签找到下一跳主体，逐跳 JOIN；
        head 主语取首原子主体、head 客体取末原子客体；agent 圈域、租户过滤
        （KNOW-02：每个 fact 别名都带 tenant 谓词）与当前事实判据同源。
        """
        from string import ascii_lowercase

        aliases = ["f%s" % c for c in ascii_lowercase[:len(positive)]]
        sql = ("SELECT %s.subject_key AS subject_key, %s.object_term AS object_term,"
               " %s AS pair FROM knowledge_facts %s"
               % (aliases[0], aliases[-1],
                  " || '+' || ".join("%s.fact_id" % a for a in aliases), aliases[0]))
        for i in range(1, len(positive)):
            prev, cur, subj = aliases[i - 1], aliases[i], "s%d" % i
            sql += (" JOIN knowledge_subjects %s ON %s.agent_id = %s.agent_id"
                    "  AND %s.normalized_label = lower(trim(%s.object_term))"
                    "  AND %s.status = 'active'"
                    " JOIN knowledge_facts %s ON %s.subject_key = %s.subject_key"
                    "  AND %s.agent_id = %s.agent_id"
                    % (subj, subj, prev, subj, prev, subj, cur, cur, subj, cur, prev))
        where = ["%s.predicate_term_id = ?" % alias for alias in aliases]
        params: List[Any] = [atom["predicate"] for atom in positive]
        moment = None
        for alias in aliases:
            if moment is None:
                currentClause, currentParams = KnowledgeFactStore.currentFactWhere(alias)
                moment = currentParams[0]
            else:
                currentClause, currentParams = KnowledgeFactStore.currentFactWhere(alias, now=moment)
            where.append(currentClause)
            where.append("%s.record_kind = 'triple'" % alias)
            params.extend(currentParams)
            aliasClause, aliasParams = tenant_sql_where(tenantId, alias=alias)
            if aliasClause:
                where.append(aliasClause)
                params.extend(aliasParams)
        if agentId:
            where.append("%s.agent_id = ?" % aliases[0])
            params.append(agentId)
        sql += " WHERE " + " AND ".join(where)
        return sql, params

    def _negatedHolds(self, agentId: Optional[str], negated: List[Dict[str, str]],
                      subjectKey: str, objectTerm: str,
                      tenantId: str = "default") -> bool:
        """否定原子求值：与 `_negatedConstHolds` / `_negatedFactExists` 同一口径，
        SQL 带 tenant 过滤（KNOW-02，否定判定不跨租户找阻断事实）。"""
        if not negated:
            return False
        for atom in negated:
            clause, negParams = tenant_sql_where(tenantId)
            currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
            params: List[Any] = [agentId or "", subjectKey, atom["predicate"],
                                 objectTerm, *currentParams, *negParams]
            with self._store._lock:
                row = self._store._conn.execute(
                    "SELECT 1 FROM knowledge_facts WHERE agent_id = ? AND subject_key = ?"
                    " AND predicate_term_id = ? AND object_term = ?"
                    " AND " + currentClause + " AND " + clause,
                    params).fetchone()
            if row:
                return True
        return False

    def _fireConjunction(self, rule: Dict[str, Any], agentId: Optional[str],
                         tenantId: str = "default") -> List[str]:
        """同主体合取求值（条件类）：全部正原子钉在同一 subject_key 上、客体为常量。

        与 relay 的分野在接法——relay 靠"上一跳客体 = 下一跳主体"接力，合取靠
        subject_key 直接对齐；前提账记合取到的每一行，撤销沿账本精确走。
        合取 SQL 全程带 tenant_id（v25 本体分区语义在推理层同样成立）。
        """
        positive = [a for a in rule["body"] if a["kind"] == "atom"]
        negated = [a for a in rule["body"] if a["kind"] == "not"]
        conjTenantClause, conjTenantParams = tenant_sql_where(tenantId)
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
        moment = currentParams[0]
        aCurrentClause, aCurrentParams = KnowledgeFactStore.currentFactWhere("a", now=moment)
        bCurrentClause, bCurrentParams = KnowledgeFactStore.currentFactWhere("b", now=moment)
        cCurrentClause, cCurrentParams = KnowledgeFactStore.currentFactWhere("c", now=moment)
        if len(positive) == 1:
            a0 = positive[0]
            inner = ("SELECT subject_key, fact_id AS pair FROM knowledge_facts"
                     " WHERE predicate_term_id = ? AND object_term = ?"
                     " AND %s AND %s AND record_kind = 'triple'"
                     % (conjTenantClause, currentClause))
            params: List[Any] = [a0["predicate"], a0["objectConst"],
                                 *conjTenantParams, *currentParams]
            if agentId:
                inner += " AND agent_id = ?"
                params.append(agentId)
        elif len(positive) == 2:
            a0, a1 = positive[0], positive[1]
            aTenantClause, aTenantParams = tenant_sql_where(tenantId, alias="a")
            bTenantClause, bTenantParams = tenant_sql_where(tenantId, alias="b")
            inner = ("SELECT a.subject_key AS subject_key,"
                     " a.fact_id || '+' || b.fact_id AS pair"
                     " FROM knowledge_facts a"
                     " JOIN knowledge_facts b ON b.subject_key = a.subject_key"
                     "  AND b.agent_id = a.agent_id AND b.tenant_id = a.tenant_id"
                     " WHERE a.predicate_term_id = ? AND a.object_term = ?"
                     "  AND %s AND %s AND a.record_kind = 'triple'"
                     "  AND b.predicate_term_id = ? AND b.object_term = ?"
                     "  AND %s AND %s AND b.record_kind = 'triple'"
                     % (aTenantClause, aCurrentClause, bTenantClause, bCurrentClause))
            params = [a0["predicate"], a0["objectConst"], *aTenantParams, *aCurrentParams,
                      a1["predicate"], a1["objectConst"], *bTenantParams, *bCurrentParams]
            if agentId:
                inner += " AND a.agent_id = ?"
                params.append(agentId)
        else:
            # rete_network 档放宽出的 3 原子同主体合取（登记闸限 3）：全部正原子
            # 钉在同一 subject_key 上、客体全为常量；同 agent 同租户的接法与
            # 两原子路径同源，结论集与 Rete 网络逐字一致。
            a0, a1, a2 = positive[0], positive[1], positive[2]
            aTenantClause, aTenantParams = tenant_sql_where(tenantId, alias="a")
            bTenantClause, bTenantParams = tenant_sql_where(tenantId, alias="b")
            cTenantClause, cTenantParams = tenant_sql_where(tenantId, alias="c")
            inner = ("SELECT a.subject_key AS subject_key,"
                     " a.fact_id || '+' || b.fact_id || '+' || c.fact_id AS pair"
                     " FROM knowledge_facts a"
                     " JOIN knowledge_facts b ON b.subject_key = a.subject_key"
                     "  AND b.agent_id = a.agent_id AND b.tenant_id = a.tenant_id"
                     " JOIN knowledge_facts c ON c.subject_key = a.subject_key"
                     "  AND c.agent_id = a.agent_id AND c.tenant_id = a.tenant_id"
                     " WHERE a.predicate_term_id = ? AND a.object_term = ?"
                     "  AND %s AND %s AND a.record_kind = 'triple'"
                     "  AND b.predicate_term_id = ? AND b.object_term = ?"
                     "  AND %s AND %s AND b.record_kind = 'triple'"
                     "  AND c.predicate_term_id = ? AND c.object_term = ?"
                     "  AND %s AND %s AND c.record_kind = 'triple'"
                     % (aTenantClause, aCurrentClause, bTenantClause, bCurrentClause,
                        cTenantClause, cCurrentClause))
            params = [a0["predicate"], a0["objectConst"], *aTenantParams, *aCurrentParams,
                      a1["predicate"], a1["objectConst"], *bTenantParams, *bCurrentParams,
                      a2["predicate"], a2["objectConst"], *cTenantParams, *cCurrentParams]
            if agentId:
                inner += " AND a.agent_id = ?"
                params.append(agentId)
        sql = ("SELECT t.subject_key, MIN(s.canonical_label) AS label,"
               " GROUP_CONCAT(DISTINCT t.pair) AS pairs"
               " FROM (%s) t JOIN knowledge_subjects s ON s.subject_key = t.subject_key"
               " GROUP BY t.subject_key"
               " ORDER BY t.subject_key" % inner)
        with self._store._lock:
            rows = self._store._conn.execute(sql, params).fetchall()

        head = rule["head_predicate"]
        headConst = str(rule.get("head_object_const") or "")
        written: List[str] = []
        for row in rows:
            subjectKey, label = row["subject_key"], row["label"]
            if self._negatedConstHolds(agentId, negated, subjectKey, tenantId=tenantId):
                continue
            factId = self._admitDerivedFact(rule, agentId, label, head, headConst,
                                            subjectKey, _premiseIds(row["pairs"]),
                                            tenantId=tenantId)
            if factId:
                written.append(factId)
        return written

    def _negatedConstHolds(self, agentId: Optional[str], negated: List[Dict[str, str]],
                           subjectKey: str, tenantId: str = "default") -> bool:
        """条件类的否定判定：每个否定原子自带常量客体，逐原子查活事实。"""
        for atom in negated:
            negTenantClause, negTenantParams = tenant_sql_where(tenantId)
            currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
            sql = ("SELECT 1 FROM knowledge_facts WHERE subject_key = ?"
                   " AND predicate_term_id = ? AND object_term = ?"
                   " AND %s AND %s" % (negTenantClause, currentClause))
            params: List[Any] = [subjectKey, atom["predicate"], atom["objectConst"],
                                 *negTenantParams, *currentParams]
            if agentId:
                sql += " AND agent_id = ?"
                params.append(agentId)
            with self._store._lock:
                row = self._store._conn.execute(sql, params).fetchone()
            if row:
                return True
        return False

    def _retireNegationBlocked(self, rule: Dict[str, Any],
                               tenantId: str = "default") -> int:
        """分层否定的真值维护（U14 差分实测暴露的缺口）：否定前提成立时，本规则
        已被它阻断的结论必须退场。

        前向链只会「加」结论：否定前提比结论后到时，先前推出的结论不会自己消失，
        增量态就不再是规则的分层不动点——全量重放推不出它，留着它就是拿着
        「否定前提已成立」的结论对外检索。这里沿账本找出本规则的活动结论，按
        `_negatedHolds` / `_negatedConstHolds` 的同一口径复查否定前提，被阻断的
        经 `store.retract` 退场（下游级联由推导账本接手）。否定前提之后再撤销时，
        常规求值经 `_renewDerived` 把结论长回来——撤销不会比故障更持久。
        """
        negated = [a for a in rule.get("body") or [] if a.get("kind") == "not"]
        if not negated:
            return 0
        tenant = str(tenantId or "default")
        retired = 0
        for factId, agentId, label in self._activeConclusionsOfRule(
                rule["rule_id"], tenant):
            if self._conclusionBlockedByNegation(rule, negated, factId,
                                                 agentId, label, tenant):
                self._store.retract(
                    factId,
                    reason="规则 %s 的否定前提已成立，结论失去推导依据" % rule["rule_id"])
                retired += 1
        return retired

    def _activeConclusionsOfRule(self, ruleId: str,
                                 tenantId: str) -> List[Tuple[str, str, str]]:
        """本规则（不分版本——推导账是追加的）名下仍 active 的结论行。"""
        clause, params = tenant_sql_where(tenantId, alias="f")
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere("f")
        sql = ("SELECT f.fact_id AS fact_id, f.agent_id AS agent_id,"
               " s.canonical_label AS label FROM knowledge_derivation_edges e"
               " JOIN knowledge_facts f ON f.fact_id = e.derived_fact_id"
               " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
               " WHERE e.rule_id = ? AND " + currentClause + " AND " + clause)
        with self._store._lock:
            rows = self._store._conn.execute(
                sql, (ruleId, *currentParams, *params)).fetchall()
        return [(r["fact_id"], r["agent_id"], r["label"]) for r in rows]

    def _conclusionBlockedByNegation(self, rule: Dict[str, Any],
                                     negated: List[Dict[str, str]], factId: str,
                                     agentId: str, label: str,
                                     tenantId: str) -> bool:
        """按各形状的求值口径复查否定前提——与 `_negatedHolds` /
        `_negatedConstHolds` 同一判据，只是反过来用于退役已不成立的结论。"""
        fact = self._store.fact(factId)
        if not fact:
            return False
        if rule.get("shape") == "conjunction":
            # 合取的否定钉在同主体与常量客体上（_negatedConstHolds 口径）
            return any(self._negatedFactExists(agentId, fact.get("subject_key"),
                                               atom["predicate"], atom["objectConst"],
                                               tenantId)
                       for atom in negated)
        if rule.get("shape") == "inverse":
            # _fireInverse 的否定按正文变元 (X, Y) 评估：
            # 阻断事实 = (X 的主体键, 否定谓词, Y 的词形)
            xKey = self._store.resolveSubjectKey(agentId,
                                                 str(fact.get("object_term") or ""),
                                                 tenantId=tenantId)
            if not xKey:
                return False
            return any(self._negatedFactExists(agentId, xKey, atom["predicate"],
                                               label, tenantId)
                       for atom in negated)
        # relay：否定按 head 绑定 (X, Z) 评估（_negatedHolds 口径）
        return any(self._negatedFactExists(agentId, fact.get("subject_key"),
                                           atom["predicate"], fact.get("object_term"),
                                           tenantId)
                   for atom in negated)

    def _negatedFactExists(self, agentId: Optional[str], subjectKey: Any,
                           predicate: str, objectTerm: Any, tenantId: str) -> bool:
        clause, params = tenant_sql_where(tenantId)
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere()
        sql = ("SELECT 1 FROM knowledge_facts WHERE subject_key = ?"
               " AND predicate_term_id = ? AND object_term = ?"
               " AND " + currentClause + " AND " + clause)
        args: List[Any] = [subjectKey, predicate, objectTerm, *currentParams, *params]
        if agentId:
            sql += " AND agent_id = ?"
            args.append(agentId)
        with self._store._lock:
            return self._store._conn.execute(sql, args).fetchone() is not None

    def _fireInverse(self, rule: Dict[str, Any], agentId: Optional[str],
                     tenantId: str = "default") -> List[str]:
        """反向补边求值（B8）：`X A Y ⇒ Y <head> X`。

        head 主语 = 前提的**客体词形**——不要求 Y 已登记主体：推导走咽喉，
        消解段会按标签落主体/复用既存主体，这正是"经咽喉"的意义。head 客体取
        X 的规范标签。变元映射在求值器里显式落 head：反向补边是关系特征的一部分，
        不散落到任何消费方。
        """
        positive = [a for a in rule["body"] if a["kind"] == "atom"]
        negated = [a for a in rule["body"] if a["kind"] == "not"]
        a0 = positive[0]
        invTenantClause, invTenantParams = tenant_sql_where(tenantId, alias="a")
        currentClause, currentParams = KnowledgeFactStore.currentFactWhere("a")
        inner = ("SELECT a.subject_key AS x_key, MIN(s1.canonical_label) AS x_label,"
                 " a.object_term AS y_label,"
                 " GROUP_CONCAT(DISTINCT a.fact_id) AS pairs"
                 " FROM knowledge_facts a"
                 " JOIN knowledge_subjects s1 ON s1.subject_key = a.subject_key"
                 " WHERE a.predicate_term_id = ? AND %s AND %s"
                 "  AND a.record_kind = 'triple'" % (invTenantClause, currentClause))
        params: List[Any] = [a0["predicate"], *invTenantParams, *currentParams]
        if agentId:
            inner += " AND a.agent_id = ?"
            params.append(agentId)
        inner += " GROUP BY a.subject_key, a.object_term ORDER BY a.subject_key, y_label"
        with self._store._lock:
            rows = self._store._conn.execute(inner, params).fetchall()

        head = rule["head_predicate"]
        written: List[str] = []
        for row in rows:
            if self._negatedHolds(agentId, negated, row["x_key"], row["y_label"],
                                  tenantId=tenantId):
                continue
            factId = self._admitDerivedFact(rule, agentId, row["y_label"], head,
                                            row["x_label"], "",
                                            _premiseIds(row["pairs"]),
                                            tenantId=tenantId)
            if factId:
                written.append(factId)
        return written

    def ensureAutoRules(self, tenantId: str = "default") -> Dict[str, int]:
        """把术语表上的关系特征对齐成 auto_* 规则行（B8）：幂等，声明消失即退场。

        与 `seedBuiltinRules` 同一 owner 纪律：auto 规则的唯一生成点在这里，
        `term_registry` 不反向依赖引擎。声明翻转/撤除时，旧 auto 行删除并经账本
        精确撤销其结论——特征不再是声明的事实，它的推导不能还在对外检索。
        `is_a` 的传递规则沿用历史 id `is_a_transitive`（同 id 单行，结论与
        旧手工种子逐条一致，A/B 对拍判据在 test_relationMapping）。
        """
        registry = self._conditionRegistry()
        stats = {"created": 0, "retired": 0}
        desired: Dict[str, Dict[str, Any]] = {}
        for term in registry.terms("relation", tenantId=tenantId):
            termId = str(term["term_id"])
            parent = str(term.get("parent_term_id") or "")
            if parent:
                desired["auto_subproperty:%s" % termId] = {
                    "headPredicate": parent,
                    "body": [{"atom": termId, "subject": "X", "object": "Y"}],
                    "shape": "relay"}
            if term.get("transitive"):
                transitiveId = ("is_a_transitive" if termId == IS_A_PREDICATE
                                else "auto_transitive:%s" % termId)
                desired[transitiveId] = {
                    "headPredicate": termId,
                    "body": [{"atom": termId, "subject": "X", "object": "Y"},
                             {"atom": termId, "subject": "Y", "object": "Z"}],
                    "shape": "relay"}
            inverse = str(term.get("inverse_of") or "")
            if inverse:
                desired["auto_inverse:%s" % termId] = {
                    "headPredicate": inverse,
                    "body": [{"atom": termId, "subject": "X", "object": "Y"}],
                    "shape": "inverse",
                    "headSubjectVar": "Y"}
            if term.get("symmetric"):
                desired["auto_symmetric:%s" % termId] = {
                    "headPredicate": termId,
                    "body": [{"atom": termId, "subject": "X", "object": "Y"}],
                    "shape": "inverse",
                    "headSubjectVar": "Y"}
        existing = {r["rule_id"]: r for r in
                    self.rules(includeDisabled=True, tenantId=tenantId)
                    if str(r["rule_id"]).startswith("auto_")
                    or r["rule_id"] == "is_a_transitive"}
        for ruleId, spec in desired.items():
            current = existing.get(ruleId)
            if current and current.get("enabled") \
                    and current.get("shape") == spec["shape"] \
                    and current.get("head_predicate") == spec["headPredicate"] \
                    and current.get("depends_on") == sorted(
                        {a.get("atom") or a.get("not") for a in spec["body"]}):
                continue
            self.registerRule(ruleId, spec["headPredicate"], spec["body"],
                              shape=spec["shape"],
                              headSubjectVar=spec.get("headSubjectVar", "X"),
                              tenantId=tenantId)
            stats["created"] += 1
        for ruleId, row in existing.items():
            if ruleId not in desired and row.get("enabled"):
                self.dropRule(ruleId, reason="关系声明已撤，auto 规则退场",
                              tenantId=tenantId)
                stats["retired"] += 1
        return stats

    def _admitDerivedFact(self, rule: Dict[str, Any], agentId: Optional[str], label: str,
                          predicate: str, objectTerm: str, subjectKey: str,
                          premiseIds: List[str],
                          tenantId: str = "default") -> Optional[str]:
        gate = self._gateFactory(self._store) if self._gateFactory else None
        if gate is None:
            raise RuleError("推理未接咽喉写入口——推导事实不许绕过 admit 直插 SQL")
        from ..foundation.admission import AdmissionRequest

        content = "%s %s %s（由规则 %s 推出）" % (label, predicate, objectTerm, rule["rule_id"])
        try:
            receipt = gate.admit(AdmissionRequest(
                agentId=agentId or "default",
                tenantId=str(tenantId or rule.get("tenant_id") or "default"),
                subjectLabel=label, predicateTermId=predicate,
                objectTerm=objectTerm, content=content,
                qualifier={"derived_by": rule["rule_id"],
                           "stratum": rule["stratification_level"],
                           "shape": str(rule.get("shape") or "relay")},
                assertions=[{"actorType": "pipeline", "actorId": "rule:%s" % rule["rule_id"],
                             "mediumRef": "rule:%s" % rule["rule_id"],
                             "statementText": content}],
                # 来路由推导器自陈：不声明就落进咽喉的兜底「直写」，溯源账上读起来
                # 像"有人直插了一条"，而 `ACTIVITY_KINDS` 里的 `derive` 从无使用者。
                activityKind="derive",
                activityBasis="ForwardChainingEngine._admitDerivedFact（规则 %s 推导）"
                              % rule["rule_id"],
            ))
        except ValueError:
            return None            # 本体/基数拒绝推导结果：与原始写入同一口径，不开例外
        ledger = self._store._derivationLedger
        if receipt.dedupedByContent:
            return self._renewDerived(rule, ledger, receipt.factId, premiseIds)
        ledger.recordDerivation(receipt.factId, premiseIds, rule)
        ledger.recordFire(rule, [receipt.factId])
        return receipt.factId

    def _renewDerived(self, rule: Dict[str, Any], ledger: Any, factId: str,
                      premiseIds: List[str]) -> Optional[str]:
        """折回已有行：active 的不算新推导（不动点靠这条终止）；已退档的重新主张。

        内容键刻意不看 status，所以被级联退掉的结论再推一次会撞回同一行。不复活它，
        一次撤回就把这条结论永久打死——那等于撤销比故障更持久。
        """
        if (self._store.fact(factId) or {}).get("status") != "retracted":
            return None
        self._store.reviveRetracted(factId, reason="推导前提重新齐备")
        ledger.recordDerivation(factId, premiseIds, rule)
        ledger.recordFire(rule, [factId])
        return factId

    def transitiveClosure(self, agentId: str, predicate: str) -> List[Tuple[str, str]]:
        """传递闭包交给递归 CTE：一次查询算完，不在 Python 里迭代到不动点。

        链的接法与 `_fireRule` 一致——上一跳的客体按规范标签找到下一跳的主体；
        `UNION`（不是 UNION ALL）自带行去重，再加一条 path 判重防同一客体被反复绕。
        返回 (主体键, 可达客体) 对，不含自反。
        """
        rootClause, rootParams = KnowledgeFactStore.currentFactWhere()
        stepClause, stepParams = KnowledgeFactStore.currentFactWhere("f", now=rootParams[0])
        sql = (
            "WITH RECURSIVE closure(agent_id, subject_key, object_term, path) AS ("
            "  SELECT agent_id, subject_key, object_term,"
            "         '|' || subject_key || '|' || object_term || '|'"
            "  FROM knowledge_facts"
            "  WHERE agent_id = ? AND predicate_term_id = ?"
            "    AND " + rootClause + " AND record_kind = 'triple'"
            "  UNION"
            "  SELECT c.agent_id, c.subject_key, f.object_term,"
            "         c.path || f.object_term || '|'"
            "  FROM closure c"
            "  JOIN knowledge_subjects s2 ON s2.agent_id = c.agent_id"
            "    AND s2.normalized_label = lower(trim(c.object_term)) AND s2.status = 'active'"
            "  JOIN knowledge_facts f ON f.subject_key = s2.subject_key"
            "    AND f.agent_id = c.agent_id AND f.predicate_term_id = ?"
            "    AND " + stepClause + " AND f.record_kind = 'triple'"
            "    AND instr(c.path, '|' || f.object_term || '|') = 0"
            ") SELECT c.subject_key, c.object_term FROM closure c"
            " LEFT JOIN knowledge_subjects s3 ON s3.agent_id = c.agent_id"
            "   AND s3.normalized_label = lower(trim(c.object_term)) AND s3.status = 'active'"
            # 自反的一对（A 可达 A）是环的副产物，不是结论；客体没登记成主体的照原样留着。
            " WHERE s3.subject_key IS NULL OR c.subject_key <> s3.subject_key"
            " ORDER BY c.subject_key, c.object_term"
        )
        with self._store._lock:
            rows = self._store._conn.execute(
                sql, (agentId, predicate, *rootParams, predicate, *stepParams)).fetchall()
        # B8：传递闭包上限——超限显式报错，不静默截断（截断的闭包是错的语义）。
        maxClosureRows = int(os.environ.get("NEUROVA_TRANSITIVE_CLOSURE_MAX", "200000") or 200000)
        if len(rows) > maxClosureRows:
            raise RuntimeError(
                "传递闭包行数 %d 超过上限 %d（谓词 %s）：请收窄数据面或调高"
                " NEUROVA_TRANSITIVE_CLOSURE_MAX" % (len(rows), maxClosureRows, predicate))
        return [(r["subject_key"], r["object_term"]) for r in rows]
