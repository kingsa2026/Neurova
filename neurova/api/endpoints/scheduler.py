from __future__ import annotations

"""
调度器接口 - Scheduler Endpoint

功能:
1. 获取调度器状态 (GET /api/v1/scheduler/status)
2. 获取任务列表 (GET /api/v1/scheduler/tasks)
3. 添加定时任务 (POST /api/v1/scheduler/tasks)
4. 更新任务 (PUT /api/v1/scheduler/tasks/{id})
5. 删除任务 (DELETE /api/v1/scheduler/tasks/{id})
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user

logger = get_logger(__name__)

router = APIRouter()

# 导入调度器服务
try:
    from neurova.collaborate.workflow.models import ScheduledTask
    from neurova.collaborate.workflow.scheduler import AgentScheduler, get_scheduler
except ImportError:
    logger.warning("Scheduler service not available")
    get_scheduler = None
    AgentScheduler = None
    ScheduledTask = None


class SchedulerStatus(BaseModel):
    """调度器状态"""

    status: str = "running"
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    next_run: Optional[float] = None


class ScheduledTaskResponse(BaseModel):
    """定时任务响应"""

    task_id: str
    name: str
    description: str = ""
    scheduled_at: Optional[float] = None
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    agent_id: str = ""
    action: str = ""
    status: str = "pending"
    created_at: float = 0
    updated_at: float = 0
    last_run_at: Optional[float] = None
    next_run_at: Optional[float] = None
    run_count: int = 0
    max_runs: Optional[int] = None


class TaskCreate(BaseModel):
    """创建任务请求"""

    name: str = Field(..., description="任务名称")
    description: str = Field(default="", description="任务描述")
    action: str = Field(..., description="执行的动作")
    scheduled_at: Optional[float] = Field(default=None, description="计划执行时间")
    interval_seconds: Optional[int] = Field(default=None, description="重复间隔（秒）")
    cron_expression: Optional[str] = Field(default=None, description="Cron表达式")
    agent_id: str = Field(default="", description="执行的Agent ID")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="动作参数")


class TaskUpdate(BaseModel):
    """更新任务请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[float] = None
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    agent_id: Optional[str] = None


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("/status", response_model=SchedulerStatus)
async def get_scheduler_status(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取调度器状态"""
    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()
        stats = scheduler.get_statistics()

        return SchedulerStatus(
            status="running" if stats.get("is_running", False) else "stopped",
            active_tasks=stats.get("running_tasks", 0),
            completed_tasks=stats.get("completed_tasks", 0),
            failed_tasks=stats.get("failed_tasks", 0),
            next_run=None,  # 需要从任务中计算
        )
    except Exception as e:
        logger.exception("Error getting scheduler status: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get scheduler status: {str(e)}")


@router.get("/tasks", response_model=List[ScheduledTaskResponse])
async def get_tasks(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID 筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取任务列表"""
    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()
        tasks = scheduler.list_tasks(status=status)
        if agent_id:
            tasks = [t for t in tasks if (t.agent_id or "") == agent_id]

        # 限制数量
        tasks = tasks[:limit]

        # 转换为API响应格式
        result = []
        for task in tasks:
            result.append(
                ScheduledTaskResponse(
                    task_id=task.task_id,
                    name=task.name,
                    description=task.description or "",
                    scheduled_at=task.scheduled_at,
                    interval_seconds=task.interval_seconds,
                    cron_expression=task.cron_expression,
                    agent_id=task.agent_id,
                    action=task.action,
                    status=task.status,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    last_run_at=task.last_run_at,
                    next_run_at=task.next_run_at,
                    run_count=task.run_count,
                    max_runs=task.max_runs,
                )
            )

        return result
    except Exception as e:
        logger.exception("Error getting tasks: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get tasks: {str(e)}")


@router.post("/tasks", response_model=ScheduledTaskResponse)
async def create_task(
    request: Request,
    body: TaskCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """添加定时任务"""
    _get_request_id(request)

    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()

        # 创建任务
        task = scheduler.schedule_task(
            name=body.name,
            action=body.action,
            agent_id=body.agent_id,
            scheduled_at=body.scheduled_at,
            interval_seconds=body.interval_seconds,
            parameters=body.parameters,
            cron_expression=body.cron_expression,
        )

        # 设置描述
        task.description = body.description

        return ScheduledTaskResponse(
            task_id=task.task_id,
            name=task.name,
            description=task.description,
            scheduled_at=task.scheduled_at,
            interval_seconds=task.interval_seconds,
            cron_expression=task.cron_expression,
            agent_id=task.agent_id,
            action=task.action,
            status=task.status,
            created_at=task.created_at,
            updated_at=task.updated_at,
            last_run_at=task.last_run_at,
            next_run_at=task.next_run_at,
            run_count=task.run_count,
            max_runs=task.max_runs,
        )
    except Exception as e:
        logger.exception("Error creating task: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@router.get("/tasks/{task_id}", response_model=ScheduledTaskResponse)
async def get_task(
    request: Request,
    task_id: str = Path(..., description="任务ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取单个任务详情"""
    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()
        task = scheduler.get_task(task_id)

        if task is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        return ScheduledTaskResponse(
            task_id=task.task_id,
            name=task.name,
            description=task.description or "",
            scheduled_at=task.scheduled_at,
            interval_seconds=task.interval_seconds,
            cron_expression=task.cron_expression,
            agent_id=task.agent_id,
            action=task.action,
            status=task.status,
            created_at=task.created_at,
            updated_at=task.updated_at,
            last_run_at=task.last_run_at,
            next_run_at=task.next_run_at,
            run_count=task.run_count,
            max_runs=task.max_runs,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to get task: {str(e)}")


@router.put("/tasks/{task_id}", response_model=ScheduledTaskResponse)
async def update_task(
    request: Request,
    task_id: str = Path(..., description="任务ID"),
    body: TaskUpdate = TaskUpdate(),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新任务"""
    _get_request_id(request)

    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()
        task = scheduler.get_task(task_id)

        if task is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        # 更新任务属性
        if body.name is not None:
            task.name = body.name
        if body.description is not None:
            task.description = body.description
        if body.scheduled_at is not None:
            task.scheduled_at = body.scheduled_at
        if body.interval_seconds is not None:
            task.interval_seconds = body.interval_seconds
        if body.cron_expression is not None:
            task.cron_expression = body.cron_expression
        if body.agent_id is not None:
            task.agent_id = body.agent_id

        # 更新时间戳
        task.updated_at = time.time()

        # 重算排程: cron/interval 变更后重新预置 next_run_at, 否则旧排程保留/永不到期
        if body.cron_expression is not None or body.interval_seconds is not None:
            from neurova.collaborate.workflow.models import compute_next_run

            task.next_run_at = compute_next_run(
                cron_expression=task.cron_expression,
                interval_seconds=task.interval_seconds,
            )

        return ScheduledTaskResponse(
            task_id=task.task_id,
            name=task.name,
            description=task.description or "",
            scheduled_at=task.scheduled_at,
            interval_seconds=task.interval_seconds,
            cron_expression=task.cron_expression,
            agent_id=task.agent_id,
            action=task.action,
            status=task.status,
            created_at=task.created_at,
            updated_at=task.updated_at,
            last_run_at=task.last_run_at,
            next_run_at=task.next_run_at,
            run_count=task.run_count,
            max_runs=task.max_runs,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update task: {str(e)}")


@router.delete("/tasks/{task_id}")
async def delete_task(
    request: Request,
    task_id: str = Path(..., description="任务ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除任务"""
    request_id = _get_request_id(request)

    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    try:
        scheduler = get_scheduler()
        success = scheduler.remove_task(task_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        return {
            "code": 0,
            "message": f"Task '{task_id}' deleted",
            "data": {"task_id": task_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting task %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete task: {str(e)}")


# ── 立即运行(遗留修复: 前端"立即运行"按钮此前为空操作) ──


@router.post("/tasks/{task_id}/run")
def run_task_now(
    request: Request,
    task_id: str = Path(..., description="任务ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """立即执行任务（同步 def → FastAPI 线程池, 不阻塞事件循环）"""
    _get_request_id(request)

    if get_scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler service not available")

    scheduler = get_scheduler()
    task = scheduler.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    # 重跑: pending/failed 任务直接执行; completed 任务重置为 pending 后可重复触发
    if task.status == "completed":
        task.status = "pending"
        task.next_run_at = None

    scheduler._execute_task(task)
    return {
        "code": 0,
        "message": f"Task '{task_id}' executed",
        "data": {
            "task_id": task.task_id,
            "status": task.status,
            "run_count": task.run_count,
            "result": getattr(task, "last_result", None),
        },
        "request_id": _get_request_id(request),
    }


# 注册调度动作处理器(断点修复): AgentScheduler 此前全仓零注册,
# 任务触发恒 "No handler registered" 失败。模块导入即绑定
# send_message / execute_skill / run_workflow(agent 运行时惰性解析)。
if get_scheduler is not None:
    try:
        from neurova.collaborate.workflow.scheduler import register_action_handlers

        register_action_handlers(get_scheduler())
    except Exception as e:  # noqa: BLE001
        logger.warning("register scheduler action handlers failed: %s", e)
