"""benchmark 回归门 — 把 RSI 端到端评测集接成文本进化的 GATE。

核心纪律:benchmark 是 GATE 不是 fitness——
变体在评测集上再好,系统基准回退即拒绝。

接线说明(诚实边界,勿超读):
  - eval_harness 度量的是四族可优化参数(AdaptiveToolWeights/Sleep/
    Emotion/Experience)的**行为地板**;纯文本候选(技能/提示词正文)不触及
    这些参数 → 门对该类候选中性通过(0),这是诚实降级,不假装测过;
  - 门咬合的接线点在 apply_fn:调用方提供"应用候选 → 度量 → 恢复"的
    通道(如把进化产物暂挂到系统参数/注册表),门即获得
    "先量基线 → 应用候选 → 再量 → 恢复 → 回传 gain"的完整语义;
  - harness.run() 真实执行(确定性、零 LLM、毫秒级),不是假调用;
  - run() 自报度量失明时 score 为 None(全族用例回退到 setpoint),门按中性
    判定并留 WARNING 痕迹——"没量出来"与"测得 0 增益"数值相同但含义相反。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def _params_from_orchestrator(orchestrator: Any) -> dict:
    """从 RSI 编排器取活参数(与 orchestrator._measure_performance 同口径)。"""
    return {
        system: {
            p.name: p.current_value for p in params if p.current_value is not None
        }
        for system, params in orchestrator.integration_manager.get_optimizable_parameters().items()
    }


#: 无 apply_fn 时的显式中性 gain（区别于"真测出来 0 增益"）
NEUTRAL_GAIN = 0.0
#: 中性通过的原因标签——审计时必须能看出"这道门没咬合"
NEUTRAL_REASON_NO_APPLY_FN = "no_apply_fn"
#: 有 apply_fn 但本轮读数不存在（参数族为空 ⇒ harness 自报 measurement_blind）
NEUTRAL_REASON_MEASUREMENT_BLIND = "measurement_blind"


def make_eval_harness_gate(
    orchestrator: Any = None,
    live_params_provider: Optional[Callable[[], dict]] = None,
    apply_fn: Optional[Callable[[str], Any]] = None,
) -> Callable[[str, str], float]:
    """构造 bench_gate: `(baseline_text, candidate_text) -> gain`。

    apply_fn(candidate_text) -> restore:把候选暂挂进系统后返回恢复函数。

    诚实边界（Issue #46 复核，2026-09-22）：无 apply_fn 时纯文本候选**不触及**
    eval_harness 度量的四族参数 → 返回中性 `NEUTRAL_GAIN`，并在返回函数上
    挂 `neutral`/`neutral_reason` 供审计取证。**绝不假称测过**：文本候选在
    四族参数上本来就是 0 位移，"跑一遍参数快照"得到 0 也不是证据。

    中性**只有一条来源**：调用方没提供 apply_fn。曾经的"从技能注册表派生
    apply_fn"通道已删——那条路把候选正文挂进技能条目就宣告 `neutral=False`，
    但四族参数一点没动（gain 依然恒 0），等于把"这道门没咬合"的唯一可审计
    痕迹抹掉；且它的 restore 是浅拷贝快照，实测**永久改写**技能正文
    （`apply('CAND')` → `restore()` → 条目内容仍为 `'CAND'`）。假咬合比
    诚实中性更坏，故连根删除而不是修补恢复逻辑。

    因此：技能文本进化在四族参数上**本来就没有位移可言**，这道门对它恒中性
    ——这是构造成立的事实，不是待修的缺陷。要让它对某类候选真咬合，唯一
    路径是调用方提供一条**能证明位移了参数族**的 apply_fn。
    """
    from neurova.evolution.rsi.eval_harness import RSIEvalHarness

    harness = RSIEvalHarness()

    def _live_params() -> dict:
        if live_params_provider is not None:
            try:
                return live_params_provider() or {}
            except Exception as e:  # noqa: BLE001
                logger.debug("live_params_provider 失败, 空参数评测: %s", e)
                return {}
        if orchestrator is not None:
            try:
                return _params_from_orchestrator(orchestrator)
            except Exception as e:  # noqa: BLE001
                logger.debug("从编排器取活参数失败, 空参数评测: %s", e)
                return {}
        return {}

    def _readout(outcome: Any) -> Optional[float]:
        """评测集读数 → float 或 None。

        工单 007 起 `run()["score"]` 可以是 None（全族用例回退 setpoint = 度量失明）。
        None 不是 0 分：`float(None)` 会崩，把 None 兜成 0.0 又等于把"没量出来"
        冒充成"测得零增益"——两者对候选的结论相反。
        """
        score = outcome.get("score") if isinstance(outcome, dict) else None
        return None if score is None else float(score)

    def gate(baseline_text: str, candidate_text: str) -> float:
        """返回候选相对基线的 gain，并把**本轮**是否咬合落到 `neutral`/`neutral_reason`。

        这三个属性随每次调用重算（不是构造期定值）：`neutral` 回答的是"这一轮
        的结果是不是中性放行"，而"调用方提供了 apply_fn"只是它的必要条件。
        二者混同会让"取不到读数 ⇒ 中性放行"这一轮对外宣称成"已咬合、零增益"。
        """
        before = _readout(harness.run(_live_params()))
        if apply_fn is None:
            # 纯文本候选不触及参数族——**中性**（非"测得 0"）。基线度量确实
            # 跑了一遍，但那不是"候选的增益"。理由随函数外挂供审计取证。
            _mark_neutral(NEUTRAL_REASON_NO_APPLY_FN)
            logger.debug("bench gate(无 apply_fn): before=%s, 纯文本候选中性通过", before)
            return NEUTRAL_GAIN
        restore: Any = None
        try:
            restore = apply_fn(candidate_text)
            after = _readout(harness.run(_live_params()))
        finally:
            if restore is not None:
                try:
                    restore()
                except Exception as e:  # noqa: BLE001 - 恢复失败必须暴露,不能吞
                    logger.error("bench gate 恢复系统状态失败: %s", e)
        if before is None or after is None:
            # 读数不存在就没有"回退"可言：按中性放行，但必须留下可审计的痕迹，
            # 否则这道门在失明时与在咬合时对外长得一模一样。
            _mark_neutral(NEUTRAL_REASON_MEASUREMENT_BLIND)
            logger.warning(
                "bench gate 度量失明(before=%s after=%s)：按中性判定，不构成通过证据",
                before, after,
            )
            return NEUTRAL_GAIN
        _mark_neutral("")
        gain = after - before
        logger.debug("bench gate: before=%.4f after=%.4f gain=%.4f", before, after, gain)
        return gain

    def _mark_neutral(reason: str) -> None:
        """把本轮的咬合状态写到门函数上（空 reason = 本轮真咬合）。"""
        gate.neutral = bool(reason)
        gate.neutral_reason = reason

    # 构造期先按"还没跑过任何一轮"标注：有 apply_fn 不等于已咬合，故此处
    # 只把"没有 apply_fn"这一确定事实写死；其余留给每轮调用刷新。
    _mark_neutral(NEUTRAL_REASON_NO_APPLY_FN if apply_fn is None else "")
    return gate

