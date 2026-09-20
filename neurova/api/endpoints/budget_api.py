"""
Budget Management API Endpoints

Provides RESTful API for budget management, monitoring, and alerting.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import List, Optional, Dict
from decimal import Decimal
from datetime import datetime
import time
from neurova.models.cost_budget import get_budget_service, BudgetService, AlertLevel

router = APIRouter(prefix="/budgets", tags=["budgets"])


# ============================================================================
# Pydantic Models
# ============================================================================

class BudgetCreate(BaseModel):
    """Request model for creating a budget"""
    scope: str  # hourly, daily, monthly, agent, provider, model
    identifier: str
    amount: float
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    auto_reset: bool = True
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }


class BudgetResponse(BaseModel):
    """Response model for budget information"""
    id: Optional[str] = None
    scope: str
    identifier: str
    amount: float
    usage: float
    remaining: float
    percentage: float
    is_active: bool
    is_over_budget: bool
    created_at: Optional[datetime] = None
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            datetime: lambda v: v.isoformat()
        }


class BudgetStatusResponse(BaseModel):
    """Comprehensive budget status response"""
    scope: str
    identifier: str
    usage: float
    remaining: float
    percentage: float
    is_over_budget: bool
    alerts_triggered: List[Dict] = []


class AlertConfigUpdate(BaseModel):
    """Request model for updating alert configuration"""
    level: str
    enabled: bool
    channels: Optional[List[str]] = None
    message_template: Optional[str] = None


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/status/{agent_id}")
async def get_agent_budget_status(
    agent_id: str,
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Get budget status for a specific agent.
    
    Returns current usage, remaining budget, and percentage for the agent's hourly budget.
    """
    try:
        status = budget_service.get_agent_budget_status(agent_id)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/all")
async def get_all_budget_statuses(
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Get budget status for all registered budgets.
    
    Useful for admin dashboard to show overview of all budgets.
    """
    try:
        statuses = budget_service.get_all_budget_statuses()
        return {"budgets": list(statuses.values())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/record")
async def record_cost(
    agent_id: str,
    provider: str,
    model: str,
    cost: float,
    turn_id: Optional[str] = None,
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Record LLM call cost against budgets.
    
    This endpoint can be called by @track_llm_call decorator or manually.
    Automatically checks all relevant budgets and triggers alerts if thresholds exceeded.
    """
    try:
        budget_service.record_llm_call_cost(
            agent_id=agent_id,
            provider=provider,
            model=model,
            cost=Decimal(str(cost)),
            turn_id=turn_id
        )
        
        return {
            "success": True,
            "cost_recorded": cost,
            "agent_id": agent_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to record cost: {str(e)}")


@router.get("/{scope}/{identifier}/status")
async def get_budget_status(
    scope: str,
    identifier: str,
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Get detailed status for a specific budget.
    
    Includes usage, remaining, percentage, and triggered alerts.
    """
    from neurova.models.cost_budget import BudgetScope
    
    try:
        budget_scope = BudgetScope(scope)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope: {scope}. Must be one of: {[s.value for s in BudgetScope]}"
        )
    
    try:
        usage = budget_service.manager.get_usage(budget_scope, identifier)
        remaining = budget_service.manager.get_remaining(budget_scope, identifier)
        percentage = budget_service.manager.get_usage_percentage(budget_scope, identifier)
        is_over_budget = budget_service.manager.is_over_budget(budget_scope, identifier)
        
        return {
            "scope": scope,
            "identifier": identifier,
            "usage": float(usage),
            "remaining": float(remaining),
            "percentage": float(percentage),
            "is_over_budget": is_over_budget,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts")
async def get_alerts(
    limit: int = 100,
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Get recent alerts (implementation pending).
    
    TODO: Implement alert history storage and retrieval.
    Currently returns a placeholder response.
    """
    # TODO: Query alerts from database
    return {
        "alerts": [],
        "total": 0,
        "limit": limit
    }


@router.post("/alerts/config/update")
async def update_alert_config(
    config: AlertConfigUpdate,
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Update alert configuration.
    
    Allows enabling/disabling alerts, changing notification channels,
    and customizing alert message templates.
    """
    from neurova.models.cost_budget import AlertLevel, AlertChannel
    
    try:
        # Find and update alert config
        alert_level = AlertLevel(config.level)
        found = False
        
        for alert_config in budget_service.manager._alert_configs:
            if alert_config.level == alert_level:
                alert_config.enabled = config.enabled
                
                if config.channels:
                    alert_config.channels = [
                        AlertChannel(channel) for channel in config.channels
                    ]
                    
                if config.message_template:
                    alert_config.message_template = config.message_template
                    
                found = True
                break
                
        if not found:
            raise HTTPException(
                status_code=404,
                detail=f"Alert level not found: {config.level}"
            )
            
        return {
            "success": True,
            "updated": {
                "level": config.level,
                "enabled": config.enabled,
                "channels": config.channels,
                "message_template": config.message_template
            }
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def budget_health_check(
    budget_service: BudgetService = Depends(get_budget_service)
):
    """
    Health check endpoint for budget system.
    
    Verifies that budget service is initialized and operational.
    """
    return {
        "status": "healthy",
        "service_initialized": budget_service._initialized,
        "total_budgets": len(budget_service.manager._budgets),
        "active_alerts": sum(
            1 for config in budget_service.manager._alert_configs if config.enabled
        ),
        "timestamp": datetime.now().isoformat()
    }
