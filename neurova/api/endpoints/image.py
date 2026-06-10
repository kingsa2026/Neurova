"""
Image 定义管道 API 端点 v1.0.0

隔离层级: 全局

端点:
  GET  /api/v1/image/templates
  GET  /api/v1/image/templates/{name}
  POST /api/v1/image/build
  GET  /api/v1/image/builds
  GET  /api/v1/image/builds/{build_id}
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from neurova.image_pipeline import get_image_pipeline_manager, BuildStatus

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class BuildRequest(BaseModel):
    """构建请求"""
    template_name: str = Field(..., description="模板名称")
    tag: str = Field(..., description="镜像标签")
    build_args: Dict[str, str] = Field(default_factory=dict, description="构建参数")
    no_cache: bool = Field(default=False, description="是否禁用缓存")
    platform: str = Field(default="linux/amd64", description="目标平台")


class ImageTemplate(BaseModel):
    """镜像模板"""
    name: str
    description: str = ""
    base_image: str = ""
    dockerfile_content: str = ""
    build_args: List[Dict[str, str]] = []
    tags: List[str] = []
    created_at: float = 0
    updated_at: float = 0


class BuildRecord(BaseModel):
    """构建记录"""
    build_id: str
    template_name: str
    tag: str
    status: str = "pending"  # pending, building, success, failed
    started_at: float = 0
    finished_at: Optional[float] = None
    duration: Optional[float] = None
    error_message: Optional[str] = None
    image_id: Optional[str] = None
    build_args: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_templates_store: Dict[str, Dict[str, Any]] = {
    "ubuntu-base": {
        "name": "ubuntu-base",
        "description": "Ubuntu 基础镜像模板",
        "base_image": "ubuntu:22.04",
        "dockerfile_content": "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y python3",
        "build_args": [],
        "tags": ["latest", "22.04"],
        "created_at": time.time(),
        "updated_at": time.time(),
    },
    "python-ai": {
        "name": "python-ai",
        "description": "Python AI 开发环境",
        "base_image": "python:3.11-slim",
        "dockerfile_content": "FROM python:3.11-slim\nRUN pip install torch transformers",
        "build_args": [{"name": "PYTHON_VERSION", "default": "3.11"}],
        "tags": ["latest", "gpu"],
        "created_at": time.time(),
        "updated_at": time.time(),
    },
}

_builds_store: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _generate_build_id() -> str:
    """生成构建 ID"""
    import uuid
    return f"build-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/templates")
async def list_templates():
    """列出可用的镜像模板"""
    templates = list(_templates_store.values())
    return {
        "code": 0,
        "data": {
            "templates": templates,
            "total": len(templates),
        },
    }


@router.get("/templates/{name}")
async def get_template(name: str):
    """查看镜像模板详情"""
    template = _templates_store.get(name)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    return {
        "code": 0,
        "data": template,
    }


@router.post("/build")
async def build_image(body: BuildRequest):
    """构建自定义镜像"""
    # 获取 ImagePipelineManager
    manager = get_image_pipeline_manager()
    
    # 检查模板是否存在
    template = manager.get_template(body.template_name)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{body.template_name}' not found")
    
    # 构建镜像
    result = manager.build_image(
        template_id=body.template_name,
        custom_tags=[body.tag] if body.tag else None,
        build_args=body.build_args,
        platform=body.platform,
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Build failed"))
    
    build_data = result["build"]
    
    return {
        "code": 0,
        "message": f"Build started for template '{body.template_name}' with tag '{body.tag}'",
        "data": {
            "build_id": build_data["build_id"],
            "status": build_data["status"],
            "image_tag": build_data.get("image_tag"),
            "image_id": build_data.get("metadata", {}).get("image_id"),
            "duration_seconds": build_data.get("duration_seconds"),
        },
    }


@router.get("/builds")
async def list_builds(
    template_name: Optional[str] = Query(default=None, description="按模板名称筛选"),
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    limit: int = Query(default=50, le=200),
):
    """查看构建历史"""
    builds = list(_builds_store.values())
    
    if template_name:
        builds = [b for b in builds if b.get("template_name") == template_name]
    if status:
        builds = [b for b in builds if b.get("status") == status]
    
    # 按开始时间降序排序
    builds.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    
    return {
        "code": 0,
        "data": {
            "builds": builds[:limit],
            "total": len(builds),
        },
    }


@router.get("/builds/{build_id}")
async def get_build(build_id: str):
    """查看某次构建详情"""
    build = _builds_store.get(build_id)
    if not build:
        raise HTTPException(status_code=404, detail=f"Build '{build_id}' not found")
    
    return {
        "code": 0,
        "data": build,
    }