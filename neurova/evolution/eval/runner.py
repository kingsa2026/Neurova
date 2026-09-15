"""优化循环 — 变异 → 打分 → 约束闸 → 留出集对比 → 部署/拒绝。

对位 Hermes `evolution/skills/evolve_skill.py` 的骨架,核心纪律照搬:

  - **留出集是判据**:变体在 holdout 上必须优于基线,而非在训练集选最优;
  - **benchmark 是 GATE 不是 fitness**:技能分涨但 bench 回退 → 拒绝;
  - **约束闸**:尺寸/增长/语义保持,违反任一即丢弃变体;
  - **不达标保留基线**:deployed_text 永远是"当前最优且已过闸"的文本。

所有 judge / 变异 / 执行器 / bench 门都是可注入依赖,便于离线测试与
后续接真实 llm_router。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.mutator import JudgeFailure

logger = get_logger(__name__)

_EPS = 1e-9
# 每轮反射分析取评分最低的用例数(控制 LLM 成本)
_MAX_FAILURES = 3


class _JudgeLike(Protocol):
    async def score(self, *, task_input: str, expected_behavior: str, output: str,
                    skill_text: str, **kw) -> Any: ...


@dataclass
class EvolutionRunResult:
    """一次进化运行的结果与审计信息。"""

    rejected: bool = False
    reject_reason: str = ""
    baseline_text: str = ""
    deployed_text: str = ""
    holdout_before: float = 0.0
    holdout_after: float = 0.0
    train_before: float = 0.0
    train_best: float = 0.0
    iterations_run: int = 0
    bench_gain: float = 0.0
    constraint_failures: list[str] = field(default_factory=list)

    @property
    def improvement(self) -> float:
        return self.holdout_after - self.holdout_before

    @property
    def changed(self) -> bool:
        return self.deployed_text != self.baseline_text

    def to_dict(self) -> dict:
        return {
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "holdout_before": round(self.holdout_before, 4),
            "holdout_after": round(self.holdout_after, 4),
            "improvement": round(self.improvement, 4),
            "train_before": round(self.train_before, 4),
            "train_best": round(self.train_best, 4),
            "iterations_run": self.iterations_run,
            "bench_gain": round(self.bench_gain, 4),
            "changed": self.changed,
            "constraint_failures": list(self.constraint_failures),
        }


class _DefaultAgent:
    """默认执行器:把技能文本作为输出回显(离线/测试用)。

    真实接线方应注入一个真正跑 agent 的执行器——它拿 skill_text 当指令、
    task_input 当任务,返回 agent 的实际输出。
    """

    async def run(self, *, skill_text: str, task_input: str) -> str:
        return skill_text


class SkillEvolutionRunner:
    """技能/提示文本的进化运行器。

    依赖全部可注入:
      judge      — 判分器(LLMJudge 或测试用的脚本化 judge)
      mutate     — 变异函数 `async (*, artifact_text, artifact_type, failures) -> str`
      agent      — 执行器 `async (*, skill_text, task_input) -> str`
      bench_gate — `(baseline_text, candidate_text) -> float` 返回候选相对基线的 gain
      constraints— ConstraintValidator(可选;不注入则不校验)
    """

    def __init__(
        self,
        config: EvolutionConfig,
        *,
        judge: Any,
        agent: Any = None,
        mutate: Optional[Callable[..., Awaitable[str]]] = None,
        bench_gate: Optional[Callable[[str, str], float]] = None,
        constraints: Any = None,
    ):
        self.config = config
        self.judge = judge
        self.agent = agent or _DefaultAgent()
        self._mutate_fn = mutate
        self._bench_gate = bench_gate
        self._constraints = constraints

    # ── 内部:变异 ──

    async def _mutate(self, artifact_text: str, artifact_type: str,
                      failures: list[JudgeFailure]) -> str:
        if self._mutate_fn is not None:
            return await self._mutate_fn(
                artifact_text=artifact_text, artifact_type=artifact_type, failures=failures
            )
        from neurova.evolution.eval.mutator import ReflectiveMutator

        return await ReflectiveMutator(self.config).mutate(
            artifact_text=artifact_text, artifact_type=artifact_type, failures=failures
        )

    # ── 内部:评测 ──

    async def _call_judge(self, **kwargs) -> Any:
        """判分器适配:实例带 .score(LLMJudge)或纯函数(Hermes metric 式)。

        两种形态都接受——对齐 Hermes 把 metric 当函数传的用法,同时保留
        LLMJudge 的面向对象形态。
        """
        scorer = getattr(self.judge, "score", None)
        if scorer is not None:
            return await scorer(**kwargs)
        return await self.judge(**kwargs)

    async def _score_example(
        self, skill_text: str, ex: EvalExample, artifact_type: str
    ) -> tuple[float, str, str]:
        """返回 (composite, agent 输出, judge 反馈文本)。

        feedback 必须透传——反射式变异的输入就是它(Hermes GEPA:reads
        execution traces to understand WHY things fail);丢掉它变异退化成盲改。
        """
        output = await self.agent.run(skill_text=skill_text, task_input=ex.task_input)
        max_size = (
            self.config.max_tool_desc_size
            if artifact_type == "tool_description"
            else self.config.max_skill_size
        )
        score = await self._call_judge(
            task_input=ex.task_input,
            expected_behavior=ex.expected_behavior,
            output=output,
            skill_text=skill_text,
            artifact_size=len(skill_text),
            max_size=max_size,
        )
        return (
            float(getattr(score, "composite", score)),
            output,
            str(getattr(score, "feedback", "") or ""),
        )

    async def _evaluate(
        self, skill_text: str, examples: list[EvalExample], artifact_type: str
    ) -> tuple[float, list[tuple[EvalExample, float, str, str]]]:
        if not examples:
            return 0.0, []
        details: list[tuple[EvalExample, float, str, str]] = []
        for ex in examples:
            score, output, feedback = await self._score_example(skill_text, ex, artifact_type)
            details.append((ex, score, output, feedback))
        avg = sum(s for _, s, _, _ in details) / len(details)
        return avg, details

    async def _collect_failures(
        self, skill_text: str, examples: list[EvalExample], artifact_type: str
    ) -> list[JudgeFailure]:
        _, details = await self._evaluate(skill_text, examples, artifact_type)
        worst = sorted(details, key=lambda d: d[1])[:_MAX_FAILURES]
        return [
            JudgeFailure(task_input=ex.task_input, output=output, feedback=feedback, score=score)
            for ex, score, output, feedback in worst
        ]

    # ── 主循环 ──

    async def run(
        self,
        *,
        baseline_text: str,
        artifact_type: str,
        dataset: EvalDataset,
        iterations: Optional[int] = None,
    ) -> EvolutionRunResult:
        result = EvolutionRunResult(baseline_text=baseline_text, deployed_text=baseline_text)

        if not dataset or not dataset.all_examples:
            result.rejected = True
            result.reject_reason = "empty_dataset"
            return result

        holdout = dataset.holdout or dataset.val or dataset.train
        tune = dataset.train + dataset.val
        if not tune:
            tune = holdout

        result.holdout_before = await self._evaluate_avg(baseline_text, holdout, artifact_type)
        result.train_before = await self._evaluate_avg(baseline_text, tune, artifact_type)

        best_text, best_score = baseline_text, result.train_before
        n_iters = self.config.iterations if iterations is None else iterations

        for _ in range(max(0, n_iters)):
            failures = await self._collect_failures(best_text, dataset.val or tune, artifact_type)
            candidate = await self._mutate(best_text, artifact_type, failures)
            if not candidate or candidate == best_text:
                continue

            if self._constraints is not None:
                checks = self._constraints.validate(candidate, artifact_type, baseline_text=baseline_text)
                failed = [c.name for c in checks if not c.passed]
                if failed:
                    result.constraint_failures.extend(failed)
                    logger.debug("候选被约束闸拒绝: %s", failed)
                    continue

            result.iterations_run += 1
            score = await self._evaluate_avg(candidate, tune, artifact_type)
            if score > best_score + _EPS:
                best_text, best_score = candidate, score

        result.train_best = best_score
        result.holdout_after = await self._evaluate_avg(best_text, holdout, artifact_type)
        result.deployed_text = best_text

        # ── 判定 1:留出集回退 → 拒绝(防过拟合)──
        if result.holdout_after < result.holdout_before - _EPS:
            result.rejected = True
            result.reject_reason = "holdout_regression"
            result.deployed_text = baseline_text
            return result

        # ── 判定 2:无实质增益 → 保留基线 ──
        if result.holdout_after <= result.holdout_before + self.config.min_improvement + _EPS:
            result.rejected = True
            result.reject_reason = "no_improvement"
            result.deployed_text = baseline_text
            return result

        # ── 判定 3:benchmark 回归门(技能分涨但 bench 回退 → 拒绝)──
        if self._bench_gate is not None:
            try:
                gain = float(self._bench_gate(baseline_text, best_text))
            except Exception as e:  # noqa: BLE001 - bench 不可用不应吞掉一个已通过留出集的变体
                logger.debug("bench gate 调用失败,跳过该闸: %s", e)
                gain = 0.0
            result.bench_gain = gain
            if gain < -self.config.bench_tolerance:
                result.rejected = True
                result.reject_reason = "bench_regression"
                result.deployed_text = baseline_text
                return result

        return result

    async def _evaluate_avg(self, skill_text: str, examples: list[EvalExample],
                            artifact_type: str) -> float:
        avg, _ = await self._evaluate(skill_text, examples, artifact_type)
        return avg
