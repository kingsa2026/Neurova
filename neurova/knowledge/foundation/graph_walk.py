"""多跳图走查（工单 013，灭 B04）：属性图进对话链，读的是底座而不是 JSON 图。

B04 的形状是"图有 26% 覆盖率但答题时完全不被利用"。这里**不**把
`cognitive_layers/knowledge_graph/manager.py` 当读面：它把节点/边存成 JSON 文件、
遍历是 Python 侧 BFS 走内存 dict，与事实库是两套真相——从它读多跳，就会出现
"图上说一套、事实库里说一套"，正是这批改造要灭的病。

权威读面是 `knowledge_subjects` + `knowledge_facts` 上的递归 CTE，四条口径：

- **只走三元组**。叙述行的客体是内容键，当成边就会凭空造出一条没连过的链。
- **一跳不在此列**。一跳是时效读面（012）的活；两条分支都给就是同一说法占两个槽。
- **不跨 agent 域**。身份是 (agent, tenant, label) 维内唯一（`ux_subject_label_tenant`），
  跨域拼接等于把两个 agent 的说法连成一条链。
- **环靠"路径不重复经过同一主体"终止**，深度另有硬上限。SQLite 的递归 CTE 用
  `UNION ALL`，不去重——放任就是组合爆炸。

与 012 的另一处差别是刻意的：这里不按新近窗口筛（多跳问的是结构关系，不是"最近说过"），
但仍排除已失效说法。
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .temporal_facts import subjectsMentionedIn
from ..derivation_citation import conditionClassRouteOn, derivationInfo

GRAPH_RETRIEVER_ENV = "NEUROVA_KB_GRAPH_RETRIEVER"
_OFF_VALUES = ("0", "false", "off", "no")
_MAX_HOPS_CEILING = 4
#: 零子串锚点时的种子锚点上限（N3 接线）：兜底召回不放开到全图
SEED_ANCHOR_CAP = 3


@dataclass
class GraphWalkConfig:
    """多跳读面开关。默认开：B04 是断点不是新能力，关掉它等于把断点留在原地。"""

    enabled: bool = True
    maxHops: int = 2
    limit: int = 8

    @classmethod
    def fromEnv(cls) -> "GraphWalkConfig":
        raw = (os.environ.get(GRAPH_RETRIEVER_ENV) or "").strip().lower()
        return cls(enabled=raw not in _OFF_VALUES)


class GraphFactWalker:
    """从查询提到的主体出发，沿客体↔主体接力走若干跳。"""

    def __init__(self, store: Any, agentId: Optional[str] = None,
                 config: Optional[GraphWalkConfig] = None) -> None:
        if store is None:
            raise ValueError("GraphFactWalker 需要底座库句柄——不给权威就没得走")
        self._store = store
        self._agentId = agentId
        self._config = config or GraphWalkConfig.fromEnv()

    @property
    def factStore(self) -> Any:
        """检索器要拿它回写注入账（G07）；不暴露就别让旁路自己猜路径。"""
        return self._store

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def walkFromQuery(self, query: str, maxHops: Optional[int] = None,
                      limit: Optional[int] = None,
                      now: Optional[datetime.datetime] = None,
                      tenantId: Optional[str] = None,
                      allowedCategories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """返回 hop ≥ 2 的终点事实，按跳数由近及远、同跳内按置信与新近。

        allowedCategories（specs/2026-11-07 批 E）：部门分类白名单下推——
        锚点段与递归段都只走白名单内 category 的事实；空列表 = 受限且无可见
        分类 → 零命中；None = 未启用白名单，行为不变。
        """
        if allowedCategories is not None and not [c for c in allowedCategories if str(c)]:
            return []
        hops = min(max(int(maxHops if maxHops is not None else self._config.maxHops), 2),
                   _MAX_HOPS_CEILING)
        cap = max(int(limit if limit is not None else self._config.limit), 1)
        anchors = subjectsMentionedIn(
            self._store, query or "", self._agentId, tenantId
        )
        seeded = False
        if not anchors:
            anchors = self._seedAnchors(query or "", tenantId)
            seeded = bool(anchors)
        if not anchors:
            return []
        moment = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(
            datetime.timezone.utc)
        rows = self._walk(anchors, hops, cap, moment, tenantId,
                          allowedCategories=allowedCategories)
        # 翻主路态才给跳板挂溯源标注：观察态下推导行根本进不了 CTE（_walk 里排除），
        # 去查一遍账本只是白花一次 IO，还会让人以为过滤与标注是两套判据。
        # v35 加了按规则类的物化档位：灰度 off 但本租户有 enforce 规则时，推导行
        # 也进得来（且混合推导仍被排除），所以那种场合标注照取。
        derivedIds: set = set()
        ledgerForIds = getattr(self._store, "_derivationLedger", None)
        routeOn = conditionClassRouteOn()
        if routeOn or (ledgerForIds is not None
                       and ledgerForIds.hasEnforceRules(tenantId)):
            try:
                derivedIds = set(ledgerForIds.derivedFactIds())
            except Exception:  # noqa: BLE001 - 标注失败只丢标注，走查照旧返回
                derivedIds = set()
        if seeded:
            # 收益记账：种子驱动的走查实际返回行数（SAG 对比 C1 观测项）。
            try:
                from ..retrieval_metrics import get_retrieval_metrics

                get_retrieval_metrics().recordSeedWalkHits(walkHits=len(rows))
            except Exception:  # noqa: BLE001 - 观测面故障绝不影响走查
                pass
        return [
            self._asHopDict(row, derivedIds)
            for row in rows
        ]

    # ── 内部 ──────────────────────────────────────────────────

    def _seedAnchors(self, query: str, tenantId: Optional[str]) -> List[str]:
        """零子串锚点时的 BM25 事实种子兜底（SAG 对比 N3 接线，2026-11-05）。

        subjectsMentionedIn 是「这条查询在问谁」的强判据（时效读面与走查共用，
        不动）；但换说法/未登记别名的查询会零锚点，多跳走查整路空转。事实池
        BM25（FactSurface.search）在词法不精确时仍能召回相关事实行，其主体即
        种子锚点。受 NEUROVA_KB_FACT_SURFACE 闸门控：闸关返回空列表，行为逐位
        等于旧行为；仅在强判据零命中时调用，强判据优先地位不变。
        观测跟闸走（SAG 对比 C1 观测项）：闸关零记录；扫描只记
        latency/pool/anchors，收益（walk_hits）由 walkFromQuery 种子路径记账。
        """
        try:
            import time

            from .read_surface import FactSurface

            surface = FactSurface(self._store)
            if not surface.enabled:
                return []  # 闸关：零扫描、零观测
            started = time.monotonic()
            hits = surface.search(
                query, limit=SEED_ANCHOR_CAP, agentId=self._agentId,
                tenantId=tenantId,
            )
            elapsedMs = (time.monotonic() - started) * 1000.0
        except Exception:  # noqa: BLE001 - 种子失败让路，走查空手而归（旧行为）
            return []
        keys: List[str] = []
        for hit in hits:
            key = str(hit.get("subject_key") or "")
            if key and key not in keys:
                keys.append(key)
        keys = keys[:SEED_ANCHOR_CAP]
        try:
            from ..retrieval_metrics import get_retrieval_metrics

            get_retrieval_metrics().recordSeedScan(
                latencyMs=elapsedMs, poolSize=len(hits), anchors=len(keys)
            )
        except Exception:  # noqa: BLE001 - 观测面故障绝不影响走查
            pass
        return keys

    def _walk(self, anchors: List[str], maxHops: int, limit: int,
              now: datetime.datetime, tenantId: Optional[str] = None,
              allowedCategories: Optional[List[str]] = None) -> List[Any]:
        placeholders = ",".join("?" * len(anchors))
        stamp = now.isoformat()
        # 部门分类白名单（specs/2026-11-07 批 E）：锚点段 f 与递归段 f2 同口径——
        # 走查不得"绕道"白名单外事实接出白名单内事实
        catValues: List[Any] = []
        if allowedCategories is not None:
            catValues = [str(c) for c in allowedCategories if str(c)]
            catClause = "category IN (%s)" % ",".join("?" * len(catValues)) if catValues else "1 = 0"
        anchorClauses = ["f.status = 'active'", "f.record_kind = 'triple'",
                         "(f.valid_until IS NULL OR f.valid_until = ''"
                         " OR f.valid_until > ?)"]
        anchorValues: List[Any] = [stamp]
        if allowedCategories is not None:
            anchorClauses.append("f.%s" % catClause)
            anchorValues.extend(catValues)
        if self._agentId:
            anchorClauses.append("f.agent_id = ?")
            anchorValues.append(self._agentId)
        if tenantId is not None:
            anchorClauses.append("f.tenant_id = ?")
            anchorValues.append(str(tenantId or "default"))
        # 观察态灰度（升级计划 B1 拍板项 2）落在这里，不只落在读面：递归段里
        # 一条推导行可以当**跳板**——自己不带条目，却把挂在条目上的显式事实接进
        # 排序，那是推导进对话的真实路径。只在 FactSurface 摘条目管不到这一层。
        # 判据与读面共用同一处（conditionClassRouteOn），不各写一份 env 解析。

        ledger = getattr(self._store, "_derivationLedger", None)
        if not conditionClassRouteOn() and ledger is not None:
            anchorClauses.append(ledger.derivedExclusionClause("f"))
        # 递归段不再按 agent 过滤事实本身：域已经由 s2.agent_id = w.agent_id 与
        # f2.agent_id = s2.agent_id 两道锁住；多写一遍只会让"谁约束谁"看不清。
        headClause = ("f2.status = 'active' AND f2.record_kind = 'triple'"
                      " AND (f2.valid_until IS NULL OR f2.valid_until = ''"
                      " OR f2.valid_until > ?) AND f2.agent_id = s2.agent_id")
        if tenantId is not None:
            headClause += " AND f2.tenant_id = ?"
        if allowedCategories is not None:
            headClause += " AND f2.%s" % catClause
        if not conditionClassRouteOn() and ledger is not None:
            headClause += " AND " + ledger.derivedExclusionClause("f2")
        #  visited 只记**经过的主体**（不含当前客体）：把客体也记进去，下一跳的起点
        #  永远被判成"重复经过"，整条链一步都走不动（本票第一版就是这么红的）。
        #  路径分隔符一律 ASCII：这条串会进日志与提示词，而 Windows 控制台默认码页
        #  不是 UTF-8，一个"⇒"就够把打印打成 UnicodeEncodeError。
        sql = (
            "WITH RECURSIVE walk(fact_id, agent_id, subject_key, predicate_term_id,"
            " object_term, confidence, recorded_at, hop, visited, path, via_derived) AS ("
            "  SELECT f.fact_id, f.agent_id, f.subject_key, f.predicate_term_id,"
            "         f.object_term, f.confidence, f.recorded_at, 1,"
            "         '|' || lower(s0.canonical_label) || '|',"
            "         s0.canonical_label || ' -' || f.predicate_term_id || '-> '"
            "         || f.object_term,"
            "         EXISTS (SELECT 1 FROM knowledge_derivation_edges e"
            "                 WHERE e.derived_fact_id = f.fact_id)"
            "  FROM knowledge_facts f"
            "  JOIN knowledge_subjects s0 ON s0.subject_key = f.subject_key"
            "  WHERE %s AND f.subject_key IN (%s)"
            "  UNION ALL"
            "  SELECT f2.fact_id, f2.agent_id, f2.subject_key, f2.predicate_term_id,"
            "         f2.object_term, f2.confidence, f2.recorded_at, w.hop + 1,"
            "         w.visited || lower(s2.canonical_label) || '|',"
            "         w.path || ' ; ' || s2.canonical_label || ' -' || f2.predicate_term_id"
            "         || '-> ' || f2.object_term,"
            "         (w.via_derived OR EXISTS (SELECT 1"
            "             FROM knowledge_derivation_edges e2"
            "             WHERE e2.derived_fact_id = f2.fact_id))"
            "  FROM walk w"
            "  JOIN knowledge_subjects s2 ON s2.agent_id = w.agent_id"
            "       AND s2.normalized_label = lower(trim(w.object_term))"
            "       AND s2.status = 'active'"
            "  JOIN knowledge_facts f2 ON f2.subject_key = s2.subject_key"
            "  WHERE w.hop < ? AND %s"
            "        AND instr(w.visited, '|' || lower(s2.canonical_label) || '|') = 0"
            ")"
            " SELECT * FROM walk WHERE hop >= 2"
            " ORDER BY hop, (confidence IS NULL), confidence DESC, recorded_at DESC, fact_id"
            " LIMIT ?"
        ) % (" AND ".join(anchorClauses), placeholders, headClause)
        params = anchorValues + anchors + [maxHops, stamp]
        if tenantId is not None:
            params.append(str(tenantId or "default"))
        if allowedCategories is not None:
            # f2 的白名单占位在 headClause 里，参数序在 tenant 之后、limit 之前
            params.extend(catValues)
        params.append(limit)
        with self._store._lock:
            return self._store._conn.execute(sql, params).fetchall()

    def _asHopDict(self, row: Any, derivedIds: Optional[set] = None) -> Dict[str, Any]:
        fact = dict(row)
        subject = self._store.subjectFor(fact["subject_key"]) or {}
        assertions = self._store.assertions(fact["fact_id"])
        hop = {
            "id": fact["fact_id"],
            "subject": str(subject.get("canonical_label", "") or ""),
            "predicate": fact["predicate_term_id"],
            "object": fact["object_term"],
            "confidence": fact["confidence"],
            "hop": fact["hop"],
            "path": fact["path"],
            "visited": fact["visited"],
            "source": str(assertions[-1].get("medium_ref", "") or "") if assertions else "",
            "entry_id": (
                str(assertions[-1].get("medium_ref", "") or "").partition("entry:")[2]
                if assertions and "entry:" in str(assertions[-1].get("medium_ref", ""))
                else ""
            ),
            "tenant_id": str(fact.get("tenant_id") or "default"),
            # 整条路径有没有经过推导行：跳板本身不在返回里（只回 hop>=2 的叶子），
            # 标志不随叶子走，图谱路由就不知道自己顶上来的是推导还是观察
            "via_derived": bool(fact.get("via_derived")),
        }
        if derivedIds and fact["fact_id"] in derivedIds:
            # 这条跳是推出来的：对话侧的引用标注据它挂「推导」，不伪装成观察事实
            try:
                edges = self._store._derivationLedger.premisesOf(fact["fact_id"])
            except Exception:  # noqa: BLE001 - 读不到就不挂键（缺席＝没溯过源）
                return hop
            hop["derivation"] = derivationInfo(edges)
        return hop
