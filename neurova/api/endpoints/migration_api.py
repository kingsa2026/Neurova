"""
Neurova Zero-Downtime Migration API
零停机迁移系统 RESTful API 端点
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, List
from datetime import datetime

from neurova.core.logger import get_logger
from neurova.storage.zero_downtime_migration import (
    get_migration_manager,
    MigrationStatus,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/migrations", tags=["migrations"])


@router.get("/status/{migration_id}")
async def get_migration_status(migration_id: str):
    """获取迁移状态"""
    manager = get_migration_manager()
    status = manager.get_migration_status(migration_id)
    
    if status is None:
        raise HTTPException(status_code=404, detail="Migration not found")
    
    return {
        "migration_id": migration_id,
        "status": status.value,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/list")
async def list_migrations():
    """列出所有活跃迁移"""
    manager = get_migration_manager()
    migration_ids = manager.list_active_migrations()
    
    return {
        "active_migrations": migration_ids,
        "count": len(migration_ids),
    }


@router.post("/create")
async def create_migration(
    migration_id: str,
    from_schema: str,
    to_schema: str,
    description: str,
    estimated_duration_minutes: float = 60.0,
):
    """创建迁移计划"""
    manager = get_migration_manager()
    
    plan = manager.create_migration_plan(
        migration_id=migration_id,
        from_schema=from_schema,
        to_schema=to_schema,
        description=description,
        estimated_duration_minutes=estimated_duration_minutes,
    )
    
    return {
        "migration_id": migration_id,
        "status": "created",
        "plan": {
            "from_schema": from_schema,
            "to_schema": to_schema,
            "estimated_duration_minutes": estimated_duration_minutes,
        },
    }


@router.post("/add-step/{migration_id}")
async def add_migration_step(
    migration_id: str,
    step_name: str,
    batch_size: int = 1000,
    delay_seconds: float = 0.1,
):
    """添加迁移步骤"""
    manager = get_migration_manager()
    
    try:
        manager.add_migration_step(
            migration_id=migration_id,
            step_name=step_name,
            batch_size=batch_size,
            delay_seconds=delay_seconds,
        )
        
        return {"status": "step_added", "step_name": step_name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/execute/{migration_id}")
async def execute_migration(
    migration_id: str,
    background_tasks: BackgroundTasks,
):
    """执行迁移"""
    manager = get_migration_manager()
    
    try:
        # Execute in background to avoid blocking
        background_tasks.add_task(manager.execute_migration, migration_id)
        
        return {
            "status": "started",
            "migration_id": migration_id,
            "message": "Migration started in background",
        }
    except Exception as e:
        logger.error(f"Migration execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback/{migration_id}")
async def rollback_migration(migration_id: str):
    """回滚迁移"""
    manager = get_migration_manager()
    
    success = manager.rollback_migration(migration_id)
    
    if success:
        return {
            "status": "rolled_back",
            "migration_id": migration_id,
        }
    else:
        raise HTTPException(status_code=500, detail="Rollback failed")


@router.post("/verify/{migration_id}")
async def verify_migration(migration_id: str):
    """验证迁移完整性"""
    manager = get_migration_manager()
    
    is_valid = manager.verify_migration(migration_id)
    
    if is_valid:
        return {
            "status": "verified",
            "migration_id": migration_id,
            "valid": True,
        }
    else:
        raise HTTPException(status_code=400, detail="Verification failed")


@router.get("/history")
async def get_migration_history():
    """获取迁移历史"""
    manager = get_migration_manager()
    
    # Access private attribute for testing
    history = getattr(manager, '_migration_history', [])
    
    return {
        "history": history,
        "count": len(history),
    }
