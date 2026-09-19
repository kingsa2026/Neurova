"""检索质量离线评测台架（工单 002，设计文档 §8）。

主锚地位：本批所有"检索变好了"的结论都必须落在这里的读数上，治理指标只作辅证。
纪律：读数取不到即 `unevidenced` 并写明缺哪样，绝不按 `passed` 处理（ADR 0016）。
"""

from __future__ import annotations

import datetime
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.db_migration import migrate as apply_migrations, register_migration
from neurova.core.logger import get_logger

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


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


DEFAULT_EVAL_DB = "./data/knowledge/knowledge_evaluation.db"


class RetrievalBenchmark:
    """标注案例 → 真检索路 → recall@k / MRR / 未命中率，读数落库可对比。"""

    def __init__(self, db_path: str) -> None:
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
    ) -> Dict[str, Any]:
        started = _now()
        run_id = "evr_%s" % uuid.uuid4().hex[:12]
        cases = self.cases()
        # 身份必须随读数落库：生产条目多为 private 且各有 owner，
        # 换一个 user 就是在测另一份语料，不记下来读数不可复现。
        context = {
            "user": user or {},
            "agent_id": agentId,
            "scope": "all",
        }

        if not cases:
            report = self._writeRun(
                run_id, started, _now(), 0, topK, "unevidenced",
                "没有任何评测案例，读数无依据（不是检索差，是没测）", None, note, context,
            )
            return report

        recalls: List[float] = []
        rrs: List[float] = []
        unhits: List[float] = []
        with self._lock, self._conn:
            for case in cases:
                expected = set(json.loads(case["expected_ids"] or "[]"))
                hits = hybrid_search_knowledge(repo, user or {}, case["query"], limit=topK, agent_id=agentId)
                hitIds = [str(h.get("knowledge_id", "")) for h in hits][:topK]
                rr = 0.0
                for rank, hid in enumerate(hitIds, start=1):
                    if hid in expected:
                        rr = 1.0 / rank
                        break
                recall = (len(expected & set(hitIds)) / len(expected)) if expected else 0.0
                unhit = 0.0 if rr > 0 else 1.0
                recalls.append(recall)
                rrs.append(rr)
                unhits.append(unhit)
                self._conn.execute(
                    "INSERT INTO evaluation_findings (run_id, case_id, query, hit_ids,"
                    " reciprocal_rank, recall_at_k, unhit) VALUES (?,?,?,?,?,?,?)",
                    (run_id, case["case_id"], case["query"],
                     json.dumps(hitIds, ensure_ascii=False), rr, recall, int(unhit)),
                )

        return self._writeRun(
            run_id, started, _now(), len(cases), topK, "measured", "",
            {
                "recall_at_k": round(sum(recalls) / len(recalls), 6),
                "mrr": round(sum(rrs) / len(rrs), 6),
                "unhit_rate": round(sum(unhits) / len(unhits), 6),
            },
            note,
            context,
        )

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
                " unhit_rate, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (runId, started, finished, caseCount, topK, measureState, missingReason,
                 contextJson,
                 metrics.get("recall_at_k"), metrics.get("mrr"), metrics.get("unhit_rate"), note),
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
            "started_at": started,
        }

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
