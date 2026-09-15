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
from neurova.core.logger import get_logger
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


def _get_user_id(request: Request) -> str:
    return getattr(request.state, "user_id", "anonymous")


# ── Endpoints ──────────────────────────────────────────


@router.get("/suites")
async def list_suites():
    """列出可用的基准测试套件"""
    return {"code": 0, "message": "success", "data": {"suites": _SUITES, "total": len(_SUITES)}}


@router.post("/run")
async def run_benchmark(body: BenchmarkRunRequest, request: Request):
    """执行基准测试（2026-09-12 P6 诚实化）

    原实现用 random.randint 伪造分数/延迟并谎称 status=completed——假数据。
    真实评测执行器（neurova/benchmark 框架 + LLM 答题打分）未接线，属功能
    决策项（登记台账），本端点不投机实现；现如实记录一次 simulated 运行：
    仅登记"跑了个模拟"的事实，score 等指标一律 None，不编造数字。
    """
    suite = next((s for s in _SUITES if s["id"] == body.suite_id), None)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Suite '{body.suite_id}' not found")

    user_id = _get_user_id(request)
    run_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

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
        "config": body.config or {},
        "started_at": now,
        "completed_at": now,
    }

    _RUNS_STORE[run_id] = run_data
    _USER_RUNS.setdefault(user_id, []).append(run_id)

    logger.info("Benchmark simulated run %s recorded (engine not wired)", run_id)
    return {
        "code": 0,
        "message": "Benchmark simulated run recorded — 评测执行器未接线，未产生真实分数",
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
    if runs:
        avg_score = round(sum(r["score"] for r in runs) / len(runs), 2)
        best_score = max(r["score"] for r in runs)
    else:
        avg_score = 0
        best_score = 0

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
            avg_score = round(sum(r["score"] for r in agent_runs) / len(agent_runs), 2)
            best_score = max(r["score"] for r in agent_runs)
            avg_latency = round(sum(r.get("avg_latency_ms", 0) for r in agent_runs) / len(agent_runs), 2)
        else:
            avg_score = best_score = avg_latency = 0

        results[aid] = {
            "runs": len(agent_runs),
            "avg_score": avg_score,
            "best_score": best_score,
            "avg_latency_ms": avg_latency,
        }

    return {"code": 0, "message": "success", "data": {"comparison": results}}


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
    from neurova.api.endpoints import get_agent_instance

    clients = []
    for agent in (get_agent_instance(agent_id=agent_id), get_agent_instance(agent_id="default")):
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
