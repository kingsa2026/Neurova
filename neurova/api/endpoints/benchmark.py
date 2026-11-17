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
  GET  /api/v1/benchmark/baseline-reports            (S1-1E 只读：多 agent 基线报告列表)
  GET  /api/v1/benchmark/baseline-reports/{report_id} (S1-1E 只读：单份基线报告全文)
"""

import datetime
from neurova.core.logger import get_logger
import threading
import typing
import uuid

from fastapi import APIRouter, HTTPException, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)


# ── Models ─────────────────────────────────────────────


class BenchmarkRunRequest(BaseModel):
    suite_id: str
    agent_id: str
    config: typing.Optional[dict] = None
    tags: typing.List[str] = Field(default_factory=list)


# ── In-memory stores ───────────────────────────────────

_SUITES: typing.List[dict] = [
    {
        "id": "reasoning-v1",
        "name": "Logical Reasoning",
        "description": "Tests logical deduction and problem solving",
        "tasks": 50,
        "difficulty": "medium",
        "category": "reasoning",
    },
    {
        "id": "coding-v1",
        "name": "Code Generation",
        "description": "Tests code generation and debugging",
        "tasks": 30,
        "difficulty": "hard",
        "category": "coding",
    },
    {
        "id": "memory-v1",
        "name": "Memory Recall",
        "description": "Tests short-term and long-term memory",
        "tasks": 40,
        "difficulty": "easy",
        "category": "memory",
    },
    {
        "id": "creative-v1",
        "name": "Creative Writing",
        "description": "Tests creative content generation",
        "tasks": 20,
        "difficulty": "medium",
        "category": "creative",
    },
    {
        "id": "multimodal-v1",
        "name": "Multimodal Understanding",
        "description": "Tests image/audio understanding",
        "tasks": 25,
        "difficulty": "hard",
        "category": "multimodal",
    },
]

_RUNS_STORE: typing.Dict[str, dict] = {}  # run_id -> run data
_USER_RUNS: typing.Dict[str, list] = {}  # user_id -> [run_ids]
_RUNS_LOCK = threading.RLock()


def _get_user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anonymous")


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/suites")
async def list_suites():
    """列出可用的基准测试套件（wired=已接真执行任务库；executable_tasks=可执行题数）。"""
    from neurova.benchmark.suite_eval import getSuiteTasks, suiteWired

    suites = [
        {
            **suite,
            "wired": suiteWired(suite["id"]),
            "executable_tasks": len(getSuiteTasks(suite["id"])),
        }
        for suite in _SUITES
    ]
    return {"code": 0, "message": "success", "data": {"suites": suites, "total": len(suites)}}


def _executeBenchmarkRun(runId: str, suiteId: str, answerFn, limit: typing.Optional[int]) -> None:
    """后台执行真评测并把终态写回运行台账（POST 即返 running，本函数只在线程里跑）。"""
    from neurova.benchmark.suite_eval import getSuiteTasks, runSuite

    try:
        report = runSuite(getSuiteTasks(suiteId), answerFn, limit=limit)
        updates = {
            "status": report["status"],
            "score": report["score"],
            "tasks_total": report["tasks_total"],
            "tasks_correct": report["tasks_correct"],
            "avg_latency_ms": report["avg_latency_ms"],
            "per_task": report["per_task"],
            "executed_at": report["executed_at"],
        }
    except Exception as exc:  # noqa: BLE001 - 执行器意外故障如实落账，不静默
        logger.error("Benchmark run %s executor failed: %s", runId, exc)
        updates = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    with _RUNS_LOCK:
        run = _RUNS_STORE.get(runId)
        if run is not None:
            run.update(updates)
            run["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()


@router.post("/run")
async def run_benchmark(body: BenchmarkRunRequest, request: Request):
    """执行基准测试（N3 真执行器，2026-11-17）。

    历史：原实现用 random.randint 伪造分数/延迟并谎称 completed——P6 诚实化后
    改为记录 simulated 运行（score=None，不编造数字）；当年 `neurova/benchmark`
    门面从未服务过本端点（/suites 用本文件 _SUITES，台账用进程内 _RUNS_STORE），
    已按票④退役。现按 rag_eval 同构模式**新建**真执行器 `neurova.benchmark.suite_eval`：

    - 已接任务库的 suite（reasoning/coding/memory/creative）→ 真执行：被测 agent
      的 LLM 通道（_rag_llm_fn 单一事实源）逐任务作答、按判据打分，产出真实
      tasks_total/tasks_correct/score/avg_latency_ms。执行形态=后台线程+状态查询
      （POST 即返 running，GET /runs/{run_id} 轮询终态），长 suite 不阻塞请求。
    - 未接任务库的 suite（multimodal-v1：文本 LLM 通道无法诚实考多模态）或显式
      config.simulated=true → 保留 simulated 记录路径（score=None，不编造）。
    - 无可用 LLM 通道 → 503 如实拒绝，不伪造回答。
    """
    suite = next((s for s in _SUITES if s["id"] == body.suite_id), None)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Suite '{body.suite_id}' not found")

    from neurova.benchmark.suite_eval import getSuiteTasks

    config = body.config or {}
    tasks = getSuiteTasks(body.suite_id)
    limit = config.get("limit")
    limit = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 1 else None
    simulated = bool(config.get("simulated")) or not tasks

    user_id = _get_user_id(request)
    run_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if simulated:
        reason = "显式 simulated 配置" if config.get("simulated") else "该 suite 未接真执行任务库"
        run_data = {
            "run_id": run_id,
            "suite_id": body.suite_id,
            "suite_name": suite["name"],
            "agent_id": body.agent_id,
            "user_id": user_id,
            "status": "simulated",
            "simulated": True,
            "score": None,
            "tasks_total": suite["tasks"],
            "tasks_correct": None,
            "avg_latency_ms": None,
            "tags": body.tags,
            "config": config,
            "started_at": now,
            "completed_at": now,
        }
        with _RUNS_LOCK:
            _RUNS_STORE[run_id] = run_data
            _USER_RUNS.setdefault(user_id, []).append(run_id)
        logger.info("Benchmark simulated run %s recorded (%s)", run_id, reason)
        return {
            "code": 0,
            "message": f"Benchmark simulated run recorded — {reason}，未产生真实分数",
            "data": run_data,
        }

    answerFn = _rag_llm_fn(body.agent_id)
    if answerFn is None:
        raise HTTPException(status_code=503, detail="LLM 通道不可用（无已配置模型），真评测拒绝伪造回答")

    run_data = {
        "run_id": run_id,
        "suite_id": body.suite_id,
        "suite_name": suite["name"],
        "agent_id": body.agent_id,
        "user_id": user_id,
        "status": "running",
        "simulated": False,
        "score": None,
        "tasks_total": min(len(tasks), limit or len(tasks)),
        "tasks_correct": None,
        "avg_latency_ms": None,
        "tags": body.tags,
        "config": config,
        "started_at": now,
        "completed_at": None,
    }
    with _RUNS_LOCK:
        _RUNS_STORE[run_id] = run_data
        _USER_RUNS.setdefault(user_id, []).append(run_id)

    worker = threading.Thread(
        target=_executeBenchmarkRun,
        args=(run_id, body.suite_id, answerFn, limit),
        name=f"benchmark-run-{run_id[:8]}",
        daemon=True,
    )
    worker.start()
    logger.info("Benchmark run %s started (suite=%s agent=%s tasks=%s)", run_id, body.suite_id, body.agent_id, run_data["tasks_total"])
    return {
        "code": 0,
        "message": "Benchmark run started — 后台执行中，GET /runs/{run_id} 查询进度与结果",
        "data": run_data,
    }


@router.get("/runs")
async def list_runs(
    request: Request,
    agent_id: typing.Optional[str] = None,
    suite_id: typing.Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
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


@router.get("/results")
async def list_results(
    request: Request,
    agent_id: typing.Optional[str] = None,
    suite_id: typing.Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """查询测试结果（别名）"""
    return await list_runs(request, agent_id, suite_id, page, size)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    """查看某次运行详情"""
    user_id = _get_user_id(request)
    run = _RUNS_STORE.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if run.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"code": 0, "message": "success", "data": run}


@router.get("/agents/{agent_id}")
async def get_agent_benchmarks(agent_id: str, request: Request, page: int = 1, size: int = 20):
    """查看某 Agent 的评测历史"""
    user_id = _get_user_id(request)
    run_ids = _USER_RUNS.get(user_id, [])
    runs = [_RUNS_STORE[rid] for rid in run_ids if rid in _RUNS_STORE and _RUNS_STORE[rid].get("agent_id") == agent_id]

    runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    total = len(runs)
    start = (page - 1) * size
    items = runs[start : start + size]

    # Compute aggregates
    # P1-8: simulated 运行的 score 恒为 None（诚实化纪律不编造数字），直接
    # sum/max 会对 None 抛 TypeError 使本端点必 500。过滤 None 后聚合；
    # 无可聚合分数时如实返回 None（前端可选链渲染 '-'，不编造 0 分）。
    scores = [r["score"] for r in runs if r.get("score") is not None]
    if scores:
        avg_score = round(sum(scores) / len(scores), 2)
        best_score = max(scores)
    else:
        avg_score = None
        best_score = None

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": items,
            "total": total,
            "avg_score": avg_score,
            "best_score": best_score,
            "page": page,
            "size": size,
        },
    }


@router.post("/compare")
async def compare_agents(request_body: dict, request: Request):
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
            # P1-8 同根因第二命中点：score/avg_latency_ms 均可为 None
            # （键存在值为 None，`r.get(key, 0)` 的兜底不生效），同款过滤。
            scores = [r["score"] for r in agent_runs if r.get("score") is not None]
            latencies = [
                r["avg_latency_ms"] for r in agent_runs
                if r.get("avg_latency_ms") is not None
            ]
            avg_score = round(sum(scores) / len(scores), 2) if scores else None
            best_score = max(scores) if scores else None
            avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
        else:
            avg_score = best_score = avg_latency = None

        results[aid] = {
            "runs": len(agent_runs),
            "avg_score": avg_score,
            "best_score": best_score,
            "avg_latency_ms": avg_latency,
        }

    return {"code": 0, "message": "success", "data": {"comparison": results}}


# ── S1-1E：多 agent 协作评测基线报告（只读） ────────────────────────────
# 数据源 = BenchRunner.runAllWithReport 的既有落盘（report.saveReport →
# <数据根>/benchmark/multi_agent/*.json），本端点只读取回，不建第二套存储。


@router.get("/baseline-reports")
async def list_baseline_reports(request: Request):
    """列出多 agent 协作评测基线报告（新→旧，含 usage/轨迹聚合列与隔离注记）。"""
    from neurova.benchmark.multi_agent.report import listReports

    items = listReports()
    return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}


@router.get("/baseline-reports/{report_id}")
async def get_baseline_report(report_id: str, request: Request):
    """取回单份基线报告全文（逐任务含 usage 与轨迹列）。"""
    from neurova.benchmark.multi_agent.report import loadReport

    report = loadReport(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Baseline report '{report_id}' not found")
    return {"code": 0, "message": "success", "data": report}


# ── RAG 评估──


class RagDatasetCreateRequest(BaseModel):
    name: str = Field(..., description="数据集名称")
    description: str = ""
    items: typing.List[dict] = Field(default_factory=list, description='[{query, gold_chunk_ids:[knowledge_id#chunk_index], gold_answer?}]')


class RagGenerateRequest(BaseModel):
    sample_n: int = Field(10, ge=1, le=200, description="采样锚块数")
    neighbors: int = Field(1, ge=0, le=10, description="同条目邻居窗口")
    agent_id: str = "default"
    save_as_dataset: bool = False


class RagEvaluateRequest(BaseModel):
    dataset_id: str
    top_k: int = Field(5, ge=1, le=50)
    agent_id: str = "default"
    use_judge: bool = False


@router.get("/rag-datasets")
async def rag_datasets_list():
    from neurova.benchmark.rag_eval import load_datasets

    return {"code": 0, "data": {"datasets": load_datasets()}}


@router.post("/rag-datasets")
async def rag_datasets_create(body: RagDatasetCreateRequest):
    from neurova.benchmark.rag_eval import save_dataset

    ds = save_dataset(body.model_dump())
    return {"code": 0, "data": ds}


@router.put("/rag-datasets/{dataset_id}")
async def rag_datasets_update(dataset_id: str, body: RagDatasetCreateRequest):
    from neurova.benchmark.rag_eval import save_dataset

    try:
        ds = save_dataset(body.model_dump(), dataset_id=dataset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return {"code": 0, "data": ds}


@router.delete("/rag-datasets/{dataset_id}")
async def rag_datasets_delete(dataset_id: str):
    from neurova.benchmark.rag_eval import delete_dataset

    if not delete_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return {"code": 0, "message": "Dataset deleted"}


def _rag_llm_fn(agent_id: str):
    """出题/Judge 的同步 LLM 通道（graph_bridge 同款：agent 候选 llm_client）。"""
    from neurova.api.endpoints import defaultAgentId, get_agent_instance

    clients = []
    for agent in (get_agent_instance(agent_id=agent_id), get_agent_instance(agent_id=defaultAgentId())):
        client = getattr(agent, "llm_client", None) if agent else None
        if client is not None and client not in clients:
            clients.append(client)
    if not clients:
        return None

    def _call(prompt: str) -> str:
        from neurova.mem_core import run_async_safely

        for client in clients:
            try:
                resp = run_async_safely(client.chat([{"role": "user", "content": prompt}]))
            except Exception:  # noqa: BLE001 - 换下一个候选
                continue
            content = getattr(resp, "content", "") or ""
            if content.startswith("[LLM Error]"):
                continue
            return content
        return ""

    return _call


@router.post("/rag-datasets/generate")
async def rag_datasets_generate(
    body: RagGenerateRequest,
    current_user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    """自动出题（锚块=可见知识条目块，gold=`knowledge_id#chunk_index`）。

    LLM 通道不可用时如实 503——拒绝伪造题目（simulated 诚实纪律）。
    LLM 调用 N 次为秒级重活，to_thread 隔离不阻塞事件循环。
    """
    import asyncio as _asyncio

    from neurova.benchmark.rag_dataset_gen import generate_items
    from neurova.knowledge.repository import get_knowledge_repository

    llm_fn = _rag_llm_fn(body.agent_id)
    if llm_fn is None:
        raise HTTPException(status_code=503, detail="LLM 通道不可用（无已配置模型），自动出题拒绝伪造")

    repo = get_knowledge_repository()
    items = repo.visible_items(current_user, scope="all", agent_id=body.agent_id)
    result = await _asyncio.to_thread(
        generate_items, items, body.sample_n, body.neighbors, llm_fn
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    if body.save_as_dataset:
        from neurova.benchmark.rag_eval import save_dataset

        result["saved_dataset_id"] = save_dataset(result["dataset"])["id"]
    return {"code": 0, "data": result}


@router.post("/rag-evaluate")
async def rag_evaluate(
    body: RagEvaluateRequest,
    current_user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    """对数据集跑真检索评估（P/R/F1@K；use_judge 时逐题 LLM 二值判分）。"""
    from neurova.benchmark.rag_eval import evaluate_dataset, load_datasets
    from neurova.knowledge.repository import get_knowledge_repository

    ds = next((d for d in load_datasets() if d["id"] == body.dataset_id), None)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{body.dataset_id}' not found")

    repo = get_knowledge_repository()

    def _retrieve(query: str, top_k: int):
        ordered = []
        for item in repo.search_visible_items(
            current_user, query, agent_id=body.agent_id, limit=top_k
        ):
            kid = item.get("knowledge_id", "")
            for h in item.get("chunk_hits") or []:
                ordered.append(f"{kid}#{h.get('chunk_index')}")
        return ordered

    judge_fn = None
    if body.use_judge:
        raw = _rag_llm_fn(body.agent_id)
        if raw is not None:
            def judge_fn(question, expected, context):
                reply = raw(
                    f"判断以下回答是否正确回答了问题（只答 true/false）。\n"
                    f"问题：{question}\n标准答案：{expected}\n检索上下文：{context[:2000]}"
                )
                return "true" in reply.lower()

    report = await __import__("asyncio").to_thread(
        evaluate_dataset, ds, _retrieve, body.top_k, (1, 3, 5, 10), judge_fn
    )
    return {"code": 0, "data": report}


@router.get("/health-rag")
async def rag_health():
    """RAG 评估能力就绪探针（benchmark 执行器接线状态）。"""
    from neurova.benchmark.rag_eval import load_datasets

    return {"code": 0, "data": {"rag_executor": "wired", "datasets": len(load_datasets())}}
