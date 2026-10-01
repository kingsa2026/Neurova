"""优化循环 — 变异 → 打分 → 约束闸 → 留出集对比 → 部署/拒绝。


  - **留出集是判据**:变体在 holdout 上必须优于基线,而非在训练集选最优;
  - **benchmark 是 GATE 不是 fitness**:技能分涨但 bench 回退 → 拒绝;
  - **约束闸**:尺寸/增长/语义保持,违反任一即丢弃变体;
  - **不达标保留基线**:deployed_text 永远是"当前最优且已过闸"的文本。

所有 judge / 变异 / 执行器 / bench 门都是可注入依赖,便于离线测试与
后续接真实 llm_router。
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from neurova.core.logger import get_logger
from neurova.evolution.eval.calibration import NoiseBand
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample, evaluation_split
from neurova.evolution.eval.mutator import JudgeFailure

logger = get_logger(__name__)

_EPS = 1e-9
# 每轮反射分析取评分最低的用例数(控制 LLM 成本)
_MAX_FAILURES = 3


def _redact_eval_error(e: Exception) -> str:
    """P2-9：单例异常文本脱敏截断——会进 JudgeFailure.feedback → 变异器
    prompt 面，凭据/密钥形态内容不得外泄。脱敏器自身故障时只留异常类型。"""
    try:
        from neurova.skills.evolution_inputs_guard import redact_secrets

        return redact_secrets(f"eval_error:{type(e).__name__}: {e}")[:160]
    except Exception:  # noqa: BLE001 - 脱敏器故障不外泄原文
        return f"eval_error:{type(e).__name__}"[:160]


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
    # P0：判分可用性（judge 全线失败/输出不可解析 → 任何"增益"都不可信）
    judge_available: bool = True
    # benchmark 门本轮是否真的咬合（False 且 reason 非空 = 中性放行）。
    # 没有这两个字段时，bench_gain=0.0 在"真咬合且零增益"与"门没量出来"
    # 两种情形下对外完全同形——门内的诚实标注必须外露到结果面。
    bench_neutral: bool = False
    bench_neutral_reason: str = ""
    # P0-1 噪声地板：本轮接受判据的实效阈值 = max(min_improvement, δ)，
    # noise_band 为空 dict 表示未校准（δ=0，行为与旧版一致）。
    accept_threshold: float = 0.0
    noise_band: dict = field(default_factory=dict)
    # P0-2 holdout 防污染：heldout 集只做验收证据（0.0 = 本轮无 heldout 集）。
    # 这些字段永不反向影响 rejected/reject_reason/deployed_text。
    heldout_before: float = 0.0
    heldout_after: float = 0.0
    # P1-5 成本规则：基线/候选文本长度与相对变化率（0.0 = 规则未启用）。
    cost_baseline: int = 0
    cost_candidate: int = 0
    cost_change: float = 0.0
    # P1-7a 多变体：本轮配置与实际被评测的候选总数（审计面）。
    variants_per_round: int = 1
    candidates_evaluated: int = 0
    # P2-9 missing 记 0：本轮单用例评测异常数（0 分占满分母，运行不中断）。
    # 与 judge_unavailable（判分基础设施不可用）诚实分开。
    eval_errors: int = 0

    @property
    def improvement(self) -> float:
        return self.holdout_after - self.holdout_before

    @property
    def heldout_improvement(self) -> float:
        return self.heldout_after - self.heldout_before

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
            "bench_neutral": self.bench_neutral,
            "bench_neutral_reason": self.bench_neutral_reason,
            "accept_threshold": round(self.accept_threshold, 6),
            "noise_band": dict(self.noise_band),
            "heldout_before": round(self.heldout_before, 4),
            "heldout_after": round(self.heldout_after, 4),
            "heldout_improvement": round(self.heldout_improvement, 4),
            "cost_baseline": self.cost_baseline,
            "cost_candidate": self.cost_candidate,
            "cost_change": round(self.cost_change, 4),
            "variants_per_round": self.variants_per_round,
            "candidates_evaluated": self.candidates_evaluated,
            "eval_errors": self.eval_errors,
            "judge_available": self.judge_available,
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
        leak_critic: Any = None,
        ledger: Any = None,
    ):
        self.config = config
        self.judge = judge
        self.agent = agent or _DefaultAgent()
        self._mutate_fn = mutate
        self._bench_gate = bench_gate
        self._constraints = constraints
        # P0-3 泄漏审查：None = 不启用（行为与旧版一致）；注入 LeakCritic 后
        # 候选在约束闸之后、评测之前过闸，命中即跳过并留审计标记。
        self._leak_critic = leak_critic
        # P1-4 编辑历史台账：None = 不启用；注入后逐候选落账并把最近记录
        # 回喂变异器（已证伪假设禁止重画）。
        self._ledger = ledger
        self._run_eval_errors = 0  # P2-9：run() 开始时清零，全轮累加

    # ── 内部:变异 ──

    async def _mutate(self, artifact_text: str, artifact_type: str,
                      failures: list[JudgeFailure],
                      history: Optional[list[dict]] = None) -> str:
        if self._mutate_fn is not None:
            # 旧签名注入的 mutate（不收 history）不传新 kwarg——装配契约不漂移
            kwargs: dict[str, Any] = {}
            if history:
                try:
                    if "history" in inspect.signature(self._mutate_fn).parameters:
                        kwargs["history"] = history
                except (TypeError, ValueError):
                    pass
            return await self._mutate_fn(
                artifact_text=artifact_text, artifact_type=artifact_type, failures=failures,
                **kwargs
            )
        from neurova.evolution.eval.mutator import ReflectiveMutator

        return await ReflectiveMutator(self.config).mutate(
            artifact_text=artifact_text, artifact_type=artifact_type, failures=failures,
            history=history,
        )

    def _ledger_append(self, ledger_key: str, artifact_type: str,
                       failures: list[JudgeFailure], *, accepted: bool,
                       reject_reason: str = "", delta_train: Optional[float] = None,
                       constraint_failures: Optional[list[str]] = None) -> Optional[int]:
        """P1-4：逐候选结局入账（含被闸拒绝的）。台账故障按既有审计面惯例
        只捕 OSError（磁盘问题不阻断进化，其他缺陷如实上抛）。"""
        if self._ledger is None or not ledger_key:
            return None
        worst = min((f.score for f in failures), default=None)
        try:
            return self._ledger.append(ledger_key, {
                "artifact_type": artifact_type,
                "hypothesis": ("; ".join((f.feedback or "")[:80] for f in failures[:3])
                               or "(无失败反馈的清晰化变异)")[:200],
                "failures_digest": f"n={len(failures)};worst={worst}",
                "delta_train": None if delta_train is None else round(delta_train, 6),
                "delta_holdout": None,
                "accepted": accepted,
                "reject_reason": reject_reason,
                "constraint_failures": list(constraint_failures or []),
            })
        except OSError as e:
            logger.debug("编辑历史台账写入失败: %s", e)
            return None

    # ── 内部:评测 ──

    async def _call_judge(self, **kwargs) -> Any:
        """判分器适配:实例带 .score(LLMJudge)或纯函数。

        LLMJudge 的面向对象形态。
        """
        scorer = getattr(self.judge, "score", None)
        if scorer is not None:
            return await scorer(**kwargs)
        return await self.judge(**kwargs)

    async def _score_example(
        self, skill_text: str, ex: EvalExample, artifact_type: str
    ) -> tuple[float, str, str, bool]:
        """返回 (composite, agent 输出, judge 反馈文本, 是否单例失败)。

        P2-9 missing 记 0：单例执行/判分异常 → 0 分占满分母、运行不中断；
        异常文本脱敏截断后进 feedback（会到变异器 prompt 面）。0.0 是诚实
        记分不是中性分——防"评测崩了但剩余用例分高"的幸存者偏差。
        """
        try:
            output = await self.agent.run(skill_text=skill_text, task_input=ex.task_input)
        except Exception as e:  # noqa: BLE001 - 单例失败记 0（BaseException 不经此路）
            return 0.0, "", _redact_eval_error(e), True
        max_size = (
            self.config.max_tool_desc_size
            if artifact_type == "tool_description"
            else self.config.max_skill_size
        )
        try:
            score = await self._call_judge(
                task_input=ex.task_input,
                expected_behavior=ex.expected_behavior,
                output=output,
                skill_text=skill_text,
                artifact_size=len(skill_text),
                max_size=max_size,
            )
        except Exception as e:  # noqa: BLE001 - 单例判分失败记 0
            return 0.0, str(output or ""), _redact_eval_error(e), True
        return (
            float(getattr(score, "composite", score)),
            output,
            str(getattr(score, "feedback", "") or ""),
            False,
        )

    async def _evaluate(
        self, skill_text: str, examples: list[EvalExample], artifact_type: str
    ) -> tuple[float, list[tuple[EvalExample, float, str, str]]]:
        if not examples:
            return 0.0, []
        details: list[tuple[EvalExample, float, str, str]] = []
        eval_errors = 0
        for ex in examples:
            score, output, feedback, failed = await self._score_example(skill_text, ex, artifact_type)
            eval_errors += int(failed)
            details.append((ex, score, output, feedback))
        self._run_eval_errors += eval_errors
        avg = sum(s for _, s, _, _ in details) / len(details)
        return avg, details

    async def _collect_failures_sorted(self, skill_text: str, examples: list[EvalExample],
                                       artifact_type: str) -> list[JudgeFailure]:
        """全量失败用例按得分升序（P1-7a 分片采样的数据源）。"""
        _, details = await self._evaluate(skill_text, examples, artifact_type)
        return [
            JudgeFailure(task_input=ex.task_input, output=output, feedback=feedback, score=score)
            for ex, score, output, feedback in sorted(details, key=lambda d: d[1])
        ]

    async def _multi_variant_round(
        self, *, best_text: str, best_score: float, baseline_text: str,
        dataset: EvalDataset, tune: list[EvalExample], artifact_type: str,
        ledger_key: str, leak_markers: Optional[frozenset], result: EvolutionRunResult,
    ) -> Optional[tuple[str, float, Optional[int]]]:
        """P1-7a：一轮多变体并行搜索。

        各候选拿失败严重度轮转分片（不重叠），过闸（约束/泄漏）后并行评测
        tune 集，tune 分 argmax（严格大于才替换——平分保持先到，确定性）。
        台账逐候选入账，仅 argmax 胜者记 accepted=True（其余 variant_lost）。
        返回 (胜者文本, 分数, 台账 seq)——无幸存/无胜者返回 None。
        """
        m = result.variants_per_round
        failures_all = await self._collect_failures_sorted(best_text, dataset.val or tune, artifact_type)
        # 轮转分片：严重度打散到各候选；空分片回退全量（无失败时的清晰化变异）
        shards = [failures_all[v::m] if failures_all[v::m] else failures_all
                  for v in range(m)]

        history = None
        if self._ledger is not None and ledger_key:
            history = self._ledger.recent(ledger_key)
        mutated = await asyncio.gather(*[
            self._mutate(best_text, artifact_type, shard, history=history)
            for shard in shards
        ])

        survivors: list[tuple[str, list[JudgeFailure]]] = []
        seen = {best_text}
        for shard, cand in zip(shards, mutated):
            if not cand or cand in seen:
                continue
            seen.add(cand)
            if self._constraints is not None:
                checks = self._constraints.validate(cand, artifact_type, baseline_text=baseline_text)
                failed = [c.name for c in checks if not c.passed]
                if failed:
                    result.constraint_failures.extend(failed)
                    logger.debug("多变体候选被约束闸拒绝: %s", failed)
                    self._ledger_append(ledger_key, artifact_type, shard,
                                        accepted=False,
                                        reject_reason=f"constraints:{','.join(failed)}",
                                        constraint_failures=result.constraint_failures)
                    continue
            if self._leak_critic is not None:
                verdict = await self._leak_critic.review(
                    candidate_text=cand, baseline_text=baseline_text, markers=leak_markers)
                if verdict.leaked:
                    result.constraint_failures.append(f"leak:{verdict.category}")
                    self._ledger_append(ledger_key, artifact_type, shard,
                                        accepted=False,
                                        reject_reason=f"leak:{verdict.category}",
                                        constraint_failures=result.constraint_failures)
                    continue
            survivors.append((cand, shard))

        if not survivors:
            return None
        result.candidates_evaluated += len(survivors)
        result.iterations_run += len(survivors)
        scores = await asyncio.gather(*[
            self._evaluate_avg(cand, tune, artifact_type) for cand, _ in survivors
        ])
        survivors_scores = list(zip(survivors, scores))

        # 先定 argmax 胜者（严格大于才替换——平分保持先到，确定性），
        # 再逐候选入账：只有最终胜者记 accepted=True（超越本轮基线才算）
        winner_idx: Optional[int] = None
        for idx, (_cand, score) in enumerate(survivors_scores):
            if score > best_score + _EPS and (
                    winner_idx is None or score > survivors_scores[winner_idx][1] + _EPS):
                winner_idx = idx
        winner: Optional[tuple[str, float, Optional[int]]] = None
        for idx, ((cand, shard), score) in enumerate(survivors_scores):
            is_winner = winner_idx == idx
            seq = self._ledger_append(ledger_key, artifact_type, shard,
                                      accepted=is_winner,
                                      reject_reason="" if is_winner else "variant_lost",
                                      delta_train=score - best_score)
            if is_winner:
                winner = (cand, score, seq)
        return winner

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
        noise_band: Optional[NoiseBand] = None,
        ledger_key: str = "",
    ) -> EvolutionRunResult:
        result = EvolutionRunResult(baseline_text=baseline_text, deployed_text=baseline_text)
        self._run_eval_errors = 0  # P2-9：本轮清零（探针路径有独立语义，不计入）

        if not dataset or not dataset.all_examples:
            result.rejected = True
            result.reject_reason = "empty_dataset"
            return result

        holdout = evaluation_split(dataset)
        tune = dataset.train + dataset.val
        if not tune:
            tune = holdout

        # P0-1 噪声地板：接受阈值 = max(min_improvement, δ)。δ 来源优先级：
        # 注入的 NoiseBand（service 校准产物）> config.noise_band_delta（历史校准
        # 回填）> 无（未校准，行为与旧版一致）。
        band = noise_band
        if band is None and self.config.noise_band_delta > 0:
            band = NoiseBand(delta=self.config.noise_band_delta, sd_null=0.0,
                             z=self.config.noise_z, method="config", n_repeats=0)
        accept_threshold = max(self.config.min_improvement,
                               band.delta if band is not None else 0.0)
        result.accept_threshold = round(accept_threshold, 6)
        result.noise_band = band.to_dict() if band is not None else {}

        # P0 判分可用性前置：judge 全线不可用时，"before/after 都是中性 0.5"
        # 曾被当成"零增益通过"。先探针，不可用直接判 judge_unavailable。
        if not await self._judge_available(baseline_text, holdout, artifact_type):
            result.judge_available = False
            result.rejected = True
            result.reject_reason = "judge_unavailable"
            return result

        result.holdout_before = await self._evaluate_avg(baseline_text, holdout, artifact_type)
        result.train_before = await self._evaluate_avg(baseline_text, tune, artifact_type)

        best_text, best_score = baseline_text, result.train_before
        best_seq: Optional[int] = None
        # P0-3：泄漏标记按数据集只提取一次（多路候选共享同一标记集）
        leak_markers: Optional[frozenset] = None
        if self._leak_critic is not None:
            leak_markers = self._leak_critic.build_markers(dataset)
        result.variants_per_round = max(1, int(self.config.variants_per_round))
        n_iters = self.config.iterations if iterations is None else iterations

        for _ in range(max(0, n_iters)):
            # P1-7a：多变体并行轮（失败子集分片 → 并行变异/评测 → argmax）
            if result.variants_per_round > 1:
                won = await self._multi_variant_round(
                    best_text=best_text, best_score=best_score,
                    baseline_text=baseline_text, dataset=dataset, tune=tune,
                    artifact_type=artifact_type, ledger_key=ledger_key,
                    leak_markers=leak_markers, result=result,
                )
                if won is not None:
                    best_text, best_score, best_seq = won
                continue

            failures = await self._collect_failures(best_text, dataset.val or tune, artifact_type)
            # P1-4：最近编辑历史回喂变异器（已证伪假设禁止重画）
            history = None
            if self._ledger is not None and ledger_key:
                history = self._ledger.recent(ledger_key)
            candidate = await self._mutate(best_text, artifact_type, failures, history=history)
            if not candidate or candidate == best_text:
                continue

            if self._constraints is not None:
                checks = self._constraints.validate(candidate, artifact_type, baseline_text=baseline_text)
                failed = [c.name for c in checks if not c.passed]
                if failed:
                    result.constraint_failures.extend(failed)
                    logger.debug("候选被约束闸拒绝: %s", failed)
                    self._ledger_append(ledger_key, artifact_type, failures,
                                        accepted=False,
                                        reject_reason=f"constraints:{','.join(failed)}",
                                        constraint_failures=result.constraint_failures)
                    continue

            # P0-3 泄漏审查：评测前拦截背题/退化候选（宁漏勿误杀）。
            if self._leak_critic is not None:
                verdict = await self._leak_critic.review(
                    candidate_text=candidate, baseline_text=baseline_text,
                    markers=leak_markers)
                if verdict.leaked:
                    result.constraint_failures.append(f"leak:{verdict.category}")
                    logger.debug("候选被泄漏闸拒绝(%s): %s",
                                 verdict.category, verdict.evidence[:100])
                    self._ledger_append(ledger_key, artifact_type, failures,
                                        accepted=False,
                                        reject_reason=f"leak:{verdict.category}",
                                        constraint_failures=result.constraint_failures)
                    continue

            result.iterations_run += 1
            result.candidates_evaluated += 1
            score = await self._evaluate_avg(candidate, tune, artifact_type)
            improved = score > best_score + _EPS
            seq = self._ledger_append(ledger_key, artifact_type, failures,
                                      accepted=improved,
                                      delta_train=score - best_score)
            if improved:
                best_text, best_score = candidate, score
                best_seq = seq

        result.train_best = best_score
        result.holdout_after = await self._evaluate_avg(best_text, holdout, artifact_type)
        result.deployed_text = best_text
        # P1-4：胜者在留出集上的实测差回填其台账记录（无论最终接受与否，
        # 这都是该假设的诚实证据）
        if self._ledger is not None and ledger_key and best_seq is not None:
            try:
                self._ledger.patch(ledger_key, best_seq,
                                   {"delta_holdout": round(result.improvement, 6)})
            except OSError as e:
                logger.debug("编辑历史台账回填失败: %s", e)

        # ── 判定 1:留出集回退 → 拒绝(防过拟合)──
        if result.holdout_after < result.holdout_before - _EPS:
            result.rejected = True
            result.reject_reason = "holdout_regression"
            result.deployed_text = baseline_text
            await self._attach_heldout_evidence(result, dataset, artifact_type)
            return result

        # ── 判定 2:无实质增益 → 保留基线 ──
        # 阈值 = max(min_improvement, δ)：δ>0（已校准）时，评测噪声内的
        # "增益"不被当成真提升（P0-1 噪声地板）；未校准时即 min_improvement。
        if result.holdout_after <= result.holdout_before + accept_threshold + _EPS:
            result.rejected = True
            result.reject_reason = "no_improvement"
            result.deployed_text = baseline_text
            await self._attach_heldout_evidence(result, dataset, artifact_type)
            return result

        # ── 判定 2.5:成本规则（P1-5）──
        # ΔC ≤ β0 + β1·ΔS：涨的成本必须由实测增益买单。文本臂成本代理 =
        # 长度变化率（零 LLM、可复现）；执行器将来提供 token usage 时可无缝
        # 替换代理（字段已留）。基线为空串时 ΔC 记 0（无从比较即不判）。
        if self.config.cost_rule_enabled:
            result.cost_baseline = len(result.baseline_text)
            result.cost_candidate = len(best_text)
            if result.cost_baseline > 0:
                delta_c = (result.cost_candidate - result.cost_baseline) / result.cost_baseline
                result.cost_change = delta_c
                budget = self.config.cost_beta0 + self.config.cost_beta1 * result.improvement
                if delta_c > budget:
                    result.rejected = True
                    result.reject_reason = "cost_rule_failed"
                    result.deployed_text = baseline_text
                    await self._attach_heldout_evidence(result, dataset, artifact_type)
                    return result

        # ── 判定 3:benchmark 回归门(技能分涨但 bench 回退 → 拒绝)──
        if self._bench_gate is not None:
            try:
                gain = float(self._bench_gate(baseline_text, best_text))
            except Exception as e:  # noqa: BLE001 - bench 不可用不应吞掉一个已通过留出集的变体
                logger.debug("bench gate 调用失败,跳过该闸: %s", e)
                gain = 0.0
            result.bench_gain = gain
            # 门的诚实标注外露：`bench_gain=0.0` 在"真咬合且零增益"与
            # "门压根没量出来（中性放行）"两种情形下数值相同、含义相反，
            # 故把门本轮的 `neutral`/`neutral_reason` 收进结果面（门可能不
            # 提供这两个属性 → 缺省视为"未自报"，不臆测为已咬合）。
            result.bench_neutral = bool(getattr(self._bench_gate, "neutral", False))
            result.bench_neutral_reason = str(getattr(self._bench_gate, "neutral_reason", "") or "")
            if gain < -self.config.bench_tolerance:
                result.rejected = True
                result.reject_reason = "bench_regression"
                result.deployed_text = baseline_text
                await self._attach_heldout_evidence(result, dataset, artifact_type)
                return result

        await self._attach_heldout_evidence(result, dataset, artifact_type)
        return result

    async def _attach_heldout_evidence(self, result: EvolutionRunResult,
                                       dataset: EvalDataset, artifact_type: str) -> None:
        """P0-2 holdout 防污染：在最终判定**之后**对 heldout 集评测基线与
        部署文本各一次，只写报告字段。

        heldout 永不参与接受/拒绝判定、变异失败采样或逐轮评测——否则
        它会被搜索过程自适应消耗，退化成第二个判据集。"""
        result.eval_errors = self._run_eval_errors  # P2-9：结果面外露单例失败数
        if not dataset.heldout:
            return
        result.heldout_before = await self._evaluate_avg(
            result.baseline_text, dataset.heldout, artifact_type)
        result.heldout_after = await self._evaluate_avg(
            result.deployed_text, dataset.heldout, artifact_type)

    async def _evaluate_avg(self, skill_text: str, examples: list[EvalExample],
                            artifact_type: str) -> float:
        avg, _ = await self._evaluate(skill_text, examples, artifact_type)
        return avg

    async def _judge_available(self, skill_text: str, examples: list[EvalExample],
                               artifact_type: str) -> bool:
        """探针：这批用例上判分是否真实可用（P0 零增益放行堵漏）。

        `FitnessScore.judge_available` 是**可选**契约（外部 judge 不实现也
        合理），但缺省值时不能假设"可用"——那等于把老行为放回来。因此这里
        按 best-effort 从两种判分器形态取真实产物：
          - 实例带 `.score(...)`（LLMJudge / 测试脚本 judge）→ 直接看回值标注；
          - 纯函数 judge → 无标注，视为可用（它没有"LLM 不可用"这个态）。
        取不到任何产物（异常/None）一律判不可用：判分没跑起来就不是证据。
        """
        if not examples:
            return True
        scorer = getattr(self.judge, "score", None)
        if scorer is None:
            return True  # 纯函数判分器：不存在"判分基础设施不可用"
        ex = examples[0]
        try:
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
        except Exception as e:  # noqa: BLE001 - 探针自身故障 = 判分不可用（保守拒绝）
            logger.debug("judge 可用性探针失败: %s", e)
            return False
        if score is None:
            return False
        return bool(getattr(score, "judge_available", True))
