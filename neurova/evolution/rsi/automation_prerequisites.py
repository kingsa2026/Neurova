"""四条「无人监督全自动」前置的运行期读数（对照报告 §8）。

§8 末要求这四条**落成晋升判据里的可红断言**，不是文档里的一句话。本模块是那条断言的
唯一真值源：控制器只搬运这里的读数，不重算任何前置事实（与同文件
`_experience_quality_guard` 的"不重算、不另立阈值"同一纪律）。

为什么每条都带探针而不是写四个布尔：写死的旗标会说谎——实装被摘掉之后旗标仍然写着真，
那比"没做实"更糟，因为它让下游有理由继续信任这条判据。
"""

from __future__ import annotations

import asyncio
from dataclasses import fields
from typing import Any, Callable, Dict, Optional

from .gate_verdict import GateVerdict

#: 用于探默认执行器是否还在回显的技能正文（无中文，避免探针自身受码页影响）
PROBE_ECHO_TEXT = "prerequisite-probe-skill-text"


def _fieldNames(cls: Any) -> frozenset:
    return frozenset(f.name for f in fields(cls))


def probeCaseLevelGate() -> bool:
    """前置 1：留出侧有例级读数，且单例退化能被判出来。

    真能判否才叫探针：喂一份"均值涨但一条被撞坏"的读数，必须报出那一条退化。
    """
    from neurova.evolution.eval import runner as evalRunner

    readout = getattr(evalRunner, "_caseRegressionReadout", None)
    if readout is None:
        return False
    try:
        regressions, _unevidenced = readout({
            "a": {"baseline": 0.6, "candidate": 0.1,
                  "baseline_failed": False, "candidate_failed": False},
            "b": {"baseline": 0.4, "candidate": 0.9,
                  "baseline_failed": False, "candidate_failed": False},
        })
    except (KeyError, TypeError):
        return False
    if regressions != ["a"]:
        return False

    configNames = _fieldNames(evalRunner.EvolutionConfig)
    resultNames = _fieldNames(evalRunner.EvolutionRunResult)
    return ("case_regression_allowance" in configNames
            and "holdout_case_scores" in resultNames
            and "caseRegressions" in resultNames)


def probePresentationLedger() -> bool:
    """前置 3：呈现与采纳可分离计数（进了 prompt 不等于被点名）。

    探针直接吃生产归因函数：一条 presented 条目必须只加 presentations，
    冒领 selection 即判不满足——那正是这一格最容易失手的形态。
    """
    from neurova.skills import skill_service as skillService

    compute = getattr(skillService, "compute_skill_funnel_update", None)
    if compute is None:
        return False
    try:
        delta = compute(
            [{"skill_id": "probe", "applied": False, "ok": False, "stage": "presented"}],
            task_completed=True)["probe"]
    except (KeyError, TypeError):
        return False
    return delta.get("presentations") == 1 and delta.get("selections") == 0


def probeFailClosedOnMissingEvidence() -> bool:
    """前置 4：缺证据时不产出可通过分数。

    三件都在才算：判分可用性探针在位、其结论外露成字段、以及 `min_improvement`
    仍大于 0——退回 0 就是当年"judge 不可用时前后同为 0.5、浮点相等使 `<=` 为假
    ⇒ 零增益被放行"的那个洞（`config.py` 的 P0 堵漏注释）。
    """
    from neurova.evolution.eval import runner as evalRunner
    from neurova.evolution.eval.config import EvolutionConfig

    if not hasattr(evalRunner.SkillEvolutionRunner, "_judge_available"):
        return False
    if "judge_available" not in _fieldNames(evalRunner.EvolutionRunResult):
        return False
    try:
        return float(EvolutionConfig().min_improvement) > 0.0
    except (TypeError, ValueError):
        return False


