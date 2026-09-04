"""工作流评估子系统（Dify 对标 §3.5：「用 benchmark 跑道孵化工作流评估，
不要上企业评测平台」）。

定位：输入样例集 + 确定性断言的工作流评估——不引入 LLM 判分
（确定性断言优先，与 benchmark 哲学一致）；直接调 WorkflowExecutor
（不经 HTTP 层，无鉴权/Agent 依赖），前端/benchmark 跑道复用同一入口。

断言五型：
- output_contains / output_equals：终态输出（instance.outputs 或末节点
  result）包含/等于期望
- output_json_path：点路径取值（输出为 JSON 字符串时先解析）
- status_equals：执行终态（completed/failed/...）
- node_completed：指定节点成功完成（node_results[node_id].status）

失败语义：单样例断言失败/工作流异常只记 failed + reason，不中断整批。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# 断言
# ══════════════════════════════════════════════════════════════

_ASSERTION_KINDS = ("output_contains", "output_equals", "output_json_path", "status_equals", "node_completed")


def eval_assertion(kind: str, value: Any = None, path: str = "") -> Callable[[Any], bool]:
    """断言工厂：kind + 参数 → 谓词 callable（未知 kind 抛 ValueError）"""
    kind = (kind or "").strip().lower()
    if kind == "output_contains":
        def _contains(actual: Any) -> bool:
            if actual is None:
                return False
            if isinstance(actual, (dict, list)):
                text = json.dumps(actual, ensure_ascii=False, default=str)
            else:
                text = str(actual)
            return str(value) in text
        return _contains

    if kind == "output_equals":
        def _equals(actual: Any) -> bool:
            if isinstance(value, (dict, list)) and isinstance(actual, str):
                try:
                    actual = json.loads(actual)
                except (json.JSONDecodeError, ValueError):
                    return False
            return actual == value
        return _equals

    if kind == "output_json_path":
        def _json_path(actual: Any) -> bool:
            data = actual
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    return False
            cur: Any = data
            for part in (path or "").split("."):
                if not part:
                    continue
                if isinstance(cur, dict):
                    cur = cur.get(part)
                elif isinstance(cur, list) and part.isdigit():
                    idx = int(part)
                    cur = cur[idx] if idx < len(cur) else None
                else:
                    return False
                if cur is None and part != (path or "").split(".")[-1]:
                    return False
            return cur == value
        return _json_path

    if kind == "status_equals":
        def _status(actual: Any) -> bool:
            actual_v = getattr(actual, "value", actual)
            return str(actual_v) == str(value)
        return _status

    if kind == "node_completed":
        def _node(results: Dict[str, Any]) -> bool:
            r = (results or {}).get(str(value))
            if r is None:
                return False
            status = getattr(r, "status", None)
            status = getattr(status, "value", status)
            return status in ("success", "completed")
        return _node

    raise ValueError(f"未知断言类型: {kind!r}（有效: {_ASSERTION_KINDS}）")


# ══════════════════════════════════════════════════════════════
# 样例集
# ══════════════════════════════════════════════════════════════


@dataclass
class EvalCase:
    """评估样例：输入 + 断言集"""

    name: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    assertions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "inputs": self.inputs, "assertions": self.assertions}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalCase":
        return cls(
            name=str(d.get("name", "")),
            inputs=dict(d.get("inputs") or {}),
            assertions=list(d.get("assertions") or []),
        )


@dataclass
class EvalSuite:
    """评估套件：样例集 + 元信息"""

    name: str = ""
    description: str = ""
    cases: List[EvalCase] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "cases": [c.to_dict() for c in self.cases],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalSuite":
        return cls(
            name=str(d.get("name", "")),
            description=str(d.get("description", "")),
            cases=[EvalCase.from_dict(c) for c in (d.get("cases") or []) if isinstance(c, dict)],
        )


# ══════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════


@dataclass
class EvalReport:
    """评估报告（JSON 可序列化，benchmark 历史复用）"""

    suite_name: str = ""
    workflow_id: str = ""
    total: int = 0
    case_results: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "workflow_id": self.workflow_id,
            "total": self.total,
            "case_results": self.case_results,
            "summary": self.summary,
            "duration_ms": round(self.duration_ms, 2),
            **({"error": self.error} if self.error else {}),
        }


# ══════════════════════════════════════════════════════════════
# 评估入口
# ══════════════════════════════════════════════════════════════


def _final_output(instance) -> Any:
    """终态输出：outputs 优先，缺省时回退末序节点的 result"""
    if instance.outputs:
        return instance.outputs
    results = getattr(instance, "node_results", {}) or {}
    if not results:
        return None
    last = max(results.values(), key=lambda r: getattr(r, "finished_at", 0) or 0)
    return getattr(last, "result", None)


async def evaluate_workflow(storage, workflow_id: str, suite: EvalSuite, user_id: Optional[str] = None) -> EvalReport:
    """评估一个工作流：逐样例执行 + 逐断言判定（单例失败不中断整批）"""
    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

    started = time.time()
    report = EvalReport(suite_name=suite.name, workflow_id=workflow_id, total=len(suite.cases))

    workflow = storage.get_workflow(workflow_id)
    if workflow is None:
        report.error = "workflow_not_found"
        report.duration_ms = (time.time() - started) * 1000
        return report

    executor = get_workflow_executor()
    passed = failed = 0

    for case in suite.cases:
        case_started = time.time()
        entry: Dict[str, Any] = {
            "case": case.name,
            "status": "failed",
            "assertion_results": [],
            "duration_ms": 0.0,
            "reason": "",
        }
        try:
            instance = await executor.execute(workflow, dict(case.inputs), user_id=user_id)
            final = _final_output(instance)
            node_results = getattr(instance, "node_results", {}) or {}
            instance_status = getattr(getattr(instance, "status", None), "value", "")

            all_ok = True
            for a in case.assertions:
                kind = str(a.get("kind", ""))
                predicate = eval_assertion(kind, value=a.get("value"), path=a.get("path", ""))
                if kind == "status_equals":
                    actual: Any = instance_status
                elif kind == "node_completed":
                    actual = node_results
                else:
                    actual = final
                ok = bool(predicate(actual))
                entry["assertion_results"].append({
                    "kind": kind,
                    "value": a.get("value"),
                    "path": a.get("path", ""),
                    "passed": ok,
                })
                if not ok:
                    all_ok = False

            entry["status"] = "passed" if all_ok else "failed"
        except Exception as e:  # noqa: BLE001 — 样例级失败不中断整批
            logger.warning("评估样例 %r 执行失败: %s", case.name, e)
            entry["reason"] = str(e)[:300]

        if entry["status"] == "passed":
            passed += 1
        else:
            failed += 1
        entry["duration_ms"] = round((time.time() - case_started) * 1000, 2)
        report.case_results.append(entry)

    report.summary = {"passed": passed, "failed": failed}
    report.duration_ms = (time.time() - started) * 1000
    return report
