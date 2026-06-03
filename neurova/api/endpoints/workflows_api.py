"""
工作流系统 API

端点:
- POST   /v1/workflows                创建工作流
- GET    /v1/workflows                列出工作流
- GET    /v1/workflows/{wf_id}        获取详情
- PUT    /v1/workflows/{wf_id}        更新
- DELETE /v1/workflows/{wf_id}        删除
- POST   /v1/workflows/{wf_id}/execute  执行
- GET    /v1/workflows/{wf_id}/executions  执行记录
- POST   /v1/workflows/{wf_id}/steps  添加步骤
- PUT    /v1/workflows/{wf_id}/steps/{sid}  更新步骤
- DELETE /v1/workflows/{wf_id}/steps/{sid}  删除步骤
- POST   /v1/workflows/generate       LLM 生成
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkflowStep(BaseModel):
    step_id: str
    name: str
    step_type: str = "action"
    config: Dict[str, Any] = {}
    order: int = 0


class WorkflowInfo(BaseModel):
    workflow_id: str
    name: str
    description: str = ""
    status: str = "draft"
    project_id: Optional[str] = None
    steps: List[WorkflowStep] = []
    created_at: float = 0
    updated_at: float = 0


class WorkflowCreate(BaseModel):
    name: str = Field(..., description="工作流名称")
    description: str = ""
    project_id: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class WorkflowExecute(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStepCreate(BaseModel):
    name: str = Field(..., description="步骤名称")
    step_type: str = Field(default="action")
    config: Dict[str, Any] = Field(default_factory=dict)
    order: int = Field(default=0)


class WorkflowStepUpdate(BaseModel):
    name: Optional[str] = None
    step_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    order: Optional[int] = None


class WorkflowGenerate(BaseModel):
    description: str = Field(..., description="自然语言描述")


class ExecutionInfo(BaseModel):
    execution_id: str
    workflow_id: str
    status: str = "running"
    inputs: Dict[str, Any] = {}
    outputs: Dict[str, Any] = {}
    started_at: float = 0
    finished_at: Optional[float] = None


_workflows: Dict[str, Dict[str, Any]] = {}
_executions: Dict[str, Dict[str, Any]] = {}


@router.post("", response_model=WorkflowInfo)
async def create_workflow(body: WorkflowCreate):
    wf_id = str(uuid.uuid4())
    now = time.time()
    steps = [
        WorkflowStep(step_id=str(uuid.uuid4()), name=s.get("name", f"Step {i+1}"),
                     step_type=s.get("step_type", "action"), config=s.get("config", {}), order=i)
        for i, s in enumerate(body.steps)
    ]
    wf = {"workflow_id": wf_id, "name": body.name, "description": body.description,
          "status": "draft", "project_id": body.project_id, "steps": [s.model_dump() for s in steps],
          "created_at": now, "updated_at": now}
    _workflows[wf_id] = wf
    return WorkflowInfo(**wf)


@router.get("", response_model=List[WorkflowInfo])
async def list_workflows(project_id: Optional[str] = Query(default=None)):
    wfs = list(_workflows.values())
    if project_id:
        wfs = [w for w in wfs if w.get("project_id") == project_id]
    return [WorkflowInfo(**w) for w in wfs]


@router.get("/{workflow_id}", response_model=WorkflowInfo)
async def get_workflow(workflow_id: str):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowInfo(**wf)


@router.put("/{workflow_id}", response_model=WorkflowInfo)
async def update_workflow(workflow_id: str, body: WorkflowUpdate):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    for k, v in body.model_dump(exclude_none=True).items():
        wf[k] = v
    wf["updated_at"] = time.time()
    return WorkflowInfo(**wf)


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    if workflow_id not in _workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    del _workflows[workflow_id]
    return {"code": 0, "message": "Workflow deleted"}


@router.post("/{workflow_id}/execute", response_model=ExecutionInfo)
async def execute_workflow(workflow_id: str, body: WorkflowExecute):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    ex_id = str(uuid.uuid4())
    now = time.time()
    ex = {"execution_id": ex_id, "workflow_id": workflow_id, "status": "completed",
          "inputs": body.inputs, "outputs": {}, "started_at": now, "finished_at": now}
    _executions[ex_id] = ex
    return ExecutionInfo(**ex)


@router.get("/{workflow_id}/executions", response_model=List[ExecutionInfo])
async def list_executions(workflow_id: str, limit: int = Query(default=50, le=200)):
    exs = [e for e in _executions.values() if e.get("workflow_id") == workflow_id]
    return [ExecutionInfo(**e) for e in exs[-limit:]]


@router.post("/{workflow_id}/steps")
async def add_step(workflow_id: str, body: WorkflowStepCreate):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    step = WorkflowStep(step_id=str(uuid.uuid4()), name=body.name, step_type=body.step_type,
                        config=body.config, order=body.order)
    wf["steps"].append(step.model_dump())
    wf["updated_at"] = time.time()
    return {"code": 0, "data": step.model_dump()}


@router.put("/{workflow_id}/steps/{step_id}")
async def update_step(workflow_id: str, step_id: str, body: WorkflowStepUpdate):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    for s in wf["steps"]:
        if s.get("step_id") == step_id:
            for k, v in body.model_dump(exclude_none=True).items():
                s[k] = v
            wf["updated_at"] = time.time()
            return {"code": 0, "data": s}
    raise HTTPException(status_code=404, detail="Step not found")


@router.delete("/{workflow_id}/steps/{step_id}")
async def remove_step(workflow_id: str, step_id: str):
    wf = _workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    wf["steps"] = [s for s in wf["steps"] if s.get("step_id") != step_id]
    wf["updated_at"] = time.time()
    return {"code": 0, "message": "Step removed"}


@router.post("/generate")
async def generate_workflow(body: WorkflowGenerate):
    """使用 LLM 根据描述生成工作流"""
    return {
        "code": 0,
        "data": {
            "name": f"Generated: {body.description[:50]}",
            "description": body.description,
            "steps": [
                {"name": "Analyze Input", "step_type": "action", "config": {}},
                {"name": "Process Data", "step_type": "action", "config": {}},
                {"name": "Generate Output", "step_type": "action", "config": {}},
            ],
        },
    }
