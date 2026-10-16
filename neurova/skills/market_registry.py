"""
市场技能联邦注册 — 安装后打通 Agent 技能页 + 工具注册表

链路契约（§6-186 把真字节接进咽喉之后）：
- link_market_skill_to_agent:
  ① SkillService(agent_id).install_skill —— 技能页可见；staging 里放的是
     **市场缓存目录的真字节** + 咽喉合成的 manifest.json，所以安装门扫的、
     构件摘要钉的都是将被执行那份，不是空壳；
  ② SkillRegistry.register —— 工具集可见且可调：有映射时注册真实可执行
     Skill（参数直通）；账本 `path` 指的目录含 SKILL.md 时注册 SkillDocSkill
     指令型（execute 返回 SKILL.md 指令体）；两者皆无时注册壳（executable=False，
     可见不可调，如实标注）。
  ③ 咽喉因安全门拒装 ⇒ 不注册可执行体，并把拒因交回调用方（端点据此显式 4xx）。
- unlink_market_skill_from_agent：两处同步移除（卸载一致性）。

运行时**只有一条取径**：账本 `path`。市场缓存目录只是安装期的来源，清掉了不影响
恢复（钉过的那份才是权威）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

#: 映射表里存的是一只**执行体工厂**（零参可调用），不是类名。
#: 旧形态在这里存 `"WebSearchSkillExecutor"` 字符串，构造处另写了一张 `{类名: 类}` 的内联查表——
#: 同一个概念两份表示（教义第 6 条）：加一只映射要改两处，漏第二处时问句说"有映射"、
#: 构造却造不出东西，只留一条 warning 就静默降级成空壳（§6-280 甲收口这一处）。
#: 存工厂同时保住"重型依赖不在模块顶层裸 import"（AGENTS §3）——延迟 import 落在工厂里。
ExecutorFactory = Callable[[], Any]


def _webSearchExecutor() -> Any:
    from neurova.skills.builtin.web_search_executor import WebSearchSkillExecutor

    return WebSearchSkillExecutor()


_BUILTIN_EXECUTOR_MAPPINGS: Dict[str, ExecutorFactory] = {"web-search": _webSearchExecutor}

# 市场技能 id → 真实执行体工厂（参数直通；无映射时尝试 SKILL.md 指令型，两者皆无则注册为壳）
_MARKET_EXECUTORS: Dict[str, ExecutorFactory] = dict(_BUILTIN_EXECUTOR_MAPPINGS)


def hasExecutorMapping(skill_id: str) -> bool:
    """这只 id 有没有**代码里的**执行体映射（`web-search` 那一族）。

    外面要问的是这一句，不是自己去读私有表：读面判"这条可得吗"必须把这一形算进去——
    这类技能盘上本来就没有字节，按落盘判会把真能动的好技能集体误灰（§6-272 的对照格）。
    """
    return str(skill_id or "") in _MARKET_EXECUTORS


def executorMappings() -> Dict[str, ExecutorFactory]:
    """映射表的只读投影——问"在册的是哪些"别直读私有表（改一处就是一份平行事实源）。"""
    return dict(_MARKET_EXECUTORS)


def registerExecutorMapping(skill_id: str, factory: ExecutorFactory) -> None:
    """添一只代码侧执行体映射——**唯一**的添法。

    当场判形状而不是等构造那步静默失败：这张表的值必须是工厂，收下一个类名字符串就是
    把刚收掉的双表示重新长回来。
    """
    if not callable(factory):
        raise TypeError(
            f"执行体映射要的是工厂，收到 {type(factory).__name__}：{factory!r}")
    _MARKET_EXECUTORS[str(skill_id or "")] = factory


def buildMappedExecutable(skill_id: str, description: str = "") -> Optional[Any]:
    """按映射表构造 `ExecutorBackedSkill`；不在册 ⇒ None，在册却造不出 ⇒ 点名后 None。

    只认映射、**不看盘**：盘上那一支（SKILL.md 指令型、构件摘要门）不经这里，
    否则这条腿会顺手绕过安装门钉下的那份对账（§6-280 甲要的是一条咽喉一个口径，不是第二条后门）。
    """
    factory = _MARKET_EXECUTORS.get(skill_id)
    if factory is None:
        return None
    try:
        from neurova.skills.executor import ExecutorBackedSkill

        skill = ExecutorBackedSkill(factory())
    except Exception as e:  # noqa: BLE001 — 造不出执行体要如实降级，但不许无声
        logger.warning("mapped executor %s could not be built: %s", skill_id, e)
        return None
    skill.name = skill_id
    skill.description = description or skill.description
    return skill


#: 安装期不进账本的运行产物（缓存目录里可能有上一次跑出来的字节）
_STAGING_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".incoming_*")


def _default_market_skills_dir() -> Path:
    """市场安装根目录（与 MarketImporter 单例一致；异常时回退 data/skills）

    只服务安装期的**来源目录**——运行时取径已经收在账本 `path` 一处。
    """
    try:
        from neurova.skills.market_importer import get_market_importer

        return get_market_importer()._skills_dir
    except Exception:  # noqa: BLE001
        return get_data_root() / "skills"


def _marketSourceDir(skill_id: str, market_skills_dir: Any = None) -> Optional[Path]:
    """安装期真字节的来源目录（不存在则 None，staging 退回只挂 manifest）。"""
    try:
        base = Path(market_skills_dir) if market_skills_dir else _default_market_skills_dir()
        source = base / skill_id
        return source if source.is_dir() else None
    except Exception as e:  # noqa: BLE001 — 来源目录取不到不阻断，退化为无真字节
        logger.warning("market source dir for %s unresolved: %s", skill_id, e)
        return None


def _build_executable_skill(skill_id: str, description: str, installed_dir: Any = None) -> Optional[Any]:
    """按优先级构造可执行 Skill：市场映射执行体 → SKILL.md 指令型 → None。

    1. MARKET_EXECUTORS 映射（如 web-search）：ExecutorBackedSkill 真实执行体；
    2. 账本 `path` 指的目录含 SKILL.md（远端市场技能）：SkillDocSkill 指令型——
       execute 返回 SKILL.md 指令体（Agent Skills 标准语义），不自动执行下载脚本。
       这里只认传入的那一份目录，不再回看市场缓存：门扫过、摘要钉过的就是它。

    执行体统一经 skills.executor.ExecutorBackedSkill 桥接为 SkillRegistry
    可注册的异步 Skill（线程池执行同步 executor, 参数直通）。
    """
    # 映射那一支只经 `buildMappedExecutable` 一处取数（§6-280 甲收口：这里原先自己又查了
    # 一张 `{类名: 类}` 内联表，于是"加一只映射"要改两处；把表改成 id→工厂后漏改这一处，
    # 拿到的是函数对象、查表必空 ⇒ 静默降级成裸壳注册，面板与工具面都画成可用却动不了）。
    mapped = buildMappedExecutable(skill_id, description)
    if mapped is not None:
        return mapped

    # SKILL.md 指令型（远端市场技能的可执行映射）
    if not installed_dir:
        return None
    try:
        skill_dir = Path(installed_dir)
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
    human_approved: bool = False,
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
        human_approved=human_approved,
    )


def _writeAgentManifestOutcome(
    service: Any,
    skill_id: str,
    name: str,
    description: str,
    version: str,
    source: str = "marketplace",
    extra_config: Optional[dict] = None,
    human_approved: bool = False,
    source_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """staging 挂**真字节** + 咽喉合成的 manifest.json，走 install_skill 公开 API。

    返回 {"ok": bool, "refused": bool, "error": str}：`refused` 只在安装门拦下时为真，
    调用方据此把拒装如实报出去（不许回"安装成功"）。

    `source_dir` 是真字节的来处（市场缓存目录）。缺了它安装就退回旧形态——门扫空壳、
    摘要钉空壳，所以市场链路必须递；合成/自主分装类技能本就没有外部字节，递 None 是对的。
    """
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
            if source_dir is not None:
                shutil.copytree(str(source_dir), str(stage),
                                ignore=_STAGING_IGNORED, dirs_exist_ok=True)
            # 咽喉合成的这张赢（包自带的 manifest.json 不获 id/name/version/source 的定义权，
            # 否则同一身份有两份账）。
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = service.install_skill(
                str(stage), skill_id=skill_id, human_approved=human_approved
            )
            refused = bool(isinstance(result, dict) and result.get("findings"))
            ok = bool(result and result.get("success", True)) and service.get_skill_info(skill_id) is not None
            return {
                "ok": ok,
                "refused": refused,
                "error": str((result or {}).get("error") or "") or None,
            }
    except Exception as e:  # noqa: BLE001 — 技能页可见性失败不阻断安装主链路
        logger.error("market skill %s -> agent manifest failed: %s", skill_id, e)
        return {"ok": False, "refused": False, "error": str(e)}


def _write_agent_manifest(
    service: Any,
    skill_id: str,
    name: str,
    description: str,
    version: str,
    source: str = "marketplace",
    extra_config: Optional[dict] = None,
    human_approved: bool = False,
) -> bool:
    return _writeAgentManifestOutcome(
        service, skill_id, name, description, version,
        source=source, extra_config=extra_config, human_approved=human_approved,
    )["ok"]


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

    market_skills_dir: 市场安装根目录，**只作安装期的真字节来源**（staging 从这里
    取包体，之后一律经账本 `path` 读）；None 时用 MarketImporter 单例目录。
    """
    outcome = _writeAgentManifestOutcome(
        service, skill_id, name, description, version,
        source_dir=_marketSourceDir(skill_id, market_skills_dir),
    )
    if not outcome["ok"]:
        # 没过门 / 没落账 ⇒ 一个可执行体都不注册：给被拒的字节开工具面，等于
        # 让门白扫一次。拒因原样交回调用方（端点显式 4xx 用）。
        logger.warning(
            "market skill %s not linked: refused=%s reason=%s",
            skill_id, outcome["refused"], outcome["error"],
        )
        return {
            "registered": False,
            "registry_count": 0,
            "manifest_ok": False,
            "install_refused": bool(outcome["refused"]),
            "reason": outcome["error"],
        }

    info = service.get_skill_info(skill_id) or {}
    installedDir = str(info.get("path") or "")
    target_registries = [registry] + list(extra_registries or [])
    registered = 0
    for reg in target_registries:
        if reg is None:
            continue
        executable = _build_executable_skill(skill_id, description, installedDir)
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
        skill_id, outcome["ok"], registered, len(target_registries),
    )
    return {
        "registered": registered > 0,
        "registry_count": registered,
        "manifest_ok": bool(outcome["ok"]),
        "install_refused": False,
        "reason": None,
    }


