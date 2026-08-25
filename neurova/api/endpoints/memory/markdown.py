"""
记忆 Markdown 导出/导入接口 — Memory Markdown Endpoint

对齐升级方案 P1-2.2「记忆可解释性」：
- GET  /api/v1/memory/markdown   导出为可读 Markdown（含分类/重要度/时间戳）
- POST /api/v1/memory/markdown   提交（可能被用户编辑过的）Markdown，
  版本化 diff 后仅写回 content 文本层，不触碰向量索引/embedding
"""

from typing import Optional

from fastapi import Depends, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.interfaces.api_standard import success_response
from neurova.security.audit_logger import (
    AuditEventType,
    AuditLogEntry,
    AuditLogger,
    AuditSeverity,
)

from .base import _get_request_id, get_memory_manager, logger, router


class ImportMarkdownRequest(BaseModel):
    """Markdown 导入请求"""

    markdown: str = Field(..., min_length=1, description="导出并可能编辑过的 Markdown")
    strict_version: bool = Field(
        False, description="严格版本校验：基准 updated_at 不一致时记冲突不覆盖"
    )
    agent_id: Optional[str] = Field(None, description="Agent ID")


def _get_exporter(manager):
    from neurova.cognitive_layers.memory_layer.memory_exporter import MemoryExporter

    return MemoryExporter(manager)


@router.get("/markdown", summary="导出记忆为可读 Markdown")
async def export_memory_markdown(
    request: Request,
    category: Optional[str] = Query(None, description="按分类过滤"),
    limit: int = Query(100, ge=1, le=500),
    agent_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user_or_default),
):
    """把当前 Agent 的记忆导出为人类可读的 Markdown，供前端查看/编辑。"""
    _get_request_id(request)
    manager = get_memory_manager(agent_id, user)
    exporter = _get_exporter(manager)
    markdown = exporter.export_markdown(category=category, limit=limit)

    return success_response(
        data={"markdown": markdown},
        message="导出成功",
        request_id=_get_request_id(request),
    )


@router.post("/markdown", summary="提交编辑后的 Markdown 写回记忆文本层")
async def import_memory_markdown(
    request: Request,
    body: ImportMarkdownRequest,
    agent_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user_or_default),
):
    """
    解析编辑后的 Markdown，与当前记忆做版本化 diff，仅应用文本变更。

    - 只更新 content 文本层；importance/category/embedding 等不受影响
    - strict_version=True 时检测并发修改冲突（updated_at 不一致 → conflicts）
    """
    request_id = _get_request_id(request)
    manager = get_memory_manager(agent_id, user)
    exporter = _get_exporter(manager)

    plan = exporter.parse_edited_markdown(body.markdown)
    stats = exporter.apply(plan, manager=manager, strict_version=body.strict_version)

    try:
        AuditLogger().log(
            AuditLogEntry(
                event_type=AuditEventType.DATA_ACCESS,
                severity=AuditSeverity.LOW,
                user_id=str((user or {}).get("user_id", "") or ""),
                action="memory_markdown_import",
                details={
                    "agent_id": agent_id or "default",
                    **stats,
                },
            )
        )
    except Exception:  # noqa: BLE001 - 审计失败不影响主流程
        logger.debug("记忆导入审计写入失败", exc_info=True)

    logger.info("记忆 Markdown 导入完成: %s", stats)
    return success_response(
        data={"stats": stats},
        message=f"已应用 {stats.get('updated', 0)} 处修改",
        request_id=request_id,
    )