def probeRealTrajectoryExecutor() -> bool:
    """前置 2：判据执行面与线上行为同域（真 agent 轨迹）。

    今天的实情是 runner 的默认执行器把技能正文原样回显 ⇒ 不满足。
    本探针要 await，而控制器是同步入口、可能被 async 端点调起——在已运行的事件循环里
    `asyncio.run` 会直接抛，所以那种情形回落到"未满足"（宁可挡住晋升，不假装量到），
    声明与事实的分歧由 `test_realTrajectoryFlagIsFalseWhileDefaultExecutorStillEchoes`
    在 CI 里钉住。默认执行器被摘掉/换成真跑之后，本探针自然翻真，无需改这里。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return False

    from neurova.evolution.eval.runner import _DefaultAgent

    async def _echoes() -> bool:
        output = await _DefaultAgent().run(skill_text=PROBE_ECHO_TEXT, task_input="probe-task")
        return str(output) == PROBE_ECHO_TEXT

    try:
        echoed = asyncio.run(_echoes())
    except RuntimeError:  # 事件循环在别处起着：不猜，按未满足处理
        return False
    except Exception:  # noqa: BLE001 - 默认执行器都不存在了，谈不上"真轨迹已接"
        return False
    return not echoed


#: 四条前置的登记表（唯一出处）。reason 只在**不满足**时给人看的落点。
_REGISTRY: Dict[str, Dict[str, Any]] = {
    "caseLevelGate": {
        "title": "留出侧例级读数 + 例级不退化门",
        "probe": probeCaseLevelGate,
        "unmetReason": "runner 的留出侧拿不到例级读数，或门不咬合（§8 前置 1）",
    },
    "realTrajectoryExecutor": {
        "title": "判据执行面与线上行为同域（真 agent 轨迹）",
        "probe": probeRealTrajectoryExecutor,
        "unmetReason": "评测默认执行器仍在回显技能正文，留出分与线上行为不同域（§8 前置 2）",
    },
    "presentationLedger": {
        "title": "呈现与采纳可分离计数",
        "probe": probePresentationLedger,
        "unmetReason": "看不见『技能进了 prompt 但没被点名』这一格（§8 前置 3）",
    },
    "failClosedOnMissingEvidence": {
        "title": "缺证据时不产出可通过分数",
        "probe": probeFailClosedOnMissingEvidence,
        "unmetReason": "判分不可用仍可能给出可通过分数（§8 前置 4）",
    },
}


def automationPrerequisites() -> Dict[str, Dict[str, Any]]:
    """四条前置的当下读数：`{键: {title, satisfied, reason, probe}}`。

    每次现算，不缓存——缓存会把"实装被摘掉"这件事藏到下一个进程才暴露，
    而那正是本格要拦的东西；四条探针都是纯函数级开销。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for key, item in _REGISTRY.items():
        probe: Callable[[], bool] = item["probe"]
        satisfied = bool(probe())
        out[key] = {
            "title": item["title"],
            "satisfied": satisfied,
            "reason": "" if satisfied else item["unmetReason"],
            "probe": probe,
        }
    return out


def automationPrerequisiteVerdict(
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
) -> GateVerdict:
    """聚合结论：未满足即 `failed` 并**逐条点名**，不折叠成"没证据"。

    前置项是结构性事实（有没有实装），不是本轮采样缺失——所以不写 `unevidenced`：
    那会让"压根没做"与"这次没测到"同形（工单 003 点过的病）。
    """
    items = registry if registry is not None else automationPrerequisites()
    missing = [key for key, item in items.items() if not item["satisfied"]]
    if missing:
        detail = "；".join(
            f"{key}（{items[key]['title']}）：{items[key]['reason'] or '未满足'}"
            for key in sorted(missing)
        )
        return GateVerdict.failed(
            f"无人监督全自动的前置未满足 ⇒ {detail}",
            evidence={key: bool(items[key]["satisfied"]) for key in sorted(items)},
        )
    return GateVerdict.passed("四条自动化前置均在位",
                              evidence={key: True for key in sorted(items)})
