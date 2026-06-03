"""
项目规则管理 API

提供以下端点:
- POST   /v1/rules              创建规则
- GET    /v1/rules              列出规则
- GET    /v1/rules/{rule_id}    获取规则详情
- PUT    /v1/rules/{rule_id}    更新规则
- DELETE /v1/rules/{rule_id}    删除规则
- PUT    /v1/rules/{rule_id}/toggle  切换启用状态
- POST   /v1/rules/{rule_id}/test   测试规则
- GET    /v1/rules/{rule_id}/logs   获取规则日志
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class RuleInfo(BaseModel):
    """规则信息"""
    rule_id: str
    name: str
    description: str = ""
    rule_type: str = "custom"
    trigger: str = ""
    action: str = ""
    enabled: bool = True
    project_id: Optional[str] = None
    execution_count: int = 0
    last_executed: Optional[float] = None
    created_at: float = 0
    updated_at: float = 0


class RuleCreate(BaseModel):
    """创建规则请求"""
    name: str = Field(..., description="规则名称")
    description: str = Field(default="", description="规则描述")
    rule_type: str = Field(default="custom", description="规则类型")
    trigger: str = Field(default="", description="触发条件")
    action: str = Field(default="", description="执行动作")
    project_id: Optional[str] = Field(default=None, description="所属项目ID")


class RuleUpdate(BaseModel):
    """更新规则请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[str] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None


class RuleTestResult(BaseModel):
    """规则测试结果"""
    rule_id: str
    success: bool
    output: str = ""
    execution_time: float = 0


class RuleLog(BaseModel):
    """规则执行日志"""
    log_id: str
    rule_id: str
    trigger: str = ""
    result: str = ""
    success: bool = True
    executed_at: float = 0


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_rules_store: Dict[str, Dict[str, Any]] = {}
_rule_logs: List[Dict[str, Any]] = []


def _get_pm():
    """获取 ProjectManager"""
    try:
        from neurova.projects.project_manager import ProjectManager
        return ProjectManager()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.post("", response_model=RuleInfo)
async def create_rule(body: RuleCreate):
    """创建新规则"""
    rule_id = str(uuid.uuid4())
    now = time.time()

    rule = {
        "rule_id": rule_id,
        "name": body.name,
        "description": body.description,
        "rule_type": body.rule_type,
        "trigger": body.trigger,
        "action": body.action,
        "enabled": True,
        "project_id": body.project_id,
        "execution_count": 0,
        "last_executed": None,
        "created_at": now,
        "updated_at": now,
    }
    _rules_store[rule_id] = rule
    return RuleInfo(**rule)


@router.get("", response_model=List[RuleInfo])
async def list_rules(
    project_id: Optional[str] = Query(default=None),
    enabled_only: bool = Query(default=False),
):
    """列出规则"""
    rules = list(_rules_store.values())
    if project_id:
        rules = [r for r in rules if r.get("project_id") == project_id]
    if enabled_only:
        rules = [r for r in rules if r.get("enabled", True)]
    return [RuleInfo(**r) for r in rules]


@router.get("/{rule_id}", response_model=RuleInfo)
async def get_rule(rule_id: str):
    """获取规则详情"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return RuleInfo(**rule)


@router.put("/{rule_id}", response_model=RuleInfo)
async def update_rule(rule_id: str, body: RuleUpdate):
    """更新规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    for field, value in body.model_dump(exclude_none=True).items():
        rule[field] = value
    rule["updated_at"] = time.time()
    return RuleInfo(**rule)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str):
    """删除规则"""
    if rule_id not in _rules_store:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    del _rules_store[rule_id]
    return {"code": 0, "message": "Rule deleted"}


@router.put("/{rule_id}/toggle")
async def toggle_rule(rule_id: str):
    """切换规则启用状态"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    rule["enabled"] = not rule["enabled"]
    rule["updated_at"] = time.time()
    return {
        "code": 0,
        "message": f"Rule {'enabled' if rule['enabled'] else 'disabled'}",
        "data": {"rule_id": rule_id, "enabled": rule["enabled"]},
    }


@router.post("/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(rule_id: str):
    """测试规则"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    start = time.time()
    # 模拟规则测试
    return RuleTestResult(
        rule_id=rule_id,
        success=True,
        output=f"Rule '{rule['name']}' test passed. Trigger: {rule.get('trigger', 'N/A')}",
        execution_time=time.time() - start,
    )


@router.get("/{rule_id}/logs", response_model=List[RuleLog])
async def get_rule_logs(
    rule_id: str,
    limit: int = Query(default=50, le=200),
):
    """获取规则执行日志"""
    logs = [l for l in _rule_logs if l.get("rule_id") == rule_id]
    return [RuleLog(**l) for l in logs[-limit:]]
