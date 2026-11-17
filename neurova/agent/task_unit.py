# -*- coding: utf-8 -*-
"""结构化任务单元（P1-1，评测报告 G-2）。

蜂群派生的任务从自由文本升级为可挂接验收（P1-2）/评审（P1-3）/依赖门（P1-4）的
结构化单元。设计取舍：
- 纯 dataclass + 手写解析，不引 pydantic——与 swarm 既有轻量风格一致；
- 字段 camelCase（仓规），解析容忍 snake_case 别名（LLM 工具入参常混用）；
- 自由文本 task 永远保留：task_unit 是增强不是替代，member 的实际提示词由
  renderTaskUnitPrompt 把两者拼装——原始任务描述进正文，结构化字段进任务书分节。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.agent.context_firewall import fenceUntrustedPayload

REVIEW_MODES = ("none", "supervisor")


@dataclass
class TaskUnit:
    """任务单元三元组的本仓落地：目标 + 预期产物/验收条件 + 依赖/评审。"""

    goal: str
    expectedResult: str = ""
    acceptanceCriteria: List[str] = field(default_factory=list)
    requiredInputs: List[str] = field(default_factory=list)
    artifactOwnership: str = ""
    reviewMode: str = "none"
    dependencies: List[str] = field(default_factory=list)
    # P3-4（评测报告 G-13）：不可信外部内容槽位——外部检索/用户材料类内容走这里，
    # 渲染时被隔离进显式不可信段（fenceUntrustedPayload），与可信任务指令物理分槽。
    untrustedPayload: str = ""

    def toDict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "expectedResult": self.expectedResult,
            "acceptanceCriteria": list(self.acceptanceCriteria),
            "requiredInputs": list(self.requiredInputs),
            "artifactOwnership": self.artifactOwnership,
            "reviewMode": self.reviewMode,
            "dependencies": list(self.dependencies),
            "untrustedPayload": self.untrustedPayload,
        }


def _pick(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _asStringList(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def parseTaskUnit(data: Optional[Any]) -> Optional[TaskUnit]:
    """dict → TaskUnit；None/空 dict → None；形状非法抛 ValueError（spawn 侧转结构化拒绝）。"""
    if data is None:
        return None
    if isinstance(data, TaskUnit):
        return data
    if not isinstance(data, dict):
        raise ValueError("task_unit 必须是对象（{goal, expectedResult, acceptanceCriteria, ...}）")
    if not data:
        return None

    goal = _pick(data, "goal", "Goal")
    if goal is None or not str(goal).strip():
        raise ValueError("task_unit.goal 必填（与 task 描述一致或更精炼）")

    reviewMode = str(_pick(data, "reviewMode", "review_mode") or "none").strip().lower()
    if reviewMode not in REVIEW_MODES:
        raise ValueError(f"task_unit.reviewMode 仅支持 {REVIEW_MODES}，收到 {reviewMode!r}")

    return TaskUnit(
        goal=str(goal).strip(),
        expectedResult=str(_pick(data, "expectedResult", "expected_result") or "").strip(),
        acceptanceCriteria=_asStringList(_pick(data, "acceptanceCriteria", "acceptance_criteria")),
        requiredInputs=_asStringList(_pick(data, "requiredInputs", "required_inputs")),
        artifactOwnership=str(_pick(data, "artifactOwnership", "artifact_ownership") or "").strip(),
        reviewMode=reviewMode,
        dependencies=_asStringList(_pick(data, "dependencies")),
        untrustedPayload=str(_pick(data, "untrustedPayload", "untrusted_payload",
                                   "externalData", "external_data") or "").strip(),
    )


def renderTaskUnitPrompt(task: str, unitData: Optional[Any]) -> str:
    """member 实际收到的提示词：原始任务描述 + 结构化任务书分节（无单元时原样返回）。"""
    try:
        unit = parseTaskUnit(unitData)
    except ValueError:
        unit = None
    if unit is None:
        return task

    lines: List[str] = [task, "", "【任务书（结构化）】", f"- 目标：{unit.goal}"]
    if unit.expectedResult:
        lines.append(f"- 预期产物：{unit.expectedResult}")
    if unit.acceptanceCriteria:
        lines.append("- 验收条件（逐条核对，未满足将被验收门打回）：")
        for idx, item in enumerate(unit.acceptanceCriteria, 1):
            lines.append(f"  {idx}. {item}")
    if unit.requiredInputs:
        lines.append("- 所需输入：" + "；".join(unit.requiredInputs))
    if unit.artifactOwnership:
        lines.append(f"- 产物归属：{unit.artifactOwnership}")
    if unit.reviewMode == "supervisor":
        lines.append("- 评审方式：提交后由发起方按上述验收条件评审，不通过将带批注退回重做")
    if unit.untrustedPayload:
        # P3-4：不可信内容进显式隔离槽位段（警示 + BEGIN/END 标记），不与任务指令混排
        lines.append("")
        lines.append(fenceUntrustedPayload(unit.untrustedPayload))
    return "\n".join(lines)
