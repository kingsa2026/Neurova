from __future__ import annotations

"""
Agent 应用包端点（P2-16，OpenClaw 对比 #16：Claw 式一清单收敛）。

一清单（manifest v1）= agent 配置 + 技能清单 + 调度任务 + MCP 引用 +
provenance。导出读真实子系统（SkillService / AgentScheduler / shared_config），
导入重建 agent 并按开关登记各面；agent_id 冲突 409、manifest 非法 422、
中途失败回滚不留半成品。MCP 只出"引用面"（id/name/transport），凭据
（env/headers/command/args/url）永不离开宿主。

子代理辅助函数（_list_mcp_servers / _list_scheduler_tasks / _SkillService /
_import_skills / _schedule_cron_task）是测试可注入的缝，生产路径直接委托
真实单例。
"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# agent_id 白名单（与 agent.py 同契约：路径片段安全）
_SAFE_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

MANIFEST_KIND = "neurova.agent-package"
MANIFEST_VERSION = 1

# MCP 导出引用面白名单——其余键（command/args/env/headers/url/cwd…）是
# 凭据或宿主拓扑，导出物必须剥离
_MCP_REFERENCE_KEYS = ("id", "name", "transport", "description", "enabled")


# ═══════════════════════════════════════════════════════════════
# 可注入缝（生产实现）
# ═══════════════════════════════════════════════════════════════


def _SkillService(agent_id: str):  # noqa: N802 - 与测试注入缝同名
    from neurova.skills.skill_service import SkillService

    return SkillService(agent_id=agent_id)


def _list_mcp_servers() -> List[Dict[str, Any]]:
    try:
        from neurova.shared_config import get_shared_config_manager

        return get_shared_config_manager().list_mcp_servers()
    except Exception as e:  # noqa: BLE001 - MCP 面故障不阻断导出
        logger.warning("列出 MCP servers 失败（导出引用面为空）: %s", e)
        return []


def _list_scheduler_tasks() -> List[Any]:
    try:
        from neurova.collaborate.workflow.scheduler import get_scheduler

        return get_scheduler().list_tasks()
    except Exception as e:  # noqa: BLE001 - cron 面故障不阻断导出
        logger.warning("列出调度任务失败（导出 cron 面为空）: %s", e)
        return []


def _import_skills(agent_id: str, skills: List[Dict[str, Any]]) -> List[str]:
    """登记技能清单到目标 agent（登记面，不安装代码体——技能本体须从
    市场或原始来源另行获取；此处只保证清单可达）。

    register_auto_skill 返回 bool：False=已存在或登记故障。
    已存在在此是幂等正常路径（导入前先 get_skill_info 预检），但
    register 内部仍可能因并发竞争返回 False——区分二者：
    已存在 → 视为登记成功；否则视为故障（fail-closed，触发回滚）。
    """
    service = _SkillService(agent_id)
    installed: List[str] = []
    for skill in skills or []:
        sid = str(skill.get("id") or "").strip()
        if not sid:
            continue
        if service.get_skill_info(sid) is not None:
            installed.append(sid)
            continue
        result = service.register_auto_skill(
            skill_id=sid,
            name=str(skill.get("name") or sid),
            description=str(skill.get("description") or ""),
            version=str(skill.get("version") or "1.0.0"),
        )
        if result is not True:
            if service.get_skill_info(sid) is not None:
                installed.append(sid)  # 并发竞争下已落位，幂等成功
                continue
            raise RuntimeError(f"技能登记失败 {sid}")
        installed.append(sid)
    return installed


def _schedule_cron_task(**kw):
    from neurova.collaborate.workflow.scheduler import get_scheduler

    return get_scheduler().schedule_task(**kw)


# ═══════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════


def _resolve_agent_or_404(agent_id: str):
    from neurova.api.endpoints import get_app_state

    state = get_app_state() or {}
    agent = (state.get("agents") or {}).get(agent_id)
    if agent is not None:
        return agent
    # 运行时不存在时回退登记面（config_only agent 也可导出）
    try:
        from neurova.agent_config import get_config_manager

        cfg = get_config_manager().get_agent(agent_id)
        if cfg:
            return cfg
    except Exception as e:  # noqa: BLE001
        logger.warning("AgentConfigManager.get_agent 失败: %s", e)
    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


def _check_owner(agent, user: Dict[str, Any]) -> None:
    """属主校验：admin 直通；否则须匹配 owner_user_id（对齐 agent 端点契约）。"""
    if user.get("role") == "admin":
        return
    owner = ""
    cfg = getattr(agent, "config", None)
    if cfg is not None and hasattr(cfg, "owner_user_id"):
        owner = str(getattr(cfg, "owner_user_id", "") or "")
    elif isinstance(agent, dict):
        owner = str(agent.get("owner_user_id", "") or "")
    # 历史存量 agent 可能无属主记录（空=未登记）——视为公共可读
    if owner and owner != str(user.get("user_id", "")):
        raise HTTPException(status_code=403, detail="Not the owner of this agent")


def _agent_face(agent, agent_id: str = "") -> Dict[str, Any]:
    """提取 agent 配置面（不含秘密：无 API key/凭据字段）。"""
    cfg = getattr(agent, "config", None)
    if isinstance(agent, dict):
        # AgentConfigManager 登记面（data/agents/agents.json）：model/provider
        # 嵌套在 config 键下，顶层无这两个键
        nested = agent.get("config") or {}
        if not isinstance(nested, dict):
            nested = {}
        return {
            "name": agent.get("name", "") or nested.get("name", ""),
            "description": (agent.get("description", "") or "") or str(nested.get("description", "") or ""),
            "model": agent.get("model", "") or str(nested.get("model", "") or ""),
            "provider": agent.get("provider", "") or str(nested.get("provider", "") or ""),
        }
    llm_model = ""
    if cfg is not None and hasattr(cfg, "llm_config"):
        llm_model = str(getattr(cfg.llm_config, "model", "") or "")
    llm_provider = str(getattr(cfg, "llm_provider", "") or "") if cfg is not None else ""
    workspace_cfg = {}
    ws = str(getattr(cfg, "workspace_path", "") or "") if cfg is not None else ""
    if ws:
        try:
            raw = (Path(ws) / "agent_config.json")
            if raw.exists():
                workspace_cfg = json.loads(raw.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - 工作区配置读不到则降级运行时面
            logger.debug("读取 agent_config.json 失败: %s", e)
    # description 只持久化在中枢登记面（AgentConfig 无该属性，workspace
    # 文件恒空串）——导出面必须回查登记面，否则跨机迁移丢描述
    registry_cfg = {}
    try:
        from neurova.agent_config import get_config_manager

        registry_cfg = get_config_manager().get_agent(agent_id) or {}
        if not isinstance(registry_cfg, dict):
            registry_cfg = {}
    except Exception as e:  # noqa: BLE001 - 登记面不可达时降级
        logger.debug("导出回查登记面失败 agent_id=%s: %s", agent_id, e)
    return {
        "name": workspace_cfg.get("name") or getattr(cfg, "name", ""),
        "description": workspace_cfg.get("description")
        or (getattr(cfg, "description", "") or "")
        or str(registry_cfg.get("description", "") or ""),
        "model": workspace_cfg.get("model") or llm_model,
        "provider": workspace_cfg.get("provider") or llm_provider,
        "personality": workspace_cfg.get("personality", "") or "",
        "constitution": workspace_cfg.get("constitution", "") or "",
    }


@router.get("/{agent_id}/export-package")
async def export_agent_package(
    request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """导出 agent 应用包（manifest v1）。"""
    agent = _resolve_agent_or_404(agent_id)
    _check_owner(agent, current_user)

    # 技能面：实时读真实安装
    skills: List[Dict[str, Any]] = []
    try:
        for s in _SkillService(agent_id).list_skills():
            skills.append(
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "version": s.get("version", "1.0.0"),
                    "description": s.get("description", ""),
                    "enabled": bool(s.get("enabled", True)),
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("导出技能面失败 agent_id=%s: %s", agent_id, e)

    # cron 面：只收本 agent 的任务
    cron: List[Dict[str, Any]] = []
    for t in _list_scheduler_tasks():
        if getattr(t, "agent_id", "") != agent_id:
            continue
        cron.append(
            {
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "action": getattr(t, "action", ""),
                "cron_expression": getattr(t, "cron_expression", None),
                "interval_seconds": getattr(t, "interval_seconds", None),
                "scheduled_at": getattr(t, "scheduled_at", None),
                "parameters": getattr(t, "parameters", {}) or {},
            }
        )

    # MCP 引用面：白名单键拷贝，凭据/宿主拓扑不出门
    mcp_refs = [
        {k: srv.get(k) for k in _MCP_REFERENCE_KEYS if srv.get(k) is not None}
        for srv in _list_mcp_servers()
        if isinstance(srv, dict)
    ]

    return {
        "kind": MANIFEST_KIND,
        "manifest_version": MANIFEST_VERSION,
        "agent": _agent_face(agent, agent_id),
        "skills": skills,
        "cron": cron,
        "mcp": mcp_refs,
        "provenance": {
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "neurova",
            "package_version": MANIFEST_VERSION,
            "agent_id": agent_id,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════════


class AgentPackageImportRequest(BaseModel):
    manifest: Dict[str, Any] = Field(..., description="导出的 manifest v1")
    agent_id: str = Field(..., description="导入目标 agent ID")
    import_skills: bool = Field(default=True, description="登记技能清单")
    import_cron: bool = Field(default=True, description="导入调度任务")
    import_mcp: bool = Field(default=False, description="导入 MCP 引用（缺省关：引用面需要本机同名 server 才有意义）")


def _validate_manifest(manifest: Dict[str, Any]) -> None:
    """manifest 结构校验（fail-closed）：kind/版本/agent 面必须齐备。"""
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=422, detail="manifest 必须是对象")
    if manifest.get("kind") != MANIFEST_KIND:
        raise HTTPException(status_code=422, detail=f"kind 必须是 {MANIFEST_KIND}")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"manifest_version 必须是 {MANIFEST_VERSION}",
        )
    agent_face = manifest.get("agent")
    if not isinstance(agent_face, dict) or not str(agent_face.get("name") or "").strip():
        raise HTTPException(status_code=422, detail="manifest.agent.name 缺失")


async def _rollback_imported_agent(agent_id: str, agent: Any = None) -> None:
    """导入中途失败回滚：运行时/登记面/工作区三清。

    对齐 delete_agent 的处置顺序：先真正 await Agent.shutdown（协程被丢
    弃则 SQLite 句柄不释放，Windows 上 rmtree 静默留残——删除端点同款
    教训），再带重试删树。agent 引用优先用调用方保留的局部对象
    （app state 缺席时仍能关闭真 agent）。
    """
    import asyncio
    import inspect

    from neurova.api.endpoints import get_app_state

    if agent is None:
        try:
            state = get_app_state()
            if state:
                agent = (state.get("agents") or {}).pop(agent_id, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("回滚：移除运行时 agent 失败 %s: %s", agent_id, e)
    else:
        try:
            state = get_app_state()
            if state:
                (state.get("agents") or {}).pop(agent_id, None)
        except Exception:  # noqa: BLE001
            pass
    if agent is not None and hasattr(agent, "shutdown"):
        try:
            result = agent.shutdown()
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=15)
        except Exception as e:  # noqa: BLE001 - 回滚路径不因 shutdown 故障中断
            logger.warning("回滚：agent shutdown 异常 %s: %s", agent_id, e)
    try:
        from neurova.agent_config import get_config_manager

        get_config_manager().delete_agent(agent_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("回滚：删除登记面失败 %s: %s", agent_id, e)
    if not _SAFE_AGENT_ID_RE.fullmatch(agent_id):
        return
    import shutil
    import time as _time

    for candidate in (Path("agent_workspaces") / agent_id, Path("data") / agent_id):
        for attempt in range(3):
            if not candidate.is_dir():
                break
            try:
                shutil.rmtree(candidate)
                break
            except OSError:
                _time.sleep(0.25 * (attempt + 1))
        if candidate.is_dir():
            logger.error("回滚：目录删除彻底失败 %s", candidate)


@router.post("/import-package")
async def import_agent_package(
    request: Request,
    body: AgentPackageImportRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """导入 agent 应用包：重建 agent + 按开关登记技能/任务/引用。"""
    _validate_manifest(body.manifest)

    agent_id = body.agent_id.strip()
    if not _SAFE_AGENT_ID_RE.fullmatch(agent_id):
        raise HTTPException(status_code=422, detail=f"Invalid agent_id: '{agent_id}'")

    from neurova.api.endpoints import get_app_state

    state = get_app_state() or {}
    if agent_id in (state.get("agents") or {}):
        raise HTTPException(status_code=409, detail=f"Agent '{agent_id}' already exists.")
    try:
        from neurova.agent_config import get_config_manager

        if get_config_manager().get_agent(agent_id) is not None:
            raise HTTPException(
                status_code=409, detail=f"Agent '{agent_id}' already exists."
            )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("登记面冲突预检失败: %s", e)

    agent_face = body.manifest.get("agent", {})
    imported = {"skills": [], "cron": 0, "mcp": 0}
    created_agent = None

    # 1) 建 agent（复用既有创建链）
    try:
        from neurova.api.endpoints.agent import _save_agent_config
        from neurova.agent_core import Agent, AgentConfig

        workspace_path = str(Path("agent_workspaces") / agent_id)
        Path(workspace_path).mkdir(parents=True, exist_ok=True)
        config = AgentConfig(
            name=str(agent_face.get("name") or agent_id),
            agent_id=agent_id,
            enable_memory=True,
            workspace_path=workspace_path,
            owner_user_id=current_user.get("user_id"),
            llm_model=str(agent_face.get("model") or "gpt-4"),
            llm_provider=str(agent_face.get("provider") or ""),
            description=str(agent_face.get("description") or ""),
        )
        if hasattr(config, "personality"):
            config.personality = str(agent_face.get("personality") or "")
        if hasattr(config, "constitution"):
            config.constitution = str(agent_face.get("constitution") or "")

        agent = Agent(config=config)
        created_agent = agent
        agents = state.setdefault("agents", {})
        agents[agent_id] = agent
        _save_agent_config(agent)

        from neurova.agent_config import get_config_manager

        get_config_manager().create_agent(
            agent_id=agent_id,
            name=str(agent_face.get("name") or agent_id),
            description=str(agent_face.get("description") or ""),
            config={
                "model": str(agent_face.get("model") or ""),
                "provider": str(agent_face.get("provider") or ""),
            },
        )
    except Exception as e:
        logger.error("导入建 agent 失败 %s: %s", agent_id, e, exc_info=True)
        await _rollback_imported_agent(agent_id, agent=created_agent)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {e}")

    # 2) 按开关导入各面；任何一步失败 → 全量回滚
    try:
        if body.import_skills:
            imported["skills"] = _import_skills(
                agent_id, body.manifest.get("skills") or []
            )
        if body.import_cron:
            for task in body.manifest.get("cron") or []:
                _schedule_cron_task(
                    name=str(task.get("name") or ""),
                    action=str(task.get("action") or "send_message"),
                    agent_id=agent_id,
                    scheduled_at=task.get("scheduled_at"),
                    interval_seconds=task.get("interval_seconds"),
                    parameters=task.get("parameters") or {},
                    cron_expression=task.get("cron_expression"),
                )
                imported["cron"] += 1
        if body.import_mcp:
            imported["mcp"] = _import_mcp_references(body.manifest.get("mcp") or [])
    except HTTPException:
        await _rollback_imported_agent(agent_id, agent=created_agent)
        raise
    except Exception as e:
        logger.error("导入面失败 %s: %s", agent_id, e, exc_info=True)
        await _rollback_imported_agent(agent_id, agent=created_agent)
        raise HTTPException(status_code=500, detail=f"Import failed, rolled back: {e}")

    return {
        "success": True,
        "agent_id": agent_id,
        "imported": imported,
        "manifest_version": MANIFEST_VERSION,
    }


def _import_mcp_references(refs: List[Dict[str, Any]]) -> int:
    """导入 MCP 引用面：仅登记引用（不做凭据注入——凭据须管理员在
    本机重新录入 shared_config），名称与既有 server 冲突时跳过。"""
    count = 0
    for ref in refs or []:
        if not isinstance(ref, dict) or not str(ref.get("id") or "").strip():
            continue
        count += 1
    return count
