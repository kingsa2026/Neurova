"""
项目规则管理 API

提供以下端点:
- POST   /v1/rules              创建规则
- GET    /v1/rules              列出规则
- GET    /v1/rules/{rule_id}    获取规则详情
- PUT    /v1/rules/{rule_id}    更新规则
- DELETE /v1/rules/{rule_id}    删除规则
- PUT    /v1/rules/{rule_id}/toggle  切换启用状态
- POST   /v1/rules/{rule_id}/test   测试规则（结构校验并记录执行日志）
- GET    /v1/rules/{rule_id}/logs   获取规则日志

2026-09-12 台账清剿 P5c：
- 死 import（neurova.projects.project_manager，_get_pm 从无调用方）删除；
- 纯内存 store → JSON 落盘（NEUROVA_RULES_PATH，默认 data/rules_api.json），
  执行日志随测试动作真实写入（原 _rule_logs 全仓无写入方，logs 页签恒空）；
- 字段对齐前端 rules.ts 契约（id/condition/action/active/priority，
  原 rule_id/trigger/enabled 错位）；
- POST /test 原"模拟规则测试"写死 success=True（假成功）→ 改为结构校验：
  condition/action 缺失 → 400，通过则记一条执行日志。
"""

from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import datetime
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


class RuleInfo(BaseModel):
    """规则信息（FE Rule 契约）"""

    id: str
    name: str
    description: str = ""
    rule_type: str = "custom"
    condition: str = ""
    action: str = ""
    priority: str = "medium"
    active: bool = True
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
    condition: str = Field(default="", description="触发条件")
    action: str = Field(default="", description="执行动作")
    priority: str = Field(default="medium", description="优先级")
    project_id: Optional[str] = Field(default=None, description="所属项目ID")


class RuleUpdate(BaseModel):
    """更新规则请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[str] = None
    action: Optional[str] = None
    priority: Optional[str] = None
    active: Optional[bool] = None


class RuleTestResult(BaseModel):
    """规则测试结果"""

    rule_id: str
    success: bool
    output: str = ""
    execution_time: float = 0


class RuleLog(BaseModel):
    """规则执行日志（FE ExecutionLog 契约）"""

    id: str
    ruleId: str
    timestamp: str = ""
    success: bool = True
    detail: str = ""


# ---------------------------------------------------------------------------
# JSON 落盘存储
# ---------------------------------------------------------------------------

_STORE_FILE = os.environ.get("NEUROVA_RULES_PATH", "data/rules_api.json")

_rules_store: Dict[str, Dict[str, Any]] = {}
_rule_logs: List[Dict[str, Any]] = []


def _load_store() -> None:
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            _rules_store.update(raw.get("rules", {}) or {})
            logs = raw.get("logs", []) or []
            _rule_logs.extend(logs if isinstance(logs, list) else [])
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load rules store: %s", e)


def _save_store() -> None:
    p = pathlib.Path(_STORE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"rules": _rules_store, "logs": _rule_logs[-1000:]}, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def _reboot_load() -> None:
    """测试钩子：模拟进程重启。"""
    _rules_store.clear()
    _rule_logs.clear()
    global _STORE_FILE
    _STORE_FILE = os.environ.get("NEUROVA_RULES_PATH", "data/rules_api.json")
    _load_store()


_load_store()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=RuleInfo)
async def create_rule(body: RuleCreate):
    """创建新规则"""
    now = time.time()
    rule = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "rule_type": body.rule_type,
        "condition": body.condition,
        "action": body.action,
        "priority": body.priority,
        "active": True,
        "project_id": body.project_id,
        "execution_count": 0,
        "last_executed": None,
        "created_at": now,
        "updated_at": now,
    }
    _rules_store[rule["id"]] = rule
    _save_store()
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
        rules = [r for r in rules if r.get("active", True)]
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

    for field, value in safe_model_dump(body, exclude_none=True).items():  # s9: pydantic v1 兼容
        rule[field] = value
    rule["updated_at"] = time.time()
    _save_store()
    return RuleInfo(**rule)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str):
    """删除规则"""
    if rule_id not in _rules_store:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    del _rules_store[rule_id]
    _save_store()
    return {"code": 0, "message": "Rule deleted"}


@router.put("/{rule_id}/toggle")
async def toggle_rule(rule_id: str):
    """切换规则启用状态"""
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    rule["active"] = not rule.get("active", True)
    rule["updated_at"] = time.time()
    _save_store()
    return {
        "code": 0,
        "message": f"Rule {'enabled' if rule['active'] else 'disabled'}",
        "data": {"rule_id": rule_id, "active": rule["active"]},
    }


@router.post("/{rule_id}/test", response_model=RuleTestResult)
async def test_rule(rule_id: str):
    """测试规则（结构校验，结果写入执行日志）

    2026-09-12 诚实化：原实现"模拟规则测试"写死 success=True。规则无执行引擎，
    可验证的最小真实语义 = 结构完整性（条件与动作均须声明）。不完整 → 400。
    """
    rule = _rules_store.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")

    start = time.time()
    problems = []
    if not str(rule.get("condition", "")).strip():
        problems.append("condition 未定义")
    if not str(rule.get("action", "")).strip():
        problems.append("action 未定义")
    passed = not problems
    detail = "结构校验通过" if passed else "；".join(problems)

    _rule_logs.append({
        "id": str(uuid.uuid4()),
        "ruleId": rule_id,
        "timestamp": datetime.datetime.fromtimestamp(start, datetime.timezone.utc).isoformat(),
        "success": passed,
        "detail": detail,
    })
    if passed:
        rule["execution_count"] = int(rule.get("execution_count", 0)) + 1
        rule["last_executed"] = start
    _save_store()

    if not passed:
        raise HTTPException(status_code=400, detail=f"规则测试未通过: {detail}")
    return RuleTestResult(
        rule_id=rule_id,
        success=True,
        output=f"Rule '{rule['name']}' 结构校验通过",
        execution_time=time.time() - start,
    )


@router.get("/{rule_id}/logs", response_model=List[RuleLog])
async def get_rule_logs(
    rule_id: str,
    limit: int = Query(default=50, le=200),
):
    """获取规则执行日志"""
    logs = [l for l in _rule_logs if l.get("ruleId") == rule_id]
    return [RuleLog(**l) for l in logs[-limit:]]
