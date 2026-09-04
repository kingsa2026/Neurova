"""workflow_as_tool（P1-3 — Dify `workflow_as_tool` 对标：子流程是一等工具）。

已发布工作流 → agent 可调工具：
- name = ``workflow:{id}`` 命名空间（与 tool:/skill:/mcp: 同风格）
- parameters 直接来自工作流 start 节点的 fields 声明——**天然自带输入
  校验（DAG 定义）**：必填字段缺失在执行前拒绝，不进入引擎
- 执行走 WorkflowExecutor（与画布 run 同一引擎同一隔离语义），
  user_id 透传保证知识库节点属主校验一致

接入面：
- tool_executor._execute_tool_core 对 ``workflow:`` 前缀分派
  （_get_workflow_tool_storage 缺省打开默认 storage，测试可注入）
- builtin_tools 注册面由消费方按需聚合 list_published_workflows_as_tools
  （动态清单，不静态写死——工作流随发布/下线增减）
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_WORKFLOW_TOOL_PREFIX = "workflow:"


def build_workflow_tool_schema(workflow) -> Dict[str, Any]:
    """WorkflowDefinition → OpenAI function schema（parameters 来自 start 节点 fields）"""
    start_config: Dict[str, Any] = {}
    for node in workflow.nodes:
        if node.type == "builtin:start":
            start_config = node.config or {}
            break

    fields = start_config.get("fields") or []
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for f in fields:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        props: Dict[str, Any] = {"type": str(f.get("type") or "string")}
        desc = f.get("label") or f.get("description")
        if desc:
            props["description"] = str(desc)
        properties[str(f["name"])] = props
        if f.get("required"):
            required.append(str(f["name"]))

    description = getattr(workflow, "description", "") or getattr(workflow, "name", "")
    return {
        "name": f"{_WORKFLOW_TOOL_PREFIX}{workflow.id}",
        "description": f"【工作流】{getattr(workflow, 'name', workflow.id)}：{description}".strip("："),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def list_published_workflows_as_tools(storage) -> List[Dict[str, Any]]:
    """已发布工作流 → 工具 schema 清单（草稿不进工具面）"""
    tools: List[Dict[str, Any]] = []
    try:
        workflows = storage.list_workflows()
    except Exception as e:  # noqa: BLE001 — 清单失败返回空，不阻断调用方
        logger.warning("列出已发布工作流失败: %s", e)
        return tools
    for wf in workflows or []:
        status = getattr(getattr(wf, "status", None), "value", wf.status if hasattr(wf, "status") else "")
        if str(status) != "published":
            continue
        tools.append(build_workflow_tool_schema(wf))
    return tools


def _validate_required_inputs(workflow, inputs: Dict[str, Any]) -> Optional[str]:
    """start 节点必填字段校验；缺失返回错误消息（含字段名），齐全返回 None"""
    for node in workflow.nodes:
        if node.type != "builtin:start":
            continue
        missing = [
            str(f.get("name") or f.get("label") or "?")
            for f in (node.config or {}).get("fields") or []
            if isinstance(f, dict) and f.get("required") and not (inputs or {}).get(f.get("name"))
        ]
        if missing:
            return f"缺少必填输入: {', '.join(missing)}（工作流 {workflow.id} 的 start 节点声明）"
        return None
    return None


async def execute_workflow_as_tool(
    workflow_id: str,
    inputs: Dict[str, Any],
    storage=None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """按 id 执行已发布工作流（工具语义信封：{success, result, execution_id?}）"""
    if storage is None:
        storage = _get_workflow_tool_storage()
    try:
        workflow = storage.get_workflow(workflow_id)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"工作流存储不可用: {e}"}
    if workflow is None:
        return {"success": False, "error": f"工作流不存在或未发布: {workflow_id}"}

    status = str(getattr(getattr(workflow, "status", None), "value", getattr(workflow, "status", "")))
    if status != "published":
        return {"success": False, "error": f"工作流未发布（当前 {status}）: {workflow_id}"}

    missing = _validate_required_inputs(workflow, inputs or {})
    if missing:
        return {"success": False, "error": missing}

    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

    try:
        instance = await get_workflow_executor().execute(
            workflow, dict(inputs or {}), user_id=user_id
        )
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"工作流执行异常: {e}"}

    instance_status = str(getattr(getattr(instance, "status", None), "value", ""))
    if instance_status != "completed":
        return {
            "success": False,
            "error": f"工作流执行未完成（{instance_status}）",
            "execution_id": getattr(instance, "id", ""),
        }
    return {
        "success": True,
        "result": getattr(instance, "outputs", None),
        "execution_id": getattr(instance, "id", ""),
    }


def _get_workflow_tool_storage():
    """缺省 storage（api 层同款单例；测试可 patch 本函数注入临时库）"""
    from neurova.api.endpoints.neurflow_api import _get_storage

    return _get_storage()


def split_workflow_tool_name(tool_name: str) -> Optional[str]:
    """``workflow:{id}`` → id；非该命名空间返回 None"""
    if tool_name and tool_name.startswith(_WORKFLOW_TOOL_PREFIX):
        return tool_name[len(_WORKFLOW_TOOL_PREFIX):]
    return None
