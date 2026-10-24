"""检索质量离线评测台架（工单 002，设计文档 §8）。

主锚地位：本批所有"检索变好了"的结论都必须落在这里的读数上，治理指标只作辅证。
纪律：读数取不到即 `unevidenced` 并写明缺哪样，绝不按 `passed` 处理（ADR 0016）。
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger

from neurova.knowledge.foundation.storage_fence import (
    PRODUCTION_STORAGE_DIR,
    assertNotUnderProductionStorage,
)
from neurova.knowledge.hybrid import hybrid_search_knowledge

logger = get_logger(__name__)

_LABEL_METHODS = ("title_literal", "tag", "category")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_cases (
    case_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    expected_ids TEXT NOT NULL DEFAULT '[]',
    domain TEXT NOT NULL DEFAULT '',
    labeling_method TEXT NOT NULL DEFAULT 'manual',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    case_count INTEGER NOT NULL DEFAULT 0,
    top_k INTEGER NOT NULL DEFAULT 5,
    measure_state TEXT NOT NULL DEFAULT 'measured',
    missing_reason TEXT NOT NULL DEFAULT '',
    context_json TEXT NOT NULL DEFAULT '{}',
    recall_at_k REAL,
    mrr REAL,
    unhit_rate REAL,
    is_baseline INTEGER NOT NULL DEFAULT 0,
    frozen_at TEXT,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evaluation_findings (
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    query TEXT NOT NULL,
    hit_ids TEXT NOT NULL DEFAULT '[]',
    reciprocal_rank REAL NOT NULL DEFAULT 0,
    recall_at_k REAL NOT NULL DEFAULT 0,
    unhit INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_eval_findings_run ON evaluation_findings(run_id);
"""
register_migration(1, _SCHEMA, domain="knowledge_evaluation")

# v2：NDCG@k、精排变体与增益。旧 run 的这些列为 NULL，不是 0——没测过就是没测过。
_SCHEMA_V2 = """
ALTER TABLE evaluation_runs ADD COLUMN ndcg_at_k REAL;
ALTER TABLE evaluation_runs ADD COLUMN rerank_ndcg_at_k REAL;
ALTER TABLE evaluation_runs ADD COLUMN rerank_gain REAL;
ALTER TABLE evaluation_runs ADD COLUMN variant TEXT NOT NULL DEFAULT '';
ALTER TABLE evaluation_findings ADD COLUMN ndcg_at_k REAL NOT NULL DEFAULT 0;
ALTER TABLE evaluation_findings ADD COLUMN rerank_ndcg_at_k REAL;
"""
register_migration(2, _SCHEMA_V2, domain="knowledge_evaluation")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# 生产路径只有 storage_fence 一处定义；评测账本与底座库同目录但分库，互不共用存储。
DEFAULT_EVAL_DB = str(Path(PRODUCTION_STORAGE_DIR) / "knowledge_evaluation.db")