def restore_market_skills_from_service(service: Any, registry: Any) -> int:
    """Agent 初始化时从 SkillService manifest 恢复持久化技能（重启后仍可感知）。

    覆盖四类来源（manifest.source 区分）：
    - marketplace: 市场安装，经 MarketImporter/联邦注册；账本 `path` 指的目录含
      SKILL.md 时恢复为 SkillDocSkill 指令型可执行（市场缓存清掉也照恢复——
      权威在钉过的那份里）；
    - synthesized: agent 自主分装（NL 合成/create_skill），config.tool_sequence
      恢复为可执行 ToolSequenceSkill——注册表须先 set_tool_router 注入路由器。
    - agent / auto: agent 显式保存 / pattern 封装与 genetic 进化产物
      （register_auto_skill 写入的 source），同样按 tool_sequence 恢复——
      白名单漏 auto 曾导致重启后自动技能"前端可见、registry 不可见"，
      且 has_skill 落空使下一代遗传重复合成。
    """
    restored = 0
    try:
        for entry in service.list_skills():
            skill_id = entry.get("id") or ""
            if not skill_id:
                continue
            info = service.get_skill_info(skill_id) or {}
            source = (info.get("manifest") or {}).get("source") or info.get("source")
            if source not in ("marketplace", "synthesized", "agent", "auto"):
                continue
            if info.get("available") is False:
                # 「在册」不等于「可得」：构件缺失的条目**不进执行表**，也不再兜底注册一个
                # `status=ACTIVE` 的裸基类——那等于给 LLM 一个必然失败的工具，而面板把它画成可用。
                # 读面仍看得见这条（`list_skills`/`get_skill_info` 照旧返回，带 unavailableReason），
                # 用户据此重装或撤条目；这里关的是"能被调用"这一面（§6-272，用户裁甲）。
                logger.warning("restore 跳过 %s：%s", skill_id,
                               info.get("unavailableReason") or "构件缺失")
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
                    executable = _build_executable_skill(
                        skill_id, entry.get("description", ""), info.get("path") or "")
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


