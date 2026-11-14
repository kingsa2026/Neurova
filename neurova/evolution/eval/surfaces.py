"""V3 可进化面 schema —— 「填空式结构表示」的本仓工程化（2026-11-14）。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V3。
论文（arXiv 2610.01766）Cloze-Structured Harness Representation：阶段接口固定、
每份提案只编辑一个被允许的「面」、候选先过接口检查。本仓此前「哪些面可进化」
是隐式的——尺寸预算映射在 mutator/runner/constraints 三处各抄一份（runner 那份
已漂移：丢了 param_description 分支），可执行套件适用面又单列一份清单。

本模块是可进化面的**单一事实源**：每个面有名称/类型/标注/预算键（预算数值
单源在 EvolutionConfig，本模块只持字段名）/可执行套件适用性/接口约束
（写回位置与消费方）。变异器、约束闸、判分上限、提案记录都从这把尺取。

首期四个面全部是文本面（kind="text"）；策略/代码面接入时在此登记并带各自
的接口检查——「接口固定、内部开放」的扩面安全边界。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class EvolvableSurface:
    """一个可进化面的接口契约。"""

    name: str              # 面名（= artifact_type 词值，单一出处）
    kind: str              # 面类型：首期全部 "text"（文本面）
    label: str             # 中文标注（提案/审计面显示用）
    size_budget_key: str   # EvolutionConfig 上的尺寸预算字段名（预算单源在 config）
    exec_suite_applies: bool  # 是否合成可执行测试套件（HN2/HC2 覆盖面）
    writeback: str         # 接口约束：批准后写回到哪里
    consumer: str          # 接口约束：该面被谁消费（接口固定的另一侧）


_SURFACES = (
    EvolvableSurface(
        name="skill", kind="text", label="技能正文",
        size_budget_key="max_skill_size", exec_suite_applies=True,
        writeback="技能 manifest.config.context_template（人工批准后写回）",
        consumer="聊天管线技能注入与执行器指令面"),
    EvolvableSurface(
        name="template", kind="text", label="提示模板",
        size_budget_key="max_skill_size", exec_suite_applies=True,
        writeback="技能 manifest.config.context_template（人工批准后写回）",
        consumer="聊天管线技能注入与执行器指令面"),
    EvolvableSurface(
        name="tool_description", kind="text", label="工具描述",
        size_budget_key="max_tool_desc_size", exec_suite_applies=True,
        writeback="工具登记项的 description 字段（人工批准后写回）",
        consumer="模型工具选择面（工具清单注入）"),
    EvolvableSurface(
        name="param_description", kind="text", label="参数描述",
        size_budget_key="max_param_desc_size", exec_suite_applies=False,
        writeback="工具参数 schema 的描述字段（人工批准后写回）",
        consumer="模型工具参数填充面"),
)

SURFACES: Dict[str, EvolvableSurface] = {s.name: s for s in _SURFACES}


def hasSurface(artifact_type: str) -> bool:
    return str(artifact_type or "") in SURFACES


def surfaceFor(artifact_type: str) -> EvolvableSurface:
    """按名取面；未知面 KeyError（调用方应先用 hasSurface 或走回退预算）。"""
    return SURFACES[str(artifact_type or "")]


def sizeBudgetFor(artifact_type: str, config: Any) -> int:
    """面的尺寸预算（单源：EvolutionConfig 的对应字段）。

    未知面回退 max_skill_size——与旧 else 分支逐字一致（不因改 schema 漂移）。
    """
    surface = SURFACES.get(str(artifact_type or ""))
    key = surface.size_budget_key if surface is not None else "max_skill_size"
    return int(getattr(config, key))


def surfaceReadout(artifact_type: str, config: Any) -> Dict[str, Any]:
    """提案面的「按面记录」读数：名称/标注/类型/生效预算。未知面如实标注。"""
    name = str(artifact_type or "")
    surface = SURFACES.get(name)
    return {
        "name": name,
        "label": surface.label if surface is not None else "",
        "kind": surface.kind if surface is not None else "unknown",
        "max_size": sizeBudgetFor(name, config),
    }


def execSuiteArtifactTypes() -> tuple:
    """可执行测试套件覆盖面（HN2/HC2）——由 schema 派生，不再各写一份清单。"""
    return tuple(s.name for s in _SURFACES if s.exec_suite_applies)