class RetrievalBenchmark:
    """标注案例 → 真检索路 → recall@k / MRR / 未命中率，读数落库可对比。"""

    def __init__(self, db_path: str) -> None:
        assertNotUnderProductionStorage(db_path, "评测账本")
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._ensureSchema()

    # ── schema ────────────────────────────────────────────────

    def _ensureSchema(self) -> None:
        with self._lock:
            apply_migrations(self._conn, "knowledge_evaluation")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── 案例 ──────────────────────────────────────────────────

    def addCase(
        self,
        query: str,
        expectedIds: List[str],
        domain: str = "",
        createdBy: str = "",
        labelingMethod: str = "manual",
    ) -> str:
        if labelingMethod not in _LABEL_METHODS + ("manual",):
            raise ValueError("未知标注口径: %r（有效值: %s）" % (labelingMethod, _LABEL_METHODS + ("manual",)))
        case_id = "evc_%s" % uuid.uuid4().hex[:12]
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO evaluation_cases (case_id, query, expected_ids, domain,"
                " labeling_method, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                (case_id, query, json.dumps(list(expectedIds), ensure_ascii=False), domain,
                 labelingMethod, createdBy, _now()),
            )
        return case_id

    def cases(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM evaluation_cases ORDER BY created_at, case_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def caseCount(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM evaluation_cases").fetchone()[0])

    def labelingBreakdown(self) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT labeling_method, COUNT(*) AS n FROM evaluation_cases GROUP BY labeling_method"
            ).fetchall()
        return {r["labeling_method"]: int(r["n"]) for r in rows}

    # ── 基线快照的可移植面 ────────────────────────────────────
    # 评测库与语料库都在 .gitignore 的 /data/ 下，只活在本机。基线要能被复查，
    # 至少 case 集必须入库；否则"对比冻结基线"这句话换个人就跑不通。

    def exportCases(self, path: str) -> int:
        cases = self.cases()
        payload = {
            "schema": "neurova.knowledge.evaluation.cases/v1",
            "case_count": len(cases),
            "labeling_breakdown": self.labelingBreakdown(),
            "cases": [
                {
                    "query": c["query"], "expected_ids": json.loads(c["expected_ids"] or "[]"),
                    "domain": c["domain"], "labeling_method": c["labeling_method"],
                    "created_by": c["created_by"],
                }
                for c in cases
            ],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(cases)

    def loadCases(self, path: str) -> int:
        """按 (口径, query) 幂等导入——已有即跳过，不重复堆案例。"""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != "neurova.knowledge.evaluation.cases/v1":
            raise ValueError("评测案例快照版本不符: %r" % payload.get("schema"))
        existing = {(c["labeling_method"], c["query"]) for c in self.cases()}
        loaded = 0
        for case in payload["cases"]:
            key = (case["labeling_method"], case["query"])
            if key in existing:
                continue
            self.addCase(case["query"], case["expected_ids"], domain=case.get("domain", ""),
                         createdBy=case.get("created_by", ""),
                         labelingMethod=case["labeling_method"])
            existing.add(key)
            loaded += 1
        return loaded

    def baselineSnapshot(self) -> Dict[str, Any]:
        """可入库的基线摘要，供复查与 011 前后对比引用。"""
        baseline = self.baseline()
        if baseline is None:
            return {"measure_state": "unevidenced",
                    "missing_reason": "尚未冻结基线", "case_count": self.caseCount()}
        return {
            "measure_state": baseline.get("measure_state"),
            "run_id": baseline.get("run_id"),
            "frozen_at": baseline.get("frozen_at"),
            "case_count": baseline.get("case_count"),
            "top_k": baseline.get("top_k"),
            "context": json.loads(baseline.get("context_json") or "{}"),
            "readings": {
                "recall_at_k": baseline.get("recall_at_k"),
                "mrr": baseline.get("mrr"),
                "unhit_rate": baseline.get("unhit_rate"),
            },
            "labeling_breakdown": self.labelingBreakdown(),
            "unhit_queries": [
                f["query"] for f in self.findings(baseline["run_id"]) if f["unhit"]
            ],
        }

    def seedFromRepository(self, repo: Any, minCases: int = 30) -> int:
        """从真实条目自动标注：口径混合，不靠标题直取充数。

        自动标注衡量的是检索管路是否通，不等于语义质量——所以 labeling_method
        逐案留痕，人工标注（manual）随时可叠加进来。
        """
        items: List[Dict[str, Any]] = []
        for entries in getattr(repo, "_items", {}).values():
            items.extend(entries)
        produced = 0
        seen: set = set()
        # tag/category 口径的正确答案天然是"该类的全部条目"，只标一条会把
        # 检索判成漏报。故先建全量映射，expected 用整个集合，不按单条 id 苛求。
        expectedByQuery: Dict[tuple, List[str]] = {}
        for item in items:
            for method in _LABEL_METHODS:
                query = self._queryFor(method, item)
                kid = str(item.get("knowledge_id", ""))
                if query and kid:
                    expectedByQuery.setdefault((method, query), []).append(kid)
        if len(expectedByQuery) < minCases:
            raise ValueError(
                "条目不足：现有 %d 条、去重后仅 %d 种可标注 query，凑不满 %d 例"
                % (len(items), len(expectedByQuery), minCases)
            )

        # 三种口径逐条轮转产例：整批压在标题直取上会让"管路通"被当成"检索准"。
        # 同一 (口径, query) 只产一例——重复例会把同一个 query 计多次，把读数带偏。
        for item in items:
            for method in _LABEL_METHODS:
                if produced >= minCases:
                    break
                query = self._queryFor(method, item)
                if not query or (method, query) in seen:
                    continue
                seen.add((method, query))
                self.addCase(
                    query, expectedByQuery[(method, query)],
                    domain=str(item.get("category", "") or ""),
                    createdBy="seedFromRepository", labelingMethod=method,
                )
                produced += 1
            if produced >= minCases:
                break
        return produced

    @staticmethod
    def _queryFor(method: str, item: Dict[str, Any]) -> str:
        if method == "title_literal":
            return str(item.get("title", "")).strip()
        if method == "tag":
            return " ".join(str(t) for t in (item.get("tags") or []) if t).strip()
        return str(item.get("category", "")).strip()

    # ── 跑测 ──────────────────────────────────────────────────

    def run(
        self,
        repo: Any,
        user: Optional[Dict[str, Any]] = None,
        agentId: Optional[str] = None,
        topK: int = 5,
        note: str = "",
        searchFn: Optional[Any] = None,
        domain: str = "",
        rerank: Optional[Any] = None,
        variant: str = "",
    ) -> Dict[str, Any]:
        started = _now()
        run_id = "evr_%s" % uuid.uuid4().hex[:12]
        cases = [
            case for case in self.cases()
            if not domain or str(case.get("domain") or "") == str(domain)
        ]
        # 身份必须随读数落库：生产条目多为 private 且各有 owner，
        # 换一个 user 就是在测另一份语料，不记下来读数不可复现。
        context = {
            "user": user or {},
            "agent_id": agentId,
            "scope": "all",
            "domain": domain,
            "variant": variant,
            "rerank": bool(rerank),
        }

        if not cases:
            reason = (
                "该域没有任何评测案例，读数无依据（不是检索差，是没测）" if domain
                else "没有任何评测案例，读数无依据（不是检索差，是没测）"
            )
            report = self._writeRun(
                run_id, started, _now(), 0, topK, "unevidenced",
                reason, None, note, context,
            )
            report["variant"] = variant
            return report

        recalls: List[float] = []
        rrs: List[float] = []
        unhits: List[float] = []
        ndcgs: List[float] = []
        rerankNdcgs: List[float] = []
        with self._lock, self._conn:
            for case in cases:
                expected = set(json.loads(case["expected_ids"] or "[]"))
                hits = (searchFn or self._defaultSearch(repo, user, agentId, topK))(case["query"])
                hitIds = [str(h.get("knowledge_id", "")) for h in hits][:topK]
                rr = 0.0
                for rank, hid in enumerate(hitIds, start=1):
                    if hid in expected:
                        rr = 1.0 / rank
                        break
                recall = (len(expected & set(hitIds)) / len(expected)) if expected else 0.0
                unhit = 0.0 if rr > 0 else 1.0
                ndcg = self._ndcg(hitIds, expected, topK)
                rerankNdcg = None
                if rerank is not None:
                    reranked = rerank(case["query"], hits) or []
                    rerankIds = [str(h.get("knowledge_id", "")) for h in reranked][:topK]
                    rerankNdcg = self._ndcg(rerankIds, expected, topK)
                    rerankNdcgs.append(rerankNdcg)
                recalls.append(recall)
                rrs.append(rr)
                unhits.append(unhit)
                ndcgs.append(ndcg)
                self._conn.execute(
                    "INSERT INTO evaluation_findings (run_id, case_id, query, hit_ids,"
                    " reciprocal_rank, recall_at_k, unhit, ndcg_at_k, rerank_ndcg_at_k)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (run_id, case["case_id"], case["query"],
                     json.dumps(hitIds, ensure_ascii=False), rr, recall, int(unhit),
                     ndcg, rerankNdcg),
                )

        metrics = {
            "recall_at_k": round(sum(recalls) / len(recalls), 6),
            "mrr": round(sum(rrs) / len(rrs), 6),
            "unhit_rate": round(sum(unhits) / len(unhits), 6),
            "ndcg_at_k": round(sum(ndcgs) / len(ndcgs), 6),
        }
        if rerankNdcgs:
            metrics["rerank_ndcg_at_k"] = round(sum(rerankNdcgs) / len(rerankNdcgs), 6)
            metrics["rerank_gain"] = round(
                metrics["rerank_ndcg_at_k"] - metrics["ndcg_at_k"], 6
            )
        report = self._writeRun(
            run_id, started, _now(), len(cases), topK, "measured", "",
            metrics, note, context,
        )
        report["variant"] = variant
        return report

    @staticmethod
    def _ndcg(hitIds: List[str], expected: set, k: int) -> float:
        """二值相关度 NDCG@k；没有期望集合时返回 0（无依据不猜）。"""
        if not expected:
            return 0.0
        gains = [1.0 if hid in expected else 0.0 for hid in hitIds[:k]]
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(expected), k)))
        return dcg / ideal if ideal else 0.0

    def _writeRun(
        self, runId: str, started: str, finished: str, caseCount: int, topK: int,
        measureState: str, missingReason: str, metrics: Optional[Dict[str, float]], note: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metrics = metrics or {}
        contextJson = json.dumps(context or {}, ensure_ascii=False, sort_keys=True)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO evaluation_runs (run_id, started_at, finished_at, case_count,"
                " top_k, measure_state, missing_reason, context_json, recall_at_k, mrr,"
                " unhit_rate, ndcg_at_k, rerank_ndcg_at_k, rerank_gain, variant, note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (runId, started, finished, caseCount, topK, measureState, missingReason,
                 contextJson,
                 metrics.get("recall_at_k"), metrics.get("mrr"), metrics.get("unhit_rate"),
                 metrics.get("ndcg_at_k"), metrics.get("rerank_ndcg_at_k"),
                 metrics.get("rerank_gain"), str(context.get("variant") or "") if context else "",
                 note),
            )
        return {
            "run_id": runId,
            "case_count": caseCount,
            "top_k": topK,
            "measure_state": measureState,
            "missing_reason": missingReason,
            "context": context or {},
            "recall_at_k": metrics.get("recall_at_k"),
            "mrr": metrics.get("mrr"),
            "unhit_rate": metrics.get("unhit_rate"),
            "ndcg_at_k": metrics.get("ndcg_at_k"),
            "rerank_ndcg_at_k": metrics.get("rerank_ndcg_at_k"),
            "rerank_gain": metrics.get("rerank_gain"),
            "variant": (context or {}).get("variant", ""),
            "started_at": started,
        }

    def _defaultSearch(self, repo, user, agentId, topK):
        def _search(query: str) -> List[Dict[str, Any]]:
            return hybrid_search_knowledge(repo, user or {}, query, limit=topK, agent_id=agentId)
        return _search

    # ── 基线 ──────────────────────────────────────────────────

    def freezeBaseline(self, report: Dict[str, Any], note: str = "") -> None:
        existing = self.baseline()
        if existing and existing["run_id"] != report["run_id"]:
            raise ValueError(
                "基线已冻结在 run %s（%s），不得被新 run 覆盖；要换尺子请先建新评测集版本"
                % (existing["run_id"], existing["frozen_at"])
            )
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE evaluation_runs SET is_baseline = 1, frozen_at = ?, note = ?"
                " WHERE run_id = ?",
                (_now(), note, report["run_id"]),
            )

    def baseline(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evaluation_runs WHERE is_baseline = 1 ORDER BY frozen_at LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def runCount(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0])

    def runById(self, runId: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM evaluation_runs WHERE run_id = ?", (runId,)
            ).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["context"] = json.loads(run.get("context_json") or "{}")
        run["by_domain"] = self.byDomain(runId)
        return run

    def compareVariants(
        self, runA: Dict[str, Any], runB: Dict[str, Any], minCases: int = 30,
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """两个变体 run 的离线 A/B 对照：样本不足先报不足，不按均值判胜负。

        runA=control、runB=treatment；只看 recall@k / MRR / NDCG / 未命中率。
        """
        countA = int(runA.get("case_count") or 0)
        countB = int(runB.get("case_count") or 0)
        if min(countA, countB) < max(1, int(minCases)):
            return {
                "verdict": "insufficient_sample",
                "min_cases": int(minCases),
                "case_count_a": countA,
                "case_count_b": countB,
            }
        deltas: Dict[str, float] = {}
        for key in ("recall_at_k", "mrr", "ndcg_at_k", "unhit_rate"):
            if runA.get(key) is None or runB.get(key) is None:
                continue
            deltas[key] = round(float(runB[key]) - float(runA[key]), 6)
        improved = deltas.get("recall_at_k", 0.0) > tolerance or (
            deltas.get("ndcg_at_k", 0.0) > tolerance
            and deltas.get("unhit_rate", 0.0) <= 0.0
        )
        regressed = deltas.get("recall_at_k", 0.0) < -tolerance or (
            deltas.get("ndcg_at_k", 0.0) < -tolerance
        )
        verdict = "improved" if improved else ("regressed" if regressed else "inconclusive")
        return {
            "verdict": verdict,
            "min_cases": int(minCases),
            "tolerance": float(tolerance),
            "case_count_a": countA,
            "case_count_b": countB,
            "variant_a": runA.get("variant", ""),
            "variant_b": runB.get("variant", ""),
            "deltas": deltas,
        }

    def gateNoRegression(
        self, runA: Dict[str, Any], runB: Dict[str, Any], minCases: int = 30,
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """CI 回归门：样本不足或判定 regressed 直接失败，不放行。

        `inconclusive` 不算失败（没有证据变差），但会原样返回供人工看。
        """
        verdict = self.compareVariants(runA, runB, minCases=minCases,
                                       tolerance=tolerance)
        if verdict["verdict"] == "insufficient_sample":
            raise AssertionError(
                "评测样本不足（%d/%d < %d），不能放行"
                % (verdict["case_count_a"], verdict["case_count_b"], minCases)
            )
        if verdict["verdict"] == "regressed":
            raise AssertionError("检索变体回归: %s" % verdict.get("deltas", {}))
        return verdict

    def compareAgainstBaseline(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """把这次 run 与已冻结基线逐案对账——台架此前只有"冻"与"看"，没有"退步了没有"。

        为什么硬判据落在**逐案**而不是平均值：`search.py` 在 jieba 不可用时会静默回退
        n-gram（中文 bm25/fts 精度降级，本机与 CI 可能不同），平均 recall 因此会随环境漂；
        而"某案例原本命中的条目现在一条都不剩"不是分词粒度问题，是管路断了。
        所以：`newlyUnhit`/`missingCases` 非空即回归；聚合读数一并回传，由调用方按
        容差自判，并且**只许往下比**——基线没冻时回 `unevidenced`，绝不回 `pass`
        （与 `run()` 里"没有任何评测案例"那一支同口径：没测过的事不能报成没退化）。
        """
        baseline = self.baseline()
        if baseline is None:
            return {"verdict": "unevidenced", "missing_reason": "尚未冻结基线",
                    "case_count": self.caseCount()}
        if baseline.get("run_id") == report.get("run_id"):
            return {"verdict": "self_reference",
                    "missing_reason": "本次 run 就是基线本身，无从对账",
                    "baseline_run_id": baseline.get("run_id")}

        before = {f["case_id"]: f for f in self.findings(baseline["run_id"])}
        after = {f["case_id"]: f for f in self.findings(report["run_id"])}
        newlyUnhit = sorted(cid for cid, f in after.items()
                            if cid in before and not before[cid]["unhit"] and f["unhit"])
        missingCases = sorted(set(before) - set(after))
        recovered = sorted(cid for cid, f in after.items()
                           if cid in before and before[cid]["unhit"] and not f["unhit"])
        deltas = {
            key: round(float(report.get(key) or 0.0) - float(baseline.get(key) or 0.0), 6)
            for key in ("recall_at_k", "mrr", "unhit_rate")
        }
        if report.get("ndcg_at_k") is not None and baseline.get("ndcg_at_k") is not None:
            deltas["ndcg_at_k"] = round(
                float(report["ndcg_at_k"]) - float(baseline["ndcg_at_k"]), 6
            )
        verdict = "regress" if (newlyUnhit or missingCases) else "pass"
        return {
            "verdict": verdict,
            "baseline_run_id": baseline["run_id"],
            "run_id": report.get("run_id"),
            "deltas": deltas,
            "baseline_readings": {k: baseline.get(k)
                                  for k in ("recall_at_k", "mrr", "unhit_rate")},
            "newly_unhit_cases": newlyUnhit,
            "recovered_cases": recovered,
            "missing_cases": missingCases,
        }

    def byDomain(self, runId: str) -> List[Dict[str, Any]]:
        """按案例 domain 切片读数；没有 domain 的案例单独归到空串组。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.domain AS domain, COUNT(*) AS case_count,"
                " AVG(f.recall_at_k) AS recall_at_k, AVG(f.reciprocal_rank) AS mrr,"
                " AVG(f.unhit) AS unhit_rate, AVG(f.ndcg_at_k) AS ndcg_at_k,"
                " AVG(f.rerank_ndcg_at_k) AS rerank_ndcg_at_k"
                " FROM evaluation_findings f JOIN evaluation_cases c ON c.case_id = f.case_id"
                " WHERE f.run_id = ? GROUP BY c.domain ORDER BY c.domain",
                (runId,),
            ).fetchall()
        return [
            {
                "domain": row["domain"],
                "case_count": int(row["case_count"]),
                "recall_at_k": round(float(row["recall_at_k"] or 0.0), 6),
                "mrr": round(float(row["mrr"] or 0.0), 6),
                "unhit_rate": round(float(row["unhit_rate"] or 0.0), 6),
                "ndcg_at_k": round(float(row["ndcg_at_k"] or 0.0), 6),
                "rerank_ndcg_at_k": (
                    round(float(row["rerank_ndcg_at_k"]), 6)
                    if row["rerank_ndcg_at_k"] is not None else None
                ),
            }
            for row in rows
        ]

    def findings(self, runId: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT f.*, r.is_baseline FROM evaluation_findings f"
                " JOIN evaluation_runs r ON r.run_id = f.run_id WHERE f.run_id = ?"
                " ORDER BY f.rowid",
                (runId,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hit_ids"] = json.loads(d.get("hit_ids") or "[]")
            d["is_baseline"] = bool(d.get("is_baseline"))
            out.append(d)
        return out


_benchmark_singleton: Optional[RetrievalBenchmark] = None
_benchmark_lock = threading.Lock()


def get_retrieval_benchmark() -> RetrievalBenchmark:
    global _benchmark_singleton
    with _benchmark_lock:
        if _benchmark_singleton is None:
            _benchmark_singleton = RetrievalBenchmark(DEFAULT_EVAL_DB)
        return _benchmark_singleton


def reset_retrieval_benchmark() -> None:
    global _benchmark_singleton
    with _benchmark_lock:
        if _benchmark_singleton is not None:
            _benchmark_singleton.close()
        _benchmark_singleton = None