def restore_library_skills_for_turn(registry: Any, view: Any) -> int:
    """需求 2 执行面桥（Wave V）：轮级视图在场、registry 缺席的**用户库/公共库**
    副本物化为可执行体（ToolSequenceSkill），使跨库可见技能真正可调用——
    修复"可见但不可执行"断点。纪律：
    - 仅物化 config.tool_sequence 非空条目（元目类目录条目留在发现面，
      与 marketplace 未安装条目同语义，不造空壳可执行体）；
    - agent 层条目与 registry 同名先到（内置/启动恢复）一律跳过——
      幂等，重复调用零副作用；
    - 视图缺席/构建失败路径不调用本函数（chat_pipeline 已 try 包裹），
      注册表写失败只 warn 不炸对话。
    """
    restored = 0
    try:
        existing = getattr(registry, "skills", {}) or {}
        from types import SimpleNamespace

        for name, v in (getattr(view, "skills", {}) or {}).items():
            if getattr(v, "pool", "agent") == "agent" or name in existing:
                continue
            cfg = v.config or {}
            ts = cfg.get("tool_sequence")
            if not (isinstance(ts, list) and ts):
                continue
            m = SimpleNamespace(
                id=getattr(v, "skill_id", None) or str(name),
                name=str(name),
                description=getattr(v, "description", "") or "",
                config={**cfg, "source": "library"},
            )
            try:
                if registry.register_skill(m):
                    restored += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("库技能轮级物化失败 %s: %s", name, e)
    except Exception as e:  # noqa: BLE001
        logger.warning("restore_library_skills_for_turn 异常: %s", e)
    if restored:
        logger.info("轮级库技能物化 %d 条（用户库/公共库→执行池）", restored)
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
