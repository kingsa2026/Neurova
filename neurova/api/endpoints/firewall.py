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

from neurova.core.logger import get_logger
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)

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
    # 空值拒绝放 handler（不放 min_length）：PUT 默认实例构造含 value=""，
    # schema 级校验会在 import 期抛 ValidationError。
    value: str = Field(..., description="规则值")
    enabled: bool = Field(default=True, description="是否启用")
    # P3：rate_limit 目标窗口显式字段（minute|hour）。原实现靠
    # "minute" in name.lower() 关键字匹配，名字不含英文关键字时静默不写仍 200。
    window: Optional[str] = Field(default=None, description="rate_limit 窗口: minute|hour")


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

        # IP 白名单规则（P3 读写对称：POST allow 写入后 GET 必须可见，
        # 原实现合成列表不含 allowed_ips → 写了读不回）
        for ip in global_rules.get("allowed_ips", []):
            rules.append(
                FirewallRule(
                    rule_id=f"ip_allow_{ip}",
                    name=f"Allow IP {ip}",
                    rule_type="ip",
                    action="allow",
                    value=ip,
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

        # P3：enabled_only 此前收了从未参与过滤
        if enabled_only:
            rules = [r for r in rules if r.enabled]

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
        if not str(body.value or "").strip():
            raise HTTPException(status_code=400, detail="value 不得为空")
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
            # P3 诚实化：窗口由显式 window 字段指定（缺省回退名称关键字兼容），
            # 无法判定窗口或值非整数 → 400（原静默不写仍返 200）。
            try:
                rate_value = int(body.value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="rate_limit 规则 value 须为整数")
            window = (body.window or "").strip().lower()
            if not window:
                if "minute" in body.name.lower():
                    window = "minute"
                elif "hour" in body.name.lower():
                    window = "hour"
            if window == "minute":
                firewall.update_global_rules({"rate_limit_per_minute": rate_value})
            elif window == "hour":
                firewall.update_global_rules({"rate_limit_per_hour": rate_value})
            else:
                raise HTTPException(
                    status_code=400,
                    detail="rate_limit 规则须指定窗口：window=minute|hour（或规则名含 minute/hour）",
                )

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
    except HTTPException:
        raise
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

        # P3：rate_limit 合成 id 原会 fall-through 到 ip/path 分支静默 no-op
        # 仍返 200 回显（假成功）。现真更新对应全局速率并回读。
        if rule_id in ("rate_limit_minute", "rate_limit_hour"):
            try:
                rate_value = int(body.value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="rate_limit 规则 value 须为整数")
            key = (
                "rate_limit_per_minute"
                if rule_id == "rate_limit_minute"
                else "rate_limit_per_hour"
            )
            firewall.update_global_rules({key: rate_value})
            timestamp = time.time()
            return FirewallRule(
                rule_id=rule_id,
                name=body.name or f"Rate limit per {key.split('_')[-1]}",
                rule_type="rate_limit",
                action="limit",
                value=str(rate_value),
                enabled=True,
                created_at=timestamp,
                updated_at=timestamp,
            )

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

        # P3：速率规则常驻（GET 恒合成），删除语义不成立——原实现谎报 deleted。
        if rule_id in ("rate_limit_minute", "rate_limit_hour"):
            raise HTTPException(
                status_code=400,
                detail="速率限制规则不可删除（请用 PUT /rules/{rule_id} 更新 value）",
            )

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


@router.get("/stats")
async def get_firewall_stats():
    """获取防火墙统计信息"""
    if get_firewall is None:
        raise HTTPException(status_code=503, detail="Firewall service not available")

    try:
        # 规则唯一来源是 firewall 服务（与 /rules 端点一致）。
        # 原代码引用了根本不存在的模块级变量 _firewall_rules_store，
        # 触发 NameError 后被 except 吞掉，导致统计永远返回全 0。
        global_rules = get_firewall().get_global_rules()
        blocked_ips = global_rules.get("blocked_ips", [])
        allowed_ips = global_rules.get("allowed_ips", [])
        blocked_paths = global_rules.get("blocked_paths", [])

        # 规则构成: IP 黑名单 + IP 白名单 + 路径黑名单 + 两条速率限制规则
        total_rules = len(blocked_ips) + len(allowed_ips) + len(blocked_paths) + 2

        return {
            "code": 0,
            "message": "success",
            "data": {
                "total_rules": total_rules,
                "active_rules": total_rules,  # 规则存在即启用，无 enabled 开关
                "blocked_ips": len(blocked_ips),
                "blocked_paths": len(blocked_paths),
            },
        }
    except Exception as e:
        logger.exception("Error getting firewall stats: %s", e)
        return {
            "code": 0,
            "message": "success",
            "data": {"total_rules": 0, "active_rules": 0, "blocked_ips": 0, "blocked_paths": 0},
        }
