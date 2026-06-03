# -*- coding: utf-8 -*-
"""
Agent 协作 API 端点

提供 Agent 间协作相关的 API：
1. GET /api/agents/capabilities - 获取所有 Agent 能力矩阵
2. POST /api/agents/collaborate - 发起 Agent 协作
3. GET /api/agents/templates - 获取协作模板列表
4. POST /api/agents/templates - 创建协作模板
5. GET /api/agents/templates/{template_id} - 获取指定模板
6. DELETE /api/agents/templates/{template_id} - 删除模板
7. POST /api/agents/recommend - 获取任务推荐
8. GET /api/agents/matrix - 获取能力矩阵总览

多用户隔离机制:
- 所有操作基于 JWT Token 中的用户信息进行权限验证
- 普通用户只能访问自己有权访问的 Agent 协作功能
- 管理员可以访问所有协作功能
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from neurova.interfaces.api_standard import APIResponse, APIError, ErrorCodes
from neurova.api.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Agent 协作"])


# ==================== 辅助函数 ====================


def _user_can_access_agent_collaboration(user: Dict[str, Any], agent_id: str) -> bool:
    """
    检查用户是否有权访问 Agent 协作功能

    参数:
        user: 当前用户字典（从 get_current_user 依赖项获取）
        agent_id: Agent ID

    返回:
        用户是否有权访问
    """
    if not user:
        return False

    # 管理员可以访问所有 Agent 协作功能
    if user.get("role") == "admin":
        return True

    # 检查用户是否有权访问该 Agent
    from neurova.api.app import app_state
    if agent_id in app_state.agents:
        agent = app_state.agents[agent_id]
        if hasattr(agent, 'owner_id') and agent.owner_id == user.get("username"):
            return True

        if hasattr(agent, 'shared_with'):
            shared_with = agent.shared_with
            if isinstance(shared_with, list) and user.get("username") in shared_with:
                return True
            elif isinstance(shared_with, dict) and user.get("username") in shared_with:
                return True

    return False


# ==================== 请求/响应模型 ====================


class CapabilityRegistration(BaseModel):
    """能力注册请求"""
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = Field(..., description="Agent 名称")
    capabilities: List[Dict[str, Any]] = Field(..., description="能力列表")
    status: str = Field("online", description="状态: online/offline/busy")


class CollaborationRequest(BaseModel):
    """发起协作请求"""
    template_id: Optional[str] = Field(None, description="协作模板ID")
    participants: List[str] = Field(..., description="参与者 Agent ID 列表")
    task_description: str = Field(..., description="任务描述")
    required_capabilities: List[str] = Field(default=[], description="所需能力")
    priority: str = Field("normal", description="优先级: low/normal/high/urgent")
    timeout_seconds: int = Field(3600, description="超时时间")


class TemplateCreateRequest(BaseModel):
    """创建模板请求"""
    name: str = Field(..., description="模板名称")
    description: str = Field(..., description="模板描述")
    template_type: str = Field("custom", description="模板类型")
    roles: Dict[str, str] = Field(default={}, description="角色分配")
    role_requirements: Dict[str, List[str]] = Field(default={}, description="角色能力要求")
    workflow: Dict[str, Any] = Field(..., description="工作流定义")
    max_participants: int = Field(5, description="最大参与者数")
    min_participants: int = Field(2, description="最小参与者数")
    tags: List[str] = Field(default=[], description="标签")


class TemplateUpdateRequest(BaseModel):
    """更新模板请求"""
    name: Optional[str] = Field(None, description="模板名称")
    description: Optional[str] = Field(None, description="模板描述")
    roles: Optional[Dict[str, str]] = Field(None, description="角色分配")
    workflow: Optional[Dict[str, Any]] = Field(None, description="工作流定义")
    tags: Optional[List[str]] = Field(None, description="标签")


class TaskRecommendRequest(BaseModel):
    """任务推荐请求"""
    required_capabilities: List[str] = Field(..., description="所需能力")
    min_match_score: float = Field(0.5, description="最小匹配度")
    max_results: int = Field(5, description="最大结果数")


# ==================== 依赖函数 ====================


def get_capability_discovery():
    """获取能力发现服务"""
    from neurova.agent.protocols.capability_discovery import get_capability_discovery
    return get_capability_discovery()


def get_template_manager():
    """获取模板管理器"""
    from neurova.agent.templates import get_template_manager
    return get_template_manager()


def get_agent_matrix():
    """获取能力矩阵"""
    from neurova.agent.matrix import get_agent_matrix
    return get_agent_matrix()


def get_dead_letter_queue():
    """获取死信队列"""
    from neurova.agent.protocols.dead_letter_queue import get_dead_letter_queue
    return get_dead_letter_queue()


# ==================== 能力相关 API ====================


@router.get("/capabilities", summary="获取所有 Agent 能力矩阵")
async def get_all_agent_capabilities(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """
    获取所有已注册 Agent 的能力矩阵（多用户隔离）
    
    普通用户只能看到自己有权访问的 Agent 能力，
    管理员可以看到所有 Agent 能力。
    
    Returns:
        Agent 能力列表和统计信息
    """
    try:
        discovery = get_capability_discovery()
        matrix = get_agent_matrix()
        
        # 根据用户信息过滤 Agent 列表
        if user.get("role") == "admin":
            # 管理员可以看到所有 Agent
            agents = discovery.list_agents()
        else:
            # 普通用户只能看到自己有权访问的 Agent
            from neurova.api.app import app_state
            agents = []
            for agent_id, agent in app_state.agents.items():
                if _user_can_access_agent_collaboration(user, agent_id):
                    agent_cap = discovery.get_agent_capability(agent_id)
                    if agent_cap:
                        agents.append(agent_cap)
        
        agent_matrices = []
        
        for agent_cap in agents:
            matrix_data = matrix.get_agent_matrix(agent_cap.agent_id)
            if matrix_data:
                agent_matrices.append(matrix_data.to_dict())
        
        # 获取能力矩阵总览
        summary = matrix.get_matrix_summary()
        
        return APIResponse.ok(
            data={
                "agents": agent_matrices,
                "summary": summary,
                "total_count": len(agent_matrices),
                "user_role": user.get("role", "user"),
            },
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取能力矩阵失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取能力矩阵失败: {str(e)}")


@router.get("/capabilities/{agent_id}", summary="获取指定 Agent 能力")
async def get_agent_capability_detail(agent_id: str, request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """
    获取指定 Agent 的详细能力信息（多用户隔离）
    
    普通用户只能访问自己有权访问的 Agent 能力，
    管理员可以访问所有 Agent 能力。
    
    Args:
        agent_id: Agent ID
    """
    try:
        # 检查用户是否有权访问该 Agent
        if not user.get("role") == "admin" and not _user_can_access_agent_collaboration(user, agent_id):
            raise APIError.forbidden("无权访问此 Agent 的能力信息")
        
        discovery = get_capability_discovery()
        matrix = get_agent_matrix()
        
        agent_cap = discovery.get_agent_capability(agent_id)
        if not agent_cap:
            raise APIError.not_found(f"Agent 不存在: {agent_id}")
        
        matrix_data = matrix.get_agent_matrix(agent_id)
        
        return APIResponse.ok(
            data=matrix_data.to_dict() if matrix_data else agent_cap.to_dict(),
            message="获取成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"获取Agent能力失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取Agent能力失败: {str(e)}")


@router.post("/capabilities/register", summary="注册 Agent 能力")
async def register_agent_capability(data: CapabilityRegistration, request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """
    注册 Agent 能力信息（多用户隔离）
    
    普通用户只能注册自己有权访问的 Agent 能力，
    管理员可以注册所有 Agent 能力。
    
    Args:
        data: 能力注册数据
    """
    try:
        # 检查用户是否有权注册该 Agent 的能力
        if not user.get("role") == "admin" and not _user_can_access_agent_collaboration(user, data.agent_id):
            raise APIError.forbidden("无权注册此 Agent 的能力信息")
        
        from neurova.agent.protocols.capability_discovery import (
            AgentCapability,
            Capability,
            CapabilityCategory,
            CapabilityLevel,
        )
        
        discovery = get_capability_discovery()
        
        # 构建能力列表
        capabilities = []
        for cap_data in data.capabilities:
            cap = Capability(
                name=cap_data.get("name", ""),
                category=CapabilityCategory(cap_data.get("category", "technical")),
                level=CapabilityLevel(cap_data.get("level", "intermediate")),
                description=cap_data.get("description", ""),
                keywords=cap_data.get("keywords", []),
                examples=cap_data.get("examples", []),
                metrics=cap_data.get("metrics", {}),
            )
            capabilities.append(cap)
        
        # 创建 Agent 能力对象
        agent_cap = AgentCapability(
            agent_id=data.agent_id,
            agent_name=data.agent_name,
            capabilities=capabilities,
            status=data.status,
        )
        
        # 注册
        discovery.register_agent(agent_cap)
        
        return APIResponse.ok(
            data={"agent_id": data.agent_id, "registered": True},
            message="能力注册成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"注册Agent能力失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"注册Agent能力失败: {str(e)}")


@router.delete("/capabilities/{agent_id}", summary="注销 Agent 能力")
async def unregister_agent_capability(agent_id: str, request: Request):
    """
    注销 Agent 能力信息
    
    Args:
        agent_id: Agent ID
    """
    try:
        discovery = get_capability_discovery()
        
        success = discovery.unregister_agent(agent_id)
        
        if not success:
            raise APIError.not_found(f"Agent 不存在: {agent_id}")
        
        return APIResponse.ok(
            data={"agent_id": agent_id, "unregistered": True},
            message="能力注销成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"注销Agent能力失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"注销Agent能力失败: {str(e)}")


# ==================== 协作相关 API ====================


@router.post("/collaborate", summary="发起 Agent 协作")
async def start_collaboration(data: CollaborationRequest, request: Request):
    """
    发起 Agent 协作会话
    
    Args:
        data: 协作请求数据
    """
    try:
        from neurova.agent.protocols.message_protocol import (
            AgentMessage,
            MessagePriority,
            MessageType,
        )
        from neurova.api.app import app_state
        from neurova.api.endpoints.agent import load_agents_config
        
        # 验证参与者是否存在（检查运行时注册的 Agent + 配置文件中的 Agent）
        config_agent_ids = {cfg["agent_id"] for cfg in load_agents_config()}
        for participant_id in data.participants:
            if participant_id not in app_state.agents and participant_id not in config_agent_ids:
                raise APIError.bad_request(f"参与者不存在: {participant_id}")
        
        # 获取推荐（矩阵可能为空，跳过错误）
        recommendations = []
        try:
            matrix = get_agent_matrix()
            if data.required_capabilities:
                recommendations = matrix.recommend_agents(
                    data.required_capabilities,
                    min_match_score=0.5,
                )
        except Exception:
            pass
        
        # 创建协作会话ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # 记录协作请求
        collaboration = {
            "session_id": session_id,
            "template_id": data.template_id,
            "participants": data.participants,
            "task_description": data.task_description,
            "required_capabilities": data.required_capabilities,
            "priority": data.priority,
            "timeout_seconds": data.timeout_seconds,
            "status": "initiated",
            "created_at": datetime.now().isoformat(),
            "recommendations": [r.to_dict() for r in recommendations],
        }
        
        return APIResponse.ok(
            data=collaboration,
            message="协作会话已创建",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"发起协作失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"发起协作失败: {str(e)}")


# ==================== 模板相关 API ====================


@router.get("/templates", summary="获取协作模板列表")
async def get_templates(
    template_type: str = None,
    tags: str = None,
    request: Request = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取协作模板列表（多用户隔离）
    
    普通用户只能看到自己有权访问的模板，
    管理员可以看到所有模板。
    
    Args:
        template_type: 按类型过滤
        tags: 按标签过滤（逗号分隔）
    """
    try:
        manager = get_template_manager()
        
        # 解析标签
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        
        # 获取模板列表
        templates = manager.list_templates(
            template_type=template_type if template_type else None,
            tags=tag_list,
        )
        
        # 根据用户权限过滤模板
        if user.get("role") != "admin":
            # 普通用户只能看到自己创建的模板
            username = user.get("username", "")
            templates = [t for t in templates if hasattr(t, 'created_by') and t.created_by == username]
        
        return APIResponse.ok(
            data={
                "templates": [t.to_dict() for t in templates],
                "total_count": len(templates),
                "user_role": user.get("role", "user"),
            },
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取模板列表失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取模板列表失败: {str(e)}")


@router.get("/templates/preset", summary="获取预设模板列表")
async def get_preset_templates(request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    获取所有预设模板（多用户隔离）
    
    所有用户都可以查看预设模板。
    """
    try:
        from neurova.agent.templates import PRESET_TEMPLATES
        
        return APIResponse.ok(
            data={
                "templates": [t.to_dict() for t in PRESET_TEMPLATES],
                "total_count": len(PRESET_TEMPLATES),
                "user_role": user.get("role", "user"),
            },
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取预设模板失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取预设模板失败: {str(e)}")


@router.get("/templates/{template_id}", summary="获取指定模板")
async def get_template_detail(template_id: str, request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    获取指定模板的详细信息（多用户隔离）
    
    普通用户只能查看自己有权访问的模板，
    管理员可以查看所有模板。
    
    Args:
        template_id: 模板ID
    """
    try:
        manager = get_template_manager()
        
        template = manager.get_template(template_id)
        if not template:
            raise APIError.not_found(f"模板不存在: {template_id}")
        
        # 检查用户是否有权访问此模板
        if user.get("role") != "admin":
            username = user.get("username", "")
            if hasattr(template, 'created_by') and template.created_by != username:
                raise APIError.forbidden("无权访问此模板")
        
        return APIResponse.ok(
            data=template.to_dict(),
            message="获取成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"获取模板详情失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取模板详情失败: {str(e)}")


@router.post("/templates", summary="创建协作模板")
async def create_template(data: TemplateCreateRequest, request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    创建新的协作模板（多用户隔离）
    
    普通用户只能创建自己的模板，
    管理员可以创建所有模板。
    
    Args:
        data: 模板创建数据
    """
    try:
        from neurova.agent.templates import CollaborationTemplate
        from neurova.agent.templates.collaboration_template import (
            TemplateType,
            AgentRole,
            WorkflowDefinition,
            TaskStep,
        )
        
        manager = get_template_manager()
        
        # 构建工作流
        workflow_data = data.workflow
        steps = []
        for step_data in workflow_data.get("steps", []):
            step = TaskStep(
                step_id=step_data.get("step_id", ""),
                name=step_data.get("name", ""),
                description=step_data.get("description", ""),
                assigned_role=AgentRole(step_data.get("assigned_role", "participant")),
                required_capabilities=step_data.get("required_capabilities", []),
                input_requirements=step_data.get("input_requirements", {}),
                output_produces=step_data.get("output_produces", []),
                depends_on=step_data.get("depends_on", []),
                timeout_seconds=step_data.get("timeout_seconds", 300),
                optional=step_data.get("optional", False),
            )
            steps.append(step)
        
        workflow = WorkflowDefinition(
            workflow_id=workflow_data.get("workflow_id", ""),
            name=workflow_data.get("name", ""),
            description=workflow_data.get("description", ""),
            steps=steps,
            parallel_allowed=workflow_data.get("parallel_allowed", False),
            max_concurrent_steps=workflow_data.get("max_concurrent_steps", 2),
            rollback_on_failure=workflow_data.get("rollback_on_failure", True),
        )
        
        # 构建模板，添加创建者信息
        template = CollaborationTemplate(
            name=data.name,
            description=data.description,
            template_type=TemplateType(data.template_type),
            roles={k: AgentRole(v) for k, v in data.roles.items()},
            role_requirements=data.role_requirements,
            workflow=workflow,
            max_participants=data.max_participants,
            min_participants=data.min_participants,
            tags=data.tags,
            is_preset=False,
            created_by=user.get("username", "unknown"),
        )
        
        # 验证并注册
        success = manager.register_template(template)
        if not success:
            raise APIError.bad_request("模板验证失败")
        
        return APIResponse.ok(
            data=template.to_dict(),
            message="模板创建成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"创建模板失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"创建模板失败: {str(e)}")


@router.put("/templates/{template_id}", summary="更新协作模板")
async def update_template(
    template_id: str,
    data: TemplateUpdateRequest,
    request: Request = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    更新协作模板（多用户隔离）
    
    普通用户只能更新自己创建的模板，
    管理员可以更新所有模板。
    
    Args:
        template_id: 模板ID
        data: 更新数据
    """
    try:
        manager = get_template_manager()
        
        template = manager.get_template(template_id)
        if not template:
            raise APIError.not_found(f"模板不存在: {template_id}")
        
        if template.is_preset:
            raise APIError.bad_request("预设模板不能修改")
        
        # 检查用户是否有权更新此模板
        if user.get("role") != "admin":
            username = user.get("username", "")
            if not hasattr(template, 'created_by') or template.created_by != username:
                raise APIError.forbidden("无权更新此模板")
        
        # 更新字段
        if data.name is not None:
            template.name = data.name
        if data.description is not None:
            template.description = data.description
        if data.roles is not None:
            from neurova.agent.templates.collaboration_template import AgentRole
            template.roles = {k: AgentRole(v) for k, v in data.roles.items()}
        if data.workflow is not None:
            # 重新构建工作流
            from neurova.agent.templates.collaboration_template import WorkflowDefinition, TaskStep, AgentRole
            workflow_data = data.workflow
            steps = []
            for step_data in workflow_data.get("steps", []):
                step = TaskStep(
                    step_id=step_data.get("step_id", ""),
                    name=step_data.get("name", ""),
                    description=step_data.get("description", ""),
                    assigned_role=AgentRole(step_data.get("assigned_role", "participant")),
                    required_capabilities=step_data.get("required_capabilities", []),
                    input_requirements=step_data.get("input_requirements", {}),
                    output_produces=step_data.get("output_produces", []),
                    depends_on=step_data.get("depends_on", []),
                    timeout_seconds=step_data.get("timeout_seconds", 300),
                    optional=step_data.get("optional", False),
                )
                steps.append(step)
            template.workflow = WorkflowDefinition(
                workflow_id=workflow_data.get("workflow_id", ""),
                name=workflow_data.get("name", ""),
                description=workflow_data.get("description", ""),
                steps=steps,
                parallel_allowed=workflow_data.get("parallel_allowed", False),
                max_concurrent_steps=workflow_data.get("max_concurrent_steps", 2),
                rollback_on_failure=workflow_data.get("rollback_on_failure", True),
            )
        if data.tags is not None:
            template.tags = data.tags
        
        template.updated_at = datetime.now().timestamp()
        
        return APIResponse.ok(
            data=template.to_dict(),
            message="模板更新成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"更新模板失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"更新模板失败: {str(e)}")


@router.delete("/templates/{template_id}", summary="删除协作模板")
async def delete_template(template_id: str, request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    删除协作模板（多用户隔离）
    
    普通用户只能删除自己创建的模板，
    管理员可以删除所有模板。
    
    Args:
        template_id: 模板ID
    """
    try:
        manager = get_template_manager()
        
        template = manager.get_template(template_id)
        if not template:
            raise APIError.not_found(f"模板不存在: {template_id}")
        
        if template.is_preset:
            raise APIError.bad_request("预设模板不能删除")
        
        # 检查用户是否有权删除此模板
        if user.get("role") != "admin":
            username = user.get("username", "")
            if not hasattr(template, 'created_by') or template.created_by != username:
                raise APIError.forbidden("无权删除此模板")
        
        success = manager.unregister_template(template_id)
        
        return APIResponse.ok(
            data={"template_id": template_id, "deleted": success},
            message="模板删除成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"删除模板失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"删除模板失败: {str(e)}")


@router.post("/templates/{template_id}/clone", summary="克隆模板")
async def clone_template(template_id: str, new_name: str = None, request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    克隆协作模板（多用户隔离）
    
    普通用户只能克隆自己有权访问的模板，
    管理员可以克隆所有模板。
    
    Args:
        template_id: 模板ID
        new_name: 新模板名称
    """
    try:
        manager = get_template_manager()
        
        # 检查用户是否有权访问此模板
        if user.get("role") != "admin":
            template = manager.get_template(template_id)
            if template and hasattr(template, 'created_by') and template.created_by != user.get("username", ""):
                raise APIError.forbidden("无权克隆此模板")
        
        cloned = manager.clone_template(template_id, new_name)
        if not cloned:
            raise APIError.not_found(f"模板不存在: {template_id}")
        
        # 设置新模板的创建者
        if hasattr(cloned, 'created_by'):
            cloned.created_by = user.get("username", "unknown")
        
        return APIResponse.ok(
            data=cloned.to_dict(),
            message="模板克隆成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"克隆模板失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"克隆模板失败: {str(e)}")


# ==================== 任务推荐 API ====================


@router.post("/recommend", summary="获取任务推荐")
async def get_task_recommendations(data: TaskRecommendRequest, request: Request = None, user: Dict[str, Any] = Depends(get_current_user)):
    """
    根据所需能力推荐合适的 Agent（多用户隔离）
    
    普通用户只能看到自己有权访问的 Agent 推荐，
    管理员可以看到所有 Agent 推荐。
    
    Args:
        data: 推荐请求
    """
    try:
        matrix = get_agent_matrix()
        
        recommendations = matrix.recommend_agents(
            required_capabilities=data.required_capabilities,
            min_match_score=data.min_match_score,
            max_results=data.max_results,
        )
        
        # 根据用户权限过滤推荐结果
        if user.get("role") != "admin":
            # 普通用户只能看到自己有权访问的 Agent
            filtered_recommendations = []
            for r in recommendations:
                if hasattr(r, 'agent_id') and _user_can_access_agent_collaboration(user, r.agent_id):
                    filtered_recommendations.append(r)
            recommendations = filtered_recommendations
        
        return APIResponse.ok(
            data={
                "recommendations": [r.to_dict() for r in recommendations],
                "total_count": len(recommendations),
                "user_role": user.get("role", "user"),
            },
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取推荐失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取推荐失败: {str(e)}")


# ==================== 能力矩阵 API ====================


@router.get("/matrix", summary="获取能力矩阵总览")
async def get_capability_matrix_summary(request: Request = None):
    """
    获取所有 Agent 的能力矩阵总览
    """
    try:
        matrix = get_agent_matrix()
        summary = matrix.get_matrix_summary()
        
        return APIResponse.ok(
            data=summary,
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取能力矩阵失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取能力矩阵失败: {str(e)}")


@router.post("/matrix/compare", summary="对比 Agent 能力")
async def compare_agents_capabilities(
    agent_ids: List[str],
    request: Request = None,
):
    """
    对比多个 Agent 的能力
    
    Args:
        agent_ids: Agent ID 列表
    """
    try:
        matrix = get_agent_matrix()
        comparison = matrix.compare_agents(agent_ids)
        
        return APIResponse.ok(
            data=comparison,
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"对比Agent能力失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"对比Agent能力失败: {str(e)}")


# ==================== 死信队列 API ====================


@router.get("/dlq/stats", summary="获取死信队列统计")
async def get_dlq_stats(request: Request = None):
    """
    获取死信队列统计信息
    """
    try:
        dlq = get_dead_letter_queue()
        stats = dlq.get_stats()
        
        return APIResponse.ok(
            data=stats,
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取死信队列统计失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取死信队列统计失败: {str(e)}")


@router.get("/dlq/messages", summary="获取死信消息列表")
async def get_dlq_messages(
    reason: str = None,
    limit: int = 100,
    request: Request = None,
):
    """
    获取死信消息列表
    
    Args:
        reason: 按原因过滤
        limit: 返回数量限制
    """
    try:
        dlq = get_dead_letter_queue()
        
        if reason:
            from neurova.agent.protocols.message_protocol import DeadLetterReason
            messages = dlq.get_by_reason(DeadLetterReason(reason))
        else:
            messages = dlq.get_pending()
        
        return APIResponse.ok(
            data={
                "messages": [m.to_dict() for m in messages[:limit]],
                "total_count": len(messages),
            },
            message="获取成功",
        )
        
    except Exception as e:
        logger.error(f"获取死信消息失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"获取死信消息失败: {str(e)}")


@router.post("/dlq/messages/{message_id}/retry", summary="重试死信")
async def retry_dlq_message(message_id: str, request: Request = None):
    """
    重试处理死信消息
    
    Args:
        message_id: 消息ID
    """
    try:
        dlq = get_dead_letter_queue()
        
        retry_msg = dlq.retry(message_id)
        if not retry_msg:
            raise APIError.not_found(f"消息不存在或无法重试: {message_id}")
        
        return APIResponse.ok(
            data=retry_msg.to_dict(),
            message="重试成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"重试死信失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"重试死信失败: {str(e)}")


@router.delete("/dlq/messages/{message_id}", summary="丢弃死信")
async def discard_dlq_message(
    message_id: str,
    reason: str = None,
    request: Request = None,
):
    """
    丢弃死信消息
    
    Args:
        message_id: 消息ID
        reason: 丢弃原因
    """
    try:
        dlq = get_dead_letter_queue()
        
        success = dlq.discard(message_id, reason)
        if not success:
            raise APIError.not_found(f"消息不存在: {message_id}")
        
        return APIResponse.ok(
            data={"message_id": message_id, "discarded": True},
            message="丢弃成功",
        )
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"丢弃死信失败: {e}")
        raise APIError(ErrorCodes.INTERNAL_ERROR, f"丢弃死信失败: {str(e)}")
