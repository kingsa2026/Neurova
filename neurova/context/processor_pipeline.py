"""系统指令处理器管线（P1-4，上下文工程十轴专项·轴1）。

把 orchestrator.build_context Phase 2 的固定 append 序列改成可注册的
处理器管线：每个处理器（SystemSectionSpec）在指定阶段产出一个或多个
命名段；编排器只消费管线装配结果（instructions 进 system 消息序列、
sections 进 recordContextBudget 读数），不再手工拼接。

设计约定：
- 段序 = 阶段号升序，同阶段号按注册序（稳定排序）。默认阶段表：
  1.0 identity（soul/personality/personality_traits/constitution/
  constitution_rules，冻结快照优先、无快照活值兜底）→ 2.0 time →
  3.0 rules → 4.0 workspace_docs → 5.0 skill_catalog → 6.0 self_model。
  插件在两阶段之间注入取中间阶段号（如 2.55 落在 time 与 rules 之间）。
- build(orch, context) 返回 Dict[str, str]：一个或多个命名段；
  空串值/空 dict = 不注入（instructions 只收非空段文本）。
- sections 是**有序命名段台账**（含空串值），键与 recordContextBudget
  的分段消费口径一致，供预算读数单源取用。
- 失败隔离：单处理器抛异常 → 记入 failures（name + 异常类型 + 消息）
  后继续其余处理器；可选段失败不阻断装配，但必须留痕（诚实暴露不静默）。
- 字节一致：defaultSystemPipeline 的段序、跳过条件、文本与改造前
  build_context Phase 2 逐段一致（判据见
  tests/unit/context/test_processor_pipeline.py）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

#: 处理器构建函数签名：build(orch, context) -> {段名: 段文本}
SectionBuild = Callable[[Any, Dict[str, Any]], Dict[str, str]]

__all__ = [
    "SystemSectionSpec",
    "SystemAssemblyFailure",
    "SystemAssemblyResult",
    "SystemInstructionPipeline",
    "defaultSystemPipeline",
]


@dataclass
class SystemSectionSpec:
    """单个系统段处理器。

    Attributes:
        name: 处理器名（failures 留痕与日志定位用）。
        stage: 阶段号，升序装配；同号按注册序稳定排序。
        build: build(orch, context) -> Dict[str, str]；空串值/空 dict =
            不注入。异常由管线捕获记入 failures，不阻断其余处理器。
    """

    name: str
    stage: float
    build: SectionBuild


@dataclass
class SystemAssemblyFailure:
    """单个处理器的装配失败留痕（诚实暴露，不静默吞掉）。"""

    name: str
    error_type: str
    message: str = ""

    def __str__(self) -> str:  # 供日志一行打印
        return f"{self.name}: {self.error_type}: {self.message}"


@dataclass
class SystemAssemblyResult:
    """一次系统指令装配的结果。

    Attributes:
        sections: 有序命名段台账（含空串值）；键与 recordContextBudget
            的分段消费口径一致。
        instructions: 非空段文本按装配序排列——直接作为 system 消息序列。
        failures: 失败处理器清单（name + 异常类型）；空 = 全部成功。
    """

    sections: Dict[str, str] = field(default_factory=dict)
    instructions: List[str] = field(default_factory=list)
    failures: List[SystemAssemblyFailure] = field(default_factory=list)


class SystemInstructionPipeline:
    """系统段处理器注册表 + 装配器。"""

    def __init__(self) -> None:
        self._specs: List[SystemSectionSpec] = []

    def register(self, spec: SystemSectionSpec) -> None:
        """注册一个处理器；装配序 = (stage, 注册序) 稳定排序。"""
        self._specs.append(spec)

    def _sortedSpecs(self) -> List[SystemSectionSpec]:
        """阶段号升序，同阶段号保持注册序（enumerate 序号作次级键）。"""
        return [
            spec
            for _, spec in sorted(
                enumerate(self._specs), key=lambda pair: (pair[1].stage, pair[0])
            )
        ]

    def assemble(
        self, orch: Any, context: Optional[Dict[str, Any]] = None
    ) -> SystemAssemblyResult:
        """按阶段序执行全部处理器，产出命名段台账与 system 指令序列。

        单处理器异常被捕获并记入 failures 后继续其余处理器（失败隔离）；
        段文本只接受 str（判据收严：测试桩/异常实现可能返回 MagicMock 等
        真值对象，非 str 一律记失败不注入）。
        """
        assembly_context: Dict[str, Any] = dict(context) if context else {}
        sections: Dict[str, str] = {}
        instructions: List[str] = []
        failures: List[SystemAssemblyFailure] = []
        for spec in self._sortedSpecs():
            try:
                produced = spec.build(orch, assembly_context)
            except Exception as exc:  # noqa: BLE001 - 单处理器失败不阻断装配，留痕
                failures.append(
                    SystemAssemblyFailure(
                        name=spec.name,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue
            if not produced:
                continue
            for key, value in produced.items():
                if not isinstance(value, str):
                    failures.append(
                        SystemAssemblyFailure(
                            name=spec.name,
                            error_type="TypeError",
                            message=f"段 {key!r} 返回非字符串: {type(value).__name__}",
                        )
                    )
                    continue
                sections[key] = value
                if value:
                    instructions.append(value)
        return SystemAssemblyResult(
            sections=sections, instructions=instructions, failures=failures
        )


# ════════════════════════════════════════════════════════════════
# 默认处理器（与改造前 build_context Phase 2 逐段字节一致）
# ════════════════════════════════════════════════════════════════


def _buildIdentitySections(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """身份五段：soul/personality/personality_traits/constitution/
    constitution_rules。P2-11：优先消费会话身份快照（ChatPipeline 每轮
    经 session_snapshot 冻结，同会话内身份写入不改变当前 prompt）；未装配
    快照（或脏快照缺 soul）时活值兜底（零行为变化）。"""
    frozen = getattr(orch._agent, "_frozen_identity_snapshot", None)
    if isinstance(frozen, dict) and frozen.get("soul"):
        return {
            "soul": frozen["soul"],
            "personality": frozen.get("personality") or "",
            "personality_traits": str(frozen.get("personality_traits") or ""),
            "constitution": frozen.get("constitution") or "",
            "constitution_rules": str(frozen.get("constitution_rules") or ""),
        }
    return {
        "soul": orch.soul or "",
        "personality": orch.personality or "",
        "personality_traits": orch._livePersonalityTraitsText(),
        "constitution": orch.config.constitution or "",
        "constitution_rules": orch._liveConstitutionRulesText(),
    }


def _buildTimeSection(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """Bug T-1：注入当前时间上下文（避免 LLM 误用训练截止日期）。"""
    return {"time": orch._build_current_time_section()}


def _buildRulesSection(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """批次 C：恒定规则段（工具使用方法论/环境块/记忆写入规则等）——
    除日期外全部恒定，system 会话内字节稳定；动态内容走 envelope。"""
    from neurova.context.rules_sections import build_all_sections

    return {
        "rules": build_all_sections(
            workspace_path=str(getattr(orch.config, "workspace_path", "") or "")
        )
    }


def _buildWorkspaceDocsSection(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """P0-1：工作区 AGENTS.md 文档树段；无文档返回空串（零注入）。"""
    return {"workspace_docs": orch._workspace_docs_section() or ""}


def _buildSkillCatalogSection(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """P0-3：可用技能目录段；默认关/无技能返回空串（零注入）。"""
    return {"skill_catalog": orch._skill_catalog_section() or ""}


def _buildSelfModelSection(orch: Any, context: Dict[str, Any]) -> Dict[str, str]:
    """自我模型读取面：实测能力画像 + 声明能力 + 知识领域 + 最近任务自评。

    原始账单源在 tool_memory，此处只透传 usage_history 快照；无数据返回
    空 dict = 零注入零成本。运行期动态段，不随身份快照冻结。判据收严：
    只接受**非空字符串**返回值——测试桩/异常实现可能返回 MagicMock 等真值
    对象。异常不在此吞：交由管线 failures 留痕（缺席不阻断装配）。
    """
    mm = getattr(orch._agent, "memory_manager", None)
    if mm is None or not hasattr(mm, "selfModelPromptSection"):
        return {}
    tm = getattr(orch._agent, "tool_memory", None)
    usage = getattr(tm, "usage_history", None) if tm is not None else None
    section = mm.selfModelPromptSection(usage_records=usage)
    if not isinstance(section, str):
        return {}
    return {"self_model": section.strip()}


def defaultSystemPipeline() -> SystemInstructionPipeline:
    """按现 Phase 2 顺序注册默认处理器的管线工厂。

    每次调用返回独立实例（无共享状态）；编排器每轮 build_context 调用
    一次。插件注入：对返回实例 register 一条 SystemSectionSpec 即可，
    无需改编排器代码。
    """
    pipeline = SystemInstructionPipeline()
    pipeline.register(SystemSectionSpec(name="identity", stage=1.0, build=_buildIdentitySections))
    pipeline.register(SystemSectionSpec(name="time", stage=2.0, build=_buildTimeSection))
    pipeline.register(SystemSectionSpec(name="rules", stage=3.0, build=_buildRulesSection))
    pipeline.register(
        SystemSectionSpec(name="workspace_docs", stage=4.0, build=_buildWorkspaceDocsSection)
    )
    pipeline.register(
        SystemSectionSpec(name="skill_catalog", stage=5.0, build=_buildSkillCatalogSection)
    )
    pipeline.register(
        SystemSectionSpec(name="self_model", stage=6.0, build=_buildSelfModelSection)
    )
    return pipeline
