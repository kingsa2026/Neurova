"""
任务看板系统 API

提供以下端点:
- POST   /v1/tasks/boards                    创建看板
- GET    /v1/tasks/boards                    列出看板
- GET    /v1/tasks/boards/{board_id}         获取看板详情
- GET    /v1/tasks/boards/{board_id}/tasks   列出看板任务（2026-09-12 P5 补，FE 在调后端缺）
- POST   /v1/tasks/boards/{board_id}/tasks   创建任务
- PUT    /v1/tasks/tasks/{task_id}           更新任务
- PUT    /v1/tasks/tasks/{task_id}/move      移动任务
- GET    /v1/tasks/boards/{board_id}/stats   获取看板统计

2026-09-12 台账清剿 P5a：
- 原 _get_tbs() 依赖不存在的 neurova.projects.task_board（且从无调用方）→ 删；
- store 纯内存 dict 重启即空 → JSON 落盘（NEUROVA_TASKS_PATH，默认 data/tasks_api.json）；
- 字段对齐前端 tasks.ts 契约：board/task 用 id（原 board_id/task_id）、
  状态词汇 todo/in-progress/done（原 "To Do"）、dueDate 透传（原被 pydantic 丢弃）。
"""

from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import json
import os
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)


class BoardInfo(BaseModel):
    """看板信息（FE Board 契约：id/name）"""

    id: str
    name: str
    description: str = ""
    project_id: Optional[str] = None
    columns: List[Dict[str, Any]] = []
    created_at: float = 0
    updated_at: float = 0


class BoardCreate(BaseModel):
    """创建看板请求"""

    name: str = Field(..., description="看板名称")
    description: str = Field(default="", description="看板描述")
    project_id: Optional[str] = Field(default=None, description="所属项目ID")
    columns: List[str] = Field(
        default=["todo", "in-progress", "done"], description="列名列表（FE kanban 词汇）",
    )


class TaskInfo(BaseModel):
    """任务信息（FE Task 契约：id/status todo/dueDate）"""

    id: str
    title: str
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    assignee: Optional[str] = None
    dueDate: str = ""
    board_id: str = ""
    created_at: float = 0
    updated_at: float = 0


class TaskCreate(BaseModel):
    """创建任务请求"""

    title: str = Field(..., description="任务标题")
    description: str = Field(default="", description="任务描述")
    status: str = Field(default="todo", description="状态")
    priority: str = Field(default="medium", description="优先级: low/medium/high/urgent")
    assignee: Optional[str] = Field(default=None, description="指派人")
    dueDate: str = Field(default="", description="截止日期")


class TaskUpdate(BaseModel):
    """更新任务请求"""

    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    dueDate: Optional[str] = None


class TaskMove(BaseModel):
    """移动任务请求"""

    status: str = Field(..., description="目标状态")
    position: int = Field(default=0, description="目标位置")


class BoardStats(BaseModel):
    """看板统计"""

    board_id: str
    total_tasks: int = 0
    by_status: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# JSON 落盘存储（进程内 dict + 写操作即时落盘）
# ---------------------------------------------------------------------------

_STORE_FILE = os.environ.get("NEUROVA_TASKS_PATH", "data/tasks_api.json")

_boards_store: Dict[str, Dict[str, Any]] = {}
_tasks_store: Dict[str, Dict[str, Any]] = {}


def _load_store() -> None:
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            _boards_store.update(raw.get("boards", {}) or {})
            _tasks_store.update(raw.get("tasks", {}) or {})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load tasks store: %s", e)


def _save_store() -> None:
    p = pathlib.Path(_STORE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"boards": _boards_store, "tasks": _tasks_store}, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def _reboot_load() -> None:
    """测试钩子：模拟进程重启（清空内存，从配置路径重载）。"""
    _boards_store.clear()
    _tasks_store.clear()
    global _STORE_FILE
    _STORE_FILE = os.environ.get("NEUROVA_TASKS_PATH", "data/tasks_api.json")
    _load_store()


_load_store()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/boards", response_model=BoardInfo)
async def create_board(body: BoardCreate):
    """创建看板"""
    board_id = str(uuid.uuid4())
    now = time.time()
    columns = [{"name": col, "order": i} for i, col in enumerate(body.columns)]

    board = {
        "id": board_id,
        "name": body.name,
        "description": body.description,
        "project_id": body.project_id,
        "columns": columns,
        "created_at": now,
        "updated_at": now,
    }
    _boards_store[board_id] = board
    _save_store()
    return BoardInfo(**board)


@router.get("/boards", response_model=List[BoardInfo])
async def list_boards(project_id: Optional[str] = Query(default=None)):
    """列出看板"""
    boards = list(_boards_store.values())
    if project_id:
        boards = [b for b in boards if b.get("project_id") == project_id]
    return [BoardInfo(**b) for b in boards]


@router.get("/boards/{board_id}", response_model=BoardInfo)
async def get_board(board_id: str):
    """获取看板详情"""
    board = _boards_store.get(board_id)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_id}' not found")
    return BoardInfo(**board)


@router.get("/boards/{board_id}/tasks", response_model=List[TaskInfo])
async def list_board_tasks(board_id: str):
    """列出看板任务（FE TaskPage fetchTasks 契约）"""
    if board_id not in _boards_store:
        raise HTTPException(status_code=404, detail=f"Board '{board_id}' not found")
    tasks = [t for t in _tasks_store.values() if t.get("board_id") == board_id]
    tasks.sort(key=lambda t: t.get("created_at", 0))
    return [TaskInfo(**t) for t in tasks]


@router.post("/boards/{board_id}/tasks", response_model=TaskInfo)
async def create_task(board_id: str, body: TaskCreate):
    """创建任务"""
    board = _boards_store.get(board_id)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_id}' not found")

    task_id = str(uuid.uuid4())
    now = time.time()
    task = {
        "id": task_id,
        "title": body.title,
        "description": body.description,
        "status": body.status,
        "priority": body.priority,
        "assignee": body.assignee,
        "dueDate": body.dueDate,
        "board_id": board_id,
        "created_at": now,
        "updated_at": now,
    }
    _tasks_store[task_id] = task
    _save_store()
    return TaskInfo(**task)


@router.put("/tasks/{task_id}", response_model=TaskInfo)
async def update_task(task_id: str, body: TaskUpdate):
    """更新任务"""
    task = _tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    for field, value in safe_model_dump(body, exclude_none=True).items():  # s9: pydantic v1 兼容
        task[field] = value
    task["updated_at"] = time.time()
    _save_store()
    return TaskInfo(**task)


@router.put("/tasks/{task_id}/move", response_model=TaskInfo)
async def move_task(task_id: str, body: TaskMove):
    """移动任务"""
    task = _tasks_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    task["status"] = body.status
    task["updated_at"] = time.time()
    _save_store()
    return TaskInfo(**task)


@router.get("/boards/{board_id}/stats", response_model=BoardStats)
async def get_board_stats(board_id: str):
    """获取看板统计"""
    board = _boards_store.get(board_id)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_id}' not found")

    board_tasks = [t for t in _tasks_store.values() if t.get("board_id") == board_id]
    by_status: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}
    for t in board_tasks:
        s = t.get("status", "unknown")
        p = t.get("priority", "medium")
        by_status[s] = by_status.get(s, 0) + 1
        by_priority[p] = by_priority.get(p, 0) + 1

    return BoardStats(
        board_id=board_id,
        total_tasks=len(board_tasks),
        by_status=by_status,
        by_priority=by_priority,
    )
