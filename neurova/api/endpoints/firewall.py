from __future__ import annotations

"""
防火墙接口 - Firewall Endpoint

功能:
1. 获取防火墙规则 (GET /api/v1/firewall/rules)
2. 添加规则 (POST /api/v1/firewall/rules)
3. 更新规则 (PUT /api/v1/firewall/rules/{id})
4. 删除规则 (DELETE /api/v1/firewall/rules/{id})
5. 获取阻止列表 (GET /api/v1/firewall/blocked)
"""

import logging
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# 导入防火墙服务
try:
    from neurova.core.firewall import AgentFirewall, get_firewall
except ImportError:
    logger.warning("Firewall service not available")
    get_firewall = None
    AgentFirewall = None


class FirewallRule(BaseModel):
    """防火墙规则"""

    rule_id: str
    name: str
    rule_type: str = "ip"
    action: str = "block"
    value: str
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0


class FirewallRuleCreate(BaseModel):
    """创建防火墙规则请求"""

    name: str = Field(..., description="规则名称")
    rule_type: str = Field(default="ip", description="规则类型")
    action: str = Field(default="block", description="动作")
    value: str = Field(..., description="规则值")
    enabled: bool = Field(default=True, description="是否启用")


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("/rules", response_model=List[FirewallRule])
async def get_firewall_rules(
    request: Request,
    rule_type: Optional[str] = Query(default=None, description="规则类型筛选"),
    enabled_only: bool = Query(default=False, description="仅显示启用的规则"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取防火墙规则"""
    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        firewall = get_firewall()
        global_rules = firewall.get_global_rules()

        # 转换为规则列表
        rules = []

        # IP规则
        for ip in global_rules.get("blocked_ips", []):
            rules.append(
                FirewallRule(
                    rule_id=f"ip_block_{ip}",
                    name=f"Block IP {ip}",
                    rule_type="ip",
                    action="block",
                    value=ip,
                    enabled=True,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )

        # 路径规则
        for path in global_rules.get("blocked_paths", []):
            rules.append(
                FirewallRule(
                    rule_id=f"path_block_{path}",
                    name=f"Block path {path}",
                    rule_type="path",
                    action="block",
                    value=path,
                    enabled=True,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )

        # 速率限制规则
        rules.append(
            FirewallRule(
                rule_id="rate_limit_minute",
                name="Rate limit per minute",
                rule_type="rate_limit",
                action="limit",
                value=str(global_rules.get("rate_limit_per_minute", 60)),
                enabled=True,
                created_at=time.time(),
                updated_at=time.time(),
            )
        )

        rules.append(
            FirewallRule(
                rule_id="rate_limit_hour",
                name="Rate limit per hour",
                rule_type="rate_limit",
                action="limit",
                value=str(global_rules.get("rate_limit_per_hour", 1000)),
                enabled=True,
                created_at=time.time(),
                updated_at=time.time(),
            )
        )

        # 过滤规则类型
        if rule_type:
            rules = [r for r in rules if r.rule_type == rule_type]

        # 限制数量
        rules = rules[:limit]

        return rules
    except Exception as e:
        logger.exception("Error getting firewall rules: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get firewall rules: {str(e)}")


@router.post("/rules", response_model=FirewallRule)
async def create_firewall_rule(
    request: Request,
    body: FirewallRuleCreate,
):
    """添加防火墙规则"""
    _get_request_id(request)

    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        firewall = get_firewall()

        # 根据规则类型更新防火墙配置
        if body.rule_type == "ip":
            if body.action == "block":
                # 添加到IP黑名单
                global_rules = firewall.get_global_rules()
                blocked_ips = global_rules.get("blocked_ips", [])
                if body.value not in blocked_ips:
                    blocked_ips.append(body.value)
                    firewall.update_global_rules({"blocked_ips": blocked_ips})
            elif body.action == "allow":
                # 添加到IP白名单
                global_rules = firewall.get_global_rules()
                allowed_ips = global_rules.get("allowed_ips", [])
                if body.value not in allowed_ips:
                    allowed_ips.append(body.value)
                    firewall.update_global_rules({"allowed_ips": allowed_ips})
        elif body.rule_type == "path":
            if body.action == "block":
                # 添加到路径黑名单
                global_rules = firewall.get_global_rules()
                blocked_paths = global_rules.get("blocked_paths", [])
                if body.value not in blocked_paths:
                    blocked_paths.append(body.value)
                    firewall.update_global_rules({"blocked_paths": blocked_paths})
        elif body.rule_type == "rate_limit":
            # 更新速率限制
            if "minute" in body.name.lower():
                firewall.update_global_rules({"rate_limit_per_minute": int(body.value)})
            elif "hour" in body.name.lower():
                firewall.update_global_rules({"rate_limit_per_hour": int(body.value)})

        timestamp = time.time()

        return FirewallRule(
            rule_id=f"{body.rule_type}_{body.action}_{body.value}",
            name=body.name,
            rule_type=body.rule_type,
            action=body.action,
            value=body.value,
            enabled=body.enabled,
            created_at=timestamp,
            updated_at=timestamp,
        )
    except Exception as e:
        logger.exception("Error creating firewall rule: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create firewall rule: {str(e)}")


@router.put("/rules/{rule_id}", response_model=FirewallRule)
async def update_firewall_rule(
    request: Request,
    rule_id: str = Path(..., description="规则ID"),
    body: FirewallRuleCreate = FirewallRuleCreate(name="", value=""),
):
    """更新防火墙规则"""
    _get_request_id(request)

    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        firewall = get_firewall()

        # 解析规则ID获取规则类型和值
        parts = rule_id.split("_", 2)
        if len(parts) < 3:
            raise HTTPException(status_code=400, detail="Invalid rule ID format")

        rule_type, action, old_value = parts

        # 根据规则类型更新
        if rule_type == "ip":
            global_rules = firewall.get_global_rules()
            if action == "block":
                blocked_ips = global_rules.get("blocked_ips", [])
                if old_value in blocked_ips:
                    blocked_ips.remove(old_value)
                    if body.value not in blocked_ips:
                        blocked_ips.append(body.value)
                    firewall.update_global_rules({"blocked_ips": blocked_ips})
            elif action == "allow":
                allowed_ips = global_rules.get("allowed_ips", [])
                if old_value in allowed_ips:
                    allowed_ips.remove(old_value)
                    if body.value not in allowed_ips:
                        allowed_ips.append(body.value)
                    firewall.update_global_rules({"allowed_ips": allowed_ips})
        elif rule_type == "path":
            global_rules = firewall.get_global_rules()
            if action == "block":
                blocked_paths = global_rules.get("blocked_paths", [])
                if old_value in blocked_paths:
                    blocked_paths.remove(old_value)
                    if body.value not in blocked_paths:
                        blocked_paths.append(body.value)
                    firewall.update_global_rules({"blocked_paths": blocked_paths})

        timestamp = time.time()

        return FirewallRule(
            rule_id=rule_id,
            name=body.name,
            rule_type=body.rule_type,
            action=body.action,
            value=body.value,
            enabled=body.enabled,
            created_at=timestamp,
            updated_at=timestamp,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating firewall rule %s: %s", rule_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update firewall rule: {str(e)}")


@router.delete("/rules/{rule_id}")
async def delete_firewall_rule(
    request: Request,
    rule_id: str = Path(..., description="规则ID"),
):
    """删除防火墙规则"""
    request_id = _get_request_id(request)

    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        firewall = get_firewall()

        # 解析规则ID获取规则类型和值
        parts = rule_id.split("_", 2)
        if len(parts) < 3:
            raise HTTPException(status_code=400, detail="Invalid rule ID format")

        rule_type, action, value = parts

        # 根据规则类型删除
        if rule_type == "ip":
            global_rules = firewall.get_global_rules()
            if action == "block":
                blocked_ips = global_rules.get("blocked_ips", [])
                if value in blocked_ips:
                    blocked_ips.remove(value)
                    firewall.update_global_rules({"blocked_ips": blocked_ips})
            elif action == "allow":
                allowed_ips = global_rules.get("allowed_ips", [])
                if value in allowed_ips:
                    allowed_ips.remove(value)
                    firewall.update_global_rules({"allowed_ips": allowed_ips})
        elif rule_type == "path":
            global_rules = firewall.get_global_rules()
            if action == "block":
                blocked_paths = global_rules.get("blocked_paths", [])
                if value in blocked_paths:
                    blocked_paths.remove(value)
                    firewall.update_global_rules({"blocked_paths": blocked_paths})

        return {
            "code": 0,
            "message": f"Rule '{rule_id}' deleted",
            "data": {"rule_id": rule_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting firewall rule %s: %s", rule_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete firewall rule: {str(e)}")


@router.get("/blocked")
async def get_blocked_ips(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取阻止列表"""
    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        firewall = get_firewall()
        global_rules = firewall.get_global_rules()

        blocked_ips = global_rules.get("blocked_ips", [])[:limit]
        blocked_paths = global_rules.get("blocked_paths", [])[:limit]

        return {
            "code": 0,
            "message": "success",
            "data": {
                "blocked_ips": blocked_ips,
                "blocked_paths": blocked_paths,
            },
        }
    except Exception as e:
        logger.exception("Error getting blocked list: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get blocked list: {str(e)}")
