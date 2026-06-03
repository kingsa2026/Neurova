"""
Benchmark 基准测试框架 API 端点 v1.0.0

隔离层级: 用户层 + Agent 层

端点:
  GET  /api/v1/benchmark/suites
  POST /api/v1/benchmark/run
  GET  /api/v1/benchmark/runs
  GET  /api/v1/benchmark/runs/{run_id}
  GET  /api/v1/benchmark/agents/{agent_id}
  POST /api/v1/benchmark/compare
"""

import datetime
import logging
import typing
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Models ─────────────────────────────────────────────

class BenchmarkRunRequest(BaseModel):
    suite_id: str
    agent_id: str
    config: typing.Optional[dict] = None
    tags: typing.List[str] = Field(default_factory=list)


# ── In-memory stores ───────────────────────────────────

_SUITES: typing.List[dict] = [
    {"id": "reasoning-v1", "name": "Logical Reasoning", "description": "Tests logical deduction and problem solving", "tasks": 50, "difficulty": "medium", "category": "reasoning"},
    {"id": "coding-v1", "name": "Code Generation", "description": "Tests code generation and debugging", "tasks": 30, "difficulty": "hard", "category": "coding"},
    {"id": "memory-v1", "name": "Memory Recall", "description": "Tests short-term and long-term memory", "tasks": 40, "difficulty": "easy", "category": "memory"},
    {"id": "creative-v1", "name": "Creative Writing", "description": "Tests creative content generation", "tasks": 20, "difficulty": "medium", "category": "creative"},
    {"id": "multimodal-v1", "name": "Multimodal Understanding", "description": "Tests image/audio understanding", "tasks": 25, "difficulty": "hard", "category": "multimodal"},
]

_RUNS_STORE: typing.Dict[str, dict] = {}  # run_id -> run data
_USER_RUNS: typing.Dict[str, list] = {}  # user_id -> [run_ids]


def _get_user_id(request) -> str:
    return getattr(request.state, "user_id", "anonymous")


# ── Endpoints ──────────────────────────────────────────

@router.get("/suites")
async def list_suites():
    """列出可用的基准测试套件"""
    return {"code": 0, "message": "success", "data": {"suites": _SUITES, "total": len(_SUITES)}}


@router.post("/run")
async def run_benchmark(body: BenchmarkRunRequest, request):
    """执行基准测试"""
    suite = next((s for s in _SUITES if s["id"] == body.suite_id), None)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Suite '{body.suite_id}' not found")

    user_id = _get_user_id(request)
    run_id = str(uuid.uuid4())

    # Simulate benchmark execution
    import random
    tasks_completed = suite["tasks"]
    correct = random.randint(int(tasks_completed * 0.5), int(tasks_completed * 0.95))
    score = round(correct / tasks_completed * 100, 2)
    latency_ms = round(random.uniform(50, 500), 2)

    run_data = {
        "run_id": run_id,
        "suite_id": body.suite_id,
        "suite_name": suite["name"],
        "agent_id": body.agent_id,
        "user_id": user_id,
        "status": "completed",
        "score": score,
        "tasks_total": tasks_completed,
        "tasks_correct": correct,
        "avg_latency_ms": latency_ms,
        "tags": body.tags,
        "config": body.config or {},
        "started_at": datetime.datetime.utcnow().isoformat(),
        "completed_at": datetime.datetime.utcnow().isoformat(),
    }

    _RUNS_STORE[run_id] = run_data
    _USER_RUNS.setdefault(user_id, []).append(run_id)

    logger.info("Benchmark run %s completed: score=%.1f%%", run_id, score)
    return {"code": 0, "message": "Benchmark completed", "data": run_data}


@router.get("/runs")
async def list_runs(request, agent_id: typing.Optional[str] = None, suite_id: typing.Optional[str] = None, page: int = 1, size: int = 20):
    """查询测试运行历史"""
    user_id = _get_user_id(request)
    run_ids = _USER_RUNS.get(user_id, [])
    runs = [_RUNS_STORE[rid] for rid in run_ids if rid in _RUNS_STORE]

    if agent_id:
        runs = [r for r in runs if r.get("agent_id") == agent_id]
    if suite_id:
        runs = [r for r in runs if r.get("suite_id") == suite_id]

    runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    total = len(runs)
    start = (page - 1) * size
    items = runs[start : start + size]

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request):
    """查看某次运行详情"""
    user_id = _get_user_id(request)
    run = _RUNS_STORE.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"code": 0, "message": "success", "data": run}


@router.get("/agents/{agent_id}")
async def get_agent_benchmarks(agent_id: str, request, page: int = 1, size: int = 20):
    """查看某 Agent 的评测历史"""
    user_id = _get_user_id(request)
    run_ids = _USER_RUNS.get(user_id, [])
    runs = [_RUNS_STORE[rid] for rid in run_ids if rid in _RUNS_STORE and _RUNS_STORE[rid].get("agent_id") == agent_id]

    runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    total = len(runs)
    start = (page - 1) * size
    items = runs[start : start + size]

    # Compute aggregates
    if runs:
        avg_score = round(sum(r["score"] for r in runs) / len(runs), 2)
        best_score = max(r["score"] for r in runs)
    else:
        avg_score = 0
        best_score = 0

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "avg_score": avg_score, "best_score": best_score, "page": page, "size": size}}


@router.post("/compare")
async def compare_agents(request_body: dict, request):
    """多 Agent 对比"""
    agent_ids = request_body.get("agent_ids", [])
    suite_id = request_body.get("suite_id")
    user_id = _get_user_id(request)

    if len(agent_ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 agent_ids to compare")

    run_ids = _USER_RUNS.get(user_id, [])
    all_runs = [_RUNS_STORE[rid] for rid in run_ids if rid in _RUNS_STORE]

    results = {}
    for aid in agent_ids:
        agent_runs = [r for r in all_runs if r.get("agent_id") == aid]
        if suite_id:
            agent_runs = [r for r in agent_runs if r.get("suite_id") == suite_id]

        if agent_runs:
            avg_score = round(sum(r["score"] for r in agent_runs) / len(agent_runs), 2)
            best_score = max(r["score"] for r in agent_runs)
            avg_latency = round(sum(r.get("avg_latency_ms", 0) for r in agent_runs) / len(agent_runs), 2)
        else:
            avg_score = best_score = avg_latency = 0

        results[aid] = {"runs": len(agent_runs), "avg_score": avg_score, "best_score": best_score, "avg_latency_ms": avg_latency}

    return {"code": 0, "message": "success", "data": {"comparison": results}}
