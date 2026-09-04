"""
市场技能联邦注册 — 安装后打通 Agent 技能页 + 工具注册表

根因链（详见 tests/unit/skills/test_market_registry.py）：
- MarketImporter.import_skill 只写市场目录模拟 meta，Agent 技能页
  （SkillService -> data/agents/{id}/skills/manifest.json）感知不到；
- agent 工具集（SkillRegistry）未注册 → LLM 看不到也调不动。

链路契约：
- link_market_skill_to_agent:
  ① SkillService(agent_id).install_skill —— 技能页可见；
  ② SkillRegistry.register —— 工具集可见且可调：有映射时注册真实可执行
     Skill（参数直通）；安装目录含 SKILL.md 时注册 SkillDocSkill 指令型
     （execute 返回 SKILL.md 指令体）；两者皆无时注册壳（executable=False，
     可见不可调，如实标注）。
- unlink_market_skill_from_agent：两处同步移除（卸载一致性）。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 市场技能 id → 真实执行体工厂（参数直通；无映射时尝试 SKILL.md 指令型，
# 两者皆无则注册为壳）
_MARKET_EXECUTORS: Dict[str, str] = {
    "web-search": "WebSearchSkillExecutor",
}


def _default_market_skills_dir() -> Path:
    """市场安装根目录（与 MarketImporter 单例一致；异常时回退 data/skills）"""
    try:
        from neurova.skills.market_importer import get_market_importer

        return get_market_importer()._skills_dir
    except Exception:  # noqa: BLE001
        return Path("data/skills")


def _build_executable_skill(skill_id: str, description: str, market_skills_dir: Any = None) -> Optional[Any]:
    """按优先级构造可执行 Skill：市场映射执行体 → SKILL.md 指令型 → None。

    1. MARKET_EXECUTORS 映射（如 web-search）：ExecutorBackedSkill 真实执行体；
    2. 安装目录含 SKILL.md（远端市场技能）：SkillDocSkill 指令型——execute
       返回 SKILL.md 指令体（Agent Skills 标准语义），不自动执行下载脚本。

    执行体统一经 skills.executor.ExecutorBackedSkill 桥接为 SkillRegistry
    可注册的异步 Skill（线程池执行同步 executor, 参数直通）。
    """
    exec_name = _MARKET_EXECUTORS.get(skill_id)
    if exec_name:
        try:
            from neurova.skills.executor import ExecutorBackedSkill
            from neurova.skills.builtin.web_search_executor import WebSearchSkillExecutor

            executor_cls = {"WebSearchSkillExecutor": WebSearchSkillExecutor}.get(exec_name)
            if executor_cls is None:
                logger.warning("MARKET_EXECUTORS mapping %s -> %s not found", skill_id, exec_name)
            else:
                skill = ExecutorBackedSkill(executor_cls())
                skill.name = skill_id
                skill.description = description or skill.description
                return skill
        except Exception as e:  # noqa: BLE001 — 注册失败降级，不阻断安装
            logger.warning("build executable skill %s failed: %s", skill_id, e)

    # SKILL.md 指令型（远端市场技能的可执行映射）
    try:
        base = Path(market_skills_dir) if market_skills_dir else _default_market_skills_dir()
        skill_dir = base / skill_id
        if (skill_dir / "SKILL.md").exists():
            from neurova.skills.builtin.skill_doc_executor import SkillMarkdownExecutor

            skill = SkillDocSkill(skill_id, skill_dir)
            skill.name = skill_id
            skill.description = description or skill.description
            return skill
    except Exception as e:  # noqa: BLE001 — 指令型构造失败降级为壳
        logger.warning("build doc skill %s failed: %s", skill_id, e)

    return None


class SkillDocSkill:
    """SKILL.md 指令型技能（SkillRegistry 可注册的鸭子类型，同 ExecutorBackedSkill）。

    _get_parameters 提供通用 task 参数（模型由此知道如何调用）；
    execute 经 SkillMarkdownExecutor 返回指令体。
    """

    def __init__(self, skill_id: str, skill_dir: Any, description: str = ""):
        from neurova.skills.builtin.skill_doc_executor import SkillMarkdownExecutor
        from neurova.skills.executor import ExecutorBackedSkill

        self._bridged = ExecutorBackedSkill(SkillMarkdownExecutor(skill_id, skill_dir, description=description))
        self.name = skill_id
        self.description = description or self._bridged.description
        self.status = "active"

    def add_event_handler(self, handler) -> None:
        self._bridged.add_event_handler(handler)

    def get_info(self):
        return self._bridged.get_info()

    def _get_parameters(self) -> Dict[str, Any]:
        """通用调用契约：task 承载任务/问题（指令体据此注入执行）。"""
        return {
            "task": {
                "type": "string",
                "required": False,
                "description": "交给该技能处理的任务/问题；技能将返回 SKILL.md 指令体供遵循执行",
            }
        }

    async def execute(self, params: Any = None, context: Any = None):
        return await self._bridged.execute(params, context)


def persist_synthesized_skill(
    skill_id: str,
    name: str,
    description: str,
    version: str,
    tool_sequence: list,
    service: Any,
    permissions: Optional[dict] = None,
) -> bool:
    """agent 自主分装（合成）技能持久化到 agent 技能页 manifest。

    合成技能 config.tool_sequence 一并落盘(source=synthesized), 冷启动时
    restore 按 manifest 恢复为可执行的 ToolSequenceSkill。
    permissions: P0-4 声明式权限（可选）——随 config 落盘，恢复不丢失。
    """
    extra = {"tool_sequence": tool_sequence}
    if permissions is not None:
        extra["permissions"] = permissions
    return _write_agent_manifest(
        service, skill_id, name, description, version,
        source="synthesized",
        extra_config=extra,
    )


def _write_agent_manifest(
    service: Any,
    skill_id: str,
    name: str,
    description: str,
    version: str,
    source: str = "marketplace",
    extra_config: Optional[dict] = None,
) -> bool:
    """以 staging 目录挂 manifest.json，走 SkillService.install_skill 公开 API"""
    manifest = {
        "id": skill_id,
        "name": name,
        "version": version or "1.0.0",
        "description": description,
        "enabled": True,
        "source": source,
    }
    if extra_config:
        manifest["config"] = extra_config
    try:
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td) / skill_id
            stage.mkdir(parents=True, exist_ok=True)
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = service.install_skill(str(stage), skill_id=skill_id)
            return bool(result and result.get("success", True)) and service.get_skill_info(skill_id) is not None
    except Exception as e:  # noqa: BLE001 — 技能页可见性失败不阻断安装主链路
        logger.error("market skill %s -> agent manifest failed: %s", skill_id, e)
        return False


def link_market_skill_to_agent(
    skill_id: str,
    name: str,
    description: str,
    version: str,
    service: Any,
    registry: Any,
    extra_registries: Optional[list] = None,
    market_skills_dir: Any = None,
) -> Dict[str, Any]:
    """市场安装成功后的联邦注册：技能页（manifest）+ 工具注册表（可执行）

    extra_registries: 运行中 Agent 的 _skill_registry 实例列表——Agent 各自
    持有独立注册表（agent_core.init_tools 用 create_default_skills 新建，
    非全局单例），安装时需注入每个运行实例才能立即被 LLM 工具集感知。

    market_skills_dir: 市场安装根目录（SKILL.md 指令型技能探测用）；
    None 时用 MarketImporter 单例目录。
    """
    manifest_ok = _write_agent_manifest(service, skill_id, name, description, version)
    target_registries = [registry] + list(extra_registries or [])
    registered = 0
    for reg in target_registries:
        if reg is None:
            continue
        executable = _build_executable_skill(skill_id, description, market_skills_dir)
        if executable is not None:
            try:
                # 与 create_default_skills 的内置技能一致: registry.register 直接
                # 接受 ExecutorBackedSkill(鸭子类型 name/add_event_handler/execute);
                # register_skill(manifest) 兼容入口会把非 Skill 实例重包成空壳, 勿用。
                reg.register(executable)
                registered += 1
                continue
            except Exception as e:  # noqa: BLE001 — 注册失败降级为壳，不阻断安装
                logger.warning("market skill %s register failed: %s", skill_id, e)
        # 壳：技能页/工具列表可见，但调用将报"未实现" —— 如实标注，不伪造执行
        from neurova.skill_system import Skill

        try:
            reg.register(Skill(skill_id, description))
            registered += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("market skill %s shell register failed: %s", skill_id, e)
    logger.info(
        "market skill %s linked: manifest=%s registries=%s/%s",
        skill_id, manifest_ok, registered, len(target_registries),
    )
    return {
        "registered": registered > 0,
        "registry_count": registered,
        "manifest_ok": bool(manifest_ok),
    }


def restore_market_skills_from_service(service: Any, registry: Any, market_skills_dir: Any = None) -> int:
    """Agent 初始化时从 SkillService manifest 恢复持久化技能（重启后仍可感知）。

    覆盖三类来源（manifest.source 区分）：
    - marketplace: 市场安装，经 MarketImporter/联邦注册；安装目录含 SKILL.md
      时恢复为 SkillDocSkill 指令型可执行；
    - synthesized: agent 自主分装（NL 合成/create_skill），config.tool_sequence
      恢复为可执行 ToolSequenceSkill——注册表须先 set_tool_router 注入路由器。
    """
    restored = 0
    try:
        for entry in service.list_skills():
            skill_id = entry.get("id") or ""
            if not skill_id:
                continue
            info = service.get_skill_info(skill_id) or {}
            source = (info.get("manifest") or {}).get("source") or info.get("source")
            if source not in ("marketplace", "synthesized", "agent"):
                continue
            manifest = info.get("manifest") or {}
            tool_sequence = (manifest.get("config") or {}).get("tool_sequence")
            try:
                if isinstance(tool_sequence, list) and tool_sequence:
                    # 合成技能: 注册表经 register_skill 构造 ToolSequenceSkill
                    # （需要 registry.tool_router 已注入，否则执行时报无路由器）
                    from types import SimpleNamespace

                    _config = {"tool_sequence": tool_sequence, "source": source}
                    # P0-4：声明随 manifest 恢复（无声明=存量语义不裁决）
                    _perm = (manifest.get("config") or {}).get("permissions")
                    if _perm is not None:
                        _config["permissions"] = _perm

                    m = SimpleNamespace(
                        id=skill_id,
                        name=str(entry.get("name") or entry.get("id") or skill_id),
                        description=entry.get("description", ""),
                        config=_config,
                    )
                    registry.register_skill(m)
                else:
                    executable = _build_executable_skill(skill_id, entry.get("description", ""), market_skills_dir)
                    if executable is not None:
                        registry.register(executable)
                    else:
                        from neurova.skill_system import Skill

                        registry.register(Skill(skill_id, entry.get("description", "")))
                restored += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("restore persisted skill %s failed: %s", skill_id, e)
    except Exception as e:  # noqa: BLE001
        logger.warning("restore persisted skills from service failed: %s", e)
    if restored:
        logger.info("restored %d persisted skills into agent registry", restored)
    return restored


def unlink_market_skill_from_agent(skill_id: str, service: Any, registry: Any) -> Dict[str, Any]:
    """卸载：注册表移除 + 技能页 manifest 移除"""
    registry.unregister(skill_id)
    removed = False
    try:
        result = service.uninstall_skill(skill_id)
        removed = bool(result and result.get("success", True))
    except Exception as e:  # noqa: BLE001 — 卸载失败不阻断注册表侧清理
        logger.warning("market skill %s agent uninstall failed: %s", skill_id, e)
    return {"unregistered": True, "manifest_removed": removed}
