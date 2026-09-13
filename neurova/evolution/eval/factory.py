"""装配工厂 — 把判分/变异/约束闸/回归门接成可用的进化 runner。

调用方一行即可获得完整闭环:
    runner = make_skill_evolution_runner()
    result = await runner.run(baseline_text=..., artifact_type="skill", dataset=ds)
    if not result.rejected: 提案(result.deployed_text)

总开关:NEUROVA_TEXT_EVOLUTION(默认关)——关闭时返回 None,调用方
走既有路径(skill_improver 字典建议)。这是"进化产物默认待审"C10 哲学
在装配层的体现。
"""

from __future__ import annotations

from typing import Any, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig, text_evolution_enabled

logger = get_logger(__name__)


def make_skill_evolution_runner(
    config: Optional[EvolutionConfig] = None,
    *,
    agent: Any = None,
    bench_gate: Optional[Any] = None,
    with_constraints: bool = True,
    judge: Optional[Any] = None,
    llm_call: Optional[Any] = None,
    mutate: Optional[Any] = None,
) -> Optional["SkillEvolutionRunner"]:
    """装配默认 runner;总开关关闭时返回 None(调用方走既有路径)。

    judge/llm_call:默认走 llm_router;测试可注入假判分器/假 LLM 通道。
    mutate:注入即替换 ReflectiveMutator(默认 None → runner 内自建)。
    bench_gate 缺省时接 RSI eval_harness 门(见 bench_gate.py 的诚实边界)。
    """
    if not text_evolution_enabled():
        logger.debug("NEUROVA_TEXT_EVOLUTION 未开启, 不装配文本进化 runner")
        return None
    from neurova.evolution.eval.constraints import ConstraintValidator
    from neurova.evolution.eval.fitness import LLMJudge
    from neurova.evolution.eval.runner import SkillEvolutionRunner

    cfg = config or EvolutionConfig()
    if bench_gate is None:
        try:
            from neurova.evolution.eval.bench_gate import make_eval_harness_gate

            bench_gate = make_eval_harness_gate()
        except Exception as e:  # noqa: BLE001 - 门不可用不阻断装配(runner 里再兜底)
            logger.debug("eval_harness 门装配失败, 进化运行不带基准门: %s", e)
            bench_gate = None
    return SkillEvolutionRunner(
        cfg,
        judge=judge if judge is not None else LLMJudge(cfg, llm_call=llm_call),
        agent=agent,
        mutate=mutate,
        bench_gate=bench_gate,
        constraints=ConstraintValidator(cfg) if with_constraints else None,
    )
