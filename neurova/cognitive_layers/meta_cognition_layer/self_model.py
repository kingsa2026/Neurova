"""SelfModelEngine — 洞察编译器（V3 元认知融合 · 全确定性，零 LLM 依赖）

反思引擎的 V3 形态：五个确定性算子全部是台账（MetaLedger）上的纯函数，
产出结构化教训（lesson）而非叙事报告。质量下限由统计与样本量决定，
与模型能力完全解耦；离线（无任何 API key）满血运行。

算子（每算子产 0..n 条 lesson）：
① drift       近期窗口成功率 vs 全历史基线，Wilson 区间不重叠才确认；
              另含健康下限（整体成功率持续 <50%）
② contrast    上下文分片（has_code_block / has_url）成功率 vs 其余调用
③ sequence    连续失败簇检测
④ calibration 窗口成功率/基线折扣系数，折扣过低升级为置信度下调建议
⑤ budget      近期平均耗时 vs 基线倍数回归

教训 schema（机器消费 condition/recommendation，人类消费 text）：
{subject, operator, condition, finding, recommendation, text, evidence, source, confidence, expires_at}

公开 API：
- get_self_model_engine(agent_id) / reset_self_model_engine()
- should_reflect()  间隔门控（默认 600s）
- reflect(trigger)  跑五算子，教训落台账 meta_records(kind="lesson"/"reflection")，
  同时返回报告 dict
- check_tool_advisory(tool_name)  调控门数据源：活跃 avoid_tool 教训或 None
"""

import datetime
import math
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_WINDOW = 30            # 基线期最少样本参考（预算算子）
_MIN_BASELINE = 20      # 基线最少样本
_MIN_WINDOW = 10        # 近期窗口大小（事件数）
_DRIFT_DROP = 0.25      # 漂移判据：窗口成功率比基线至少低 0.25
_DISCOUNT_FLOOR = 0.6   # 校准判据：折扣 < 0.6 触发告警
_BUDGET_RATIO = 2.0     # 预算判据：近期耗时 > 基线 2 倍
_LESSON_TTL_HOURS = 24  # 教训活跃期（调控门只看活跃教训）
_REFLECT_INTERVAL = 600  # 反思间隔（秒）

_ENGINE_INSTANCES: Dict[str, "SelfModelEngine"] = {}
_ENGINE_LOCK = threading.Lock()


def _wilson_interval(successes: int, total: int, z: float = 1.96):
    """Wilson 成功率置信区间（小样本稳健）。"""
    if total == 0:
        return 0.0, 0.0, 1.0
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return p, max(0.0, center - spread), min(1.0, center + spread)


class SelfModelEngine:
    """洞察编译器：台账 → 结构化教训 → 调控建议"""

    def __init__(
        self,
        agent_id: str = "default",
        reflect_interval: int = _REFLECT_INTERVAL,
        ledger: Optional[Any] = None,
        tool_weights_provider: Optional[Any] = None,
    ):
        self._agent_id = agent_id
        self._reflect_interval = reflect_interval
        self._last_reflect_at = 0.0
        self._ledger = ledger  # 测试注入；缺省懒取单例
        self._tool_weights_provider = tool_weights_provider  # 棘轮活表接入点（可选）
        self._lock = threading.RLock()

    @property
    def tool_weights(self):
        """evolution 棘轮活表（AdaptiveToolWeights）——V3 双源收口：基线优先取活表。

        无 provider / 获取失败 / 无该工具记录时返回 None（回退台账自算基线）。"""
        if self._tool_weights_provider is not None:
            try:
                return self._tool_weights_provider()
            except Exception:
                return None
        try:
            from neurova.evolution.closed_loop import get_evolution_orchestrator

            orchestrator = get_evolution_orchestrator()
            return getattr(orchestrator, "tool_weights", None)
        except Exception:
            return None

    def _baseline_rate(self, tool: str, events: List[Dict[str, Any]]) -> Optional[float]:
        """工具基线成功率：优先棘轮活表（窗口成功率），回退台账全历史。"""
        weights = self.tool_weights
        if weights is not None:
            try:
                weight = weights.get_weight(tool)
                if weight is not None:
                    if hasattr(weights, "_windowed_success_rate"):
                        rate = weights._windowed_success_rate(weight)
                        if rate and rate > 0:
                            return float(rate)
                    total = getattr(weight, "total_calls", 0)
                    ok = getattr(weight, "success_count", 0)
                    if total and total > 0:
                        return float(ok) / float(total)
            except Exception:
                pass
        n = len(events)
        if n == 0:
            return None
        return sum(1 for e in events if e["success"]) / n

    # ────── 台账访问 ──────

    @property
    def ledger(self):
        """台账访问——恒走单例注册表，不缓存实例。

        缓存会在 reset_meta_ledger()（测试隔离/后端重启语义）后持有已关闭的
        旧连接（sqlite3.ProgrammingError: closed database），形成闭环断点。"""
        if self._ledger is not None:
            return self._ledger
        from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

        return get_meta_ledger(self._agent_id)

    # ────── 工具事件写入（tool_executor 挂点调用） ──────

    def record_tool_event(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float = 0.0,
        source: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ledger.write_event(
            agent_id=self._agent_id,
            process_type="tool",
            description=tool_name,
            duration_ms=float(duration_ms or 0.0),
            success=bool(success),
            metadata={"source": source, **(context or {})},
        )

    # ────── 门控与主入口 ──────

    def should_reflect(self) -> bool:
        return time.time() - self._last_reflect_at >= self._reflect_interval

    def reflect(self, trigger: str = "periodic") -> Dict[str, Any]:
        """跑五算子，教训落台账并随报告返回。空台账安全。"""
        with self._lock:
            events = list(reversed(self.ledger.list_events(agent_id=self._agent_id, limit=2000)))
            lessons: List[Dict[str, Any]] = []
            observations: List[str] = []

            # P1-4：per-operator 隔离——原单 try 包五算子，_op_drift 一崩
            # contrast/sequence/calibration/budget 整轮静默报废。
            for op_name, op in (
                ("drift", self._op_drift),
                ("contrast", self._op_contrast),
                ("sequence", self._op_sequence),
                ("calibration", lambda ev, ob: self._op_calibration(lessons, ev, ob)),
                ("budget", self._op_budget),
            ):
                try:
                    lessons.extend(op(events, observations))
                except Exception as e:
                    logger.debug("洞察编译器算子 %s 异常: %s", op_name, e)

            for lesson in lessons:
                lesson["source"] = "template"
                self.ledger.create_record(
                    agent_id=self._agent_id,
                    kind="lesson",
                    type="monitoring",
                    content=lesson["text"],
                    confidence=lesson["confidence"],
                    metadata=lesson,
                )

            summary = (
                f"{len(lessons)} 条洞察: " + "; ".join(l["text"] for l in lessons[:3])
                if lessons
                else "无显著认知异常"
            )
            report = {
                "trigger": trigger,
                "lessons": lessons,
                "observations": observations,
                "confidence": 0.9 if lessons else 0.5,
                "summary": summary,
            }
            self.ledger.create_record(
                agent_id=self._agent_id,
                kind="reflection",
                type="monitoring",
                content=summary,
                confidence=report["confidence"],
                metadata={"trigger": trigger, "lesson_count": len(lessons)},
            )
            self._last_reflect_at = time.time()
            return report

    # ────── 调控门数据源 ──────

    def check_tool_advisory(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """返回该工具当前活跃的 avoid_tool 教训；无则 None。"""
        # SQL 层 kind 过滤：thought 洪泛会把活跃教训挤出最新 50 条窗口
        records = self.ledger.list_records(agent_id=self._agent_id, page=1, size=50, kind="lesson")
        now = datetime.datetime.now(datetime.timezone.utc)
        for it in records["items"]:
            if it["kind"] != "lesson":
                continue
            meta = it["metadata"] or {}
            if meta.get("subject") != tool_name or meta.get("recommendation") != "avoid_tool":
                continue
            expires_at = meta.get("expires_at")
            if expires_at and expires_at < now.isoformat():
                continue
            return meta
        return None

    # ────── 算子实现 ──────

    def _tool_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [e for e in events if e.get("process_type") == "tool"]

    def _tool_groups(self, events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for e in self._tool_events(events):
            groups.setdefault(e.get("description", ""), []).append(e)
        return groups

    def _make_lesson(
        self,
        subject: str,
        operator: str,
        condition: str,
        finding: str,
        recommendation: str,
        text: str,
        evidence: Dict[str, Any],
        confidence: float,
    ) -> Dict[str, Any]:
        expires = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=_LESSON_TTL_HOURS)
        ).isoformat()
        return {
            "subject": subject,
            "operator": operator,
            "condition": condition,
            "finding": finding,
            "recommendation": recommendation,
            "text": text,
            "evidence": evidence,
            "source": "template",
            "confidence": round(confidence, 2),
            "expires_at": expires,
        }

    def _op_drift(self, events: List[Dict[str, Any]], observations: List[str]) -> List[Dict[str, Any]]:
        lessons = []
        for tool, evts in self._tool_groups(events).items():
            if len(evts) < _MIN_BASELINE + _MIN_WINDOW:
                continue
            window = evts[-_MIN_WINDOW:]
            base = evts[: -_MIN_WINDOW]
            recent, win_lo, win_hi = _wilson_interval(
                sum(1 for e in window if e["success"]), len(window)
            )
            fired = False
            if len(base) >= _MIN_BASELINE:
                base_rate = self._baseline_rate(tool, base) or (
                    sum(1 for e in base if e["success"]) / len(base)
                )
                _, base_lo, _ = _wilson_interval(
                    sum(1 for e in base if e["success"]), len(base)
                )
                if recent < base_rate - _DRIFT_DROP and win_hi < base_lo:
                    observations.append(f"tool {tool} drifted: {base_rate:.0%} -> {recent:.0%}")
                    lessons.append(
                        self._make_lesson(
                            subject=tool,
                            operator="drift",
                            condition=f"tool={tool}",
                            finding=f"success_rate {base_rate:.0%} -> {recent:.0%}",
                            recommendation="avoid_tool",
                            text=f"工具 {tool} 成功率从 {base_rate:.0%} 滑落至 {recent:.0%}（窗口 {_MIN_WINDOW}+ 次，区间不重叠），建议暂避",
                            evidence={
                                "baseline": round(base_rate, 3),
                                "window_rate": round(recent, 3),
                                "window_n": len(window),
                                "success_rate": round(recent, 3),
                            },
                            confidence=0.9,
                        )
                    )
                    fired = True
            if not fired:
                # 健康下限：整体成功率持续过低（无基线漂移也该拦）
                overall = sum(1 for e in evts if e["success"]) / len(evts)
                if overall < 0.5:
                    observations.append(f"tool {tool} persistently low: {overall:.0%}")
                    lessons.append(
                        self._make_lesson(
                            subject=tool,
                            operator="drift",
                            condition=f"tool={tool}",
                            finding=f"success_rate {overall:.0%} persistently low",
                            recommendation="avoid_tool",
                            text=f"工具 {tool} 整体成功率仅 {overall:.0%}（{len(evts)} 次），持续低于健康线，建议暂避",
                            evidence={"success_rate": round(overall, 3), "total_n": len(evts)},
                            confidence=0.9,
                        )
                    )
        return lessons

    def _op_contrast(self, events: List[Dict[str, Any]], observations: List[str]) -> List[Dict[str, Any]]:
        lessons = []
        for tool, evts in self._tool_groups(events).items():
            for feature in ("has_code_block", "has_url"):
                in_slice = [e for e in evts if (e.get("metadata") or {}).get(feature)]
                out_slice = [e for e in evts if not (e.get("metadata") or {}).get(feature)]
                if len(in_slice) < _MIN_WINDOW or len(out_slice) < _MIN_WINDOW:
                    continue
                # 分片近窗口 vs 分片外全量
                win = in_slice[-_MIN_WINDOW:]
                p_in, lo_in, hi_in = _wilson_interval(sum(1 for e in win if e["success"]), len(win))
                p_out, lo_out, hi_out = _wilson_interval(
                    sum(1 for e in out_slice if e["success"]), len(out_slice)
                )
                if p_in < p_out - _DRIFT_DROP and hi_in < lo_out:
                    observations.append(f"tool {tool} degrades when {feature}=true")
                    lessons.append(
                        self._make_lesson(
                            subject=tool,
                            operator="contrast",
                            condition=f"tool={tool} AND {feature}=true",
                            finding=f"slice {p_in:.0%} vs rest {p_out:.0%}",
                            recommendation="avoid_tool",
                            text=f"工具 {tool} 在 {feature}=true 的任务上成功率 {p_in:.0%}，显著低于其余场景 {p_out:.0%}，此类任务建议改路",
                            evidence={"slice_rate": round(p_in, 3), "rest_rate": round(p_out, 3), "slice_n": len(win)},
                            confidence=0.85,
                        )
                    )
        return lessons

    def _op_sequence(self, events: List[Dict[str, Any]], observations: List[str]) -> List[Dict[str, Any]]:
        lessons = []
        for tool, evts in self._tool_groups(events).items():
            if len(evts) < _MIN_WINDOW:
                continue
            streak, max_streak = 0, 0
            for e in evts:
                streak = streak + 1 if not e["success"] else 0
                max_streak = max(max_streak, streak)
            if max_streak >= 5:
                observations.append(f"tool {tool} had {max_streak} consecutive failures")
                lessons.append(
                    self._make_lesson(
                        subject=tool,
                        operator="sequence",
                        condition=f"tool={tool}",
                        finding=f"consecutive_failures={max_streak}",
                        recommendation="review",
                        text=f"工具 {tool} 出现 {max_streak} 连败，建议人工检查其依赖（网络/凭据/参数）",
                        evidence={"max_streak": max_streak},
                        confidence=0.8,
                    )
                )
        return lessons

    def _op_calibration(
        self, existing: List[Dict[str, Any]], events: List[Dict[str, Any]], observations: List[str]
    ) -> List[Dict[str, Any]]:
        """折扣系数 = 近期窗口成功率 / 基线；过低且尚未产出 drift 教训时补校准告警。"""
        lessons = []
        drifted = {l["subject"] for l in existing if l["operator"] == "drift"}
        for tool, evts in self._tool_groups(events).items():
            if tool in drifted or len(evts) < _MIN_BASELINE + _MIN_WINDOW:
                continue
            base = evts[: -_MIN_WINDOW]
            if len(base) < _MIN_BASELINE:
                continue
            baseline = sum(1 for e in base if e["success"]) / len(base)
            window = evts[-_MIN_WINDOW:]
            recent = sum(1 for e in window if e["success"]) / len(window)
            discount = recent / baseline if baseline > 0 else 1.0
            if discount < _DISCOUNT_FLOOR:
                observations.append(f"tool {tool} calibration discount {discount:.2f}")
                lessons.append(
                    self._make_lesson(
                        subject=tool,
                        operator="calibration",
                        condition=f"tool={tool}",
                        finding=f"discount={discount:.2f}",
                        recommendation="discount",
                        text=f"工具 {tool} 近期表现仅达基线的 {discount:.0%}，路由置信度应下调",
                        evidence={"discount": round(discount, 2), "baseline": round(baseline, 3), "window_rate": round(recent, 3)},
                        confidence=0.8,
                    )
                )
        return lessons

    def _op_budget(self, events: List[Dict[str, Any]], observations: List[str]) -> List[Dict[str, Any]]:
        lessons = []
        for tool, evts in self._tool_groups(events).items():
            if len(evts) < _MIN_BASELINE + _MIN_WINDOW:
                continue
            durations = [e.get("duration_ms") or 0.0 for e in evts if e.get("duration_ms")]
            if len(durations) < _MIN_BASELINE + _MIN_WINDOW:
                continue
            base = durations[: -_WINDOW]
            recent = durations[-_WINDOW:]
            if not base or not recent:  # 恰等于 _WINDOW 时 base 为空，避免除零
                continue
            base_avg = sum(base) / len(base)
            recent_avg = sum(recent) / len(recent)
            if base_avg > 0 and recent_avg > base_avg * _BUDGET_RATIO:
                observations.append(f"tool {tool} latency {base_avg:.0f}ms -> {recent_avg:.0f}ms")
                lessons.append(
                    self._make_lesson(
                        subject=tool,
                        operator="budget",
                        condition=f"tool={tool}",
                        finding=f"latency {base_avg:.0f}ms -> {recent_avg:.0f}ms",
                        recommendation="budget_alert",
                        text=f"工具 {tool} 平均耗时 {base_avg:.0f}ms 涨至 {recent_avg:.0f}ms（{_BUDGET_RATIO:.0f}x），建议关注",
                        evidence={"base_avg_ms": round(base_avg), "recent_avg_ms": round(recent_avg)},
                        confidence=0.75,
                    )
                )
        return lessons


def get_self_model_engine(agent_id: str = "default") -> SelfModelEngine:
    with _ENGINE_LOCK:
        if agent_id not in _ENGINE_INSTANCES:
            _ENGINE_INSTANCES[agent_id] = SelfModelEngine(agent_id=agent_id)
        return _ENGINE_INSTANCES[agent_id]


def reset_self_model_engine(agent_id: str = None) -> None:
    with _ENGINE_LOCK:
        if agent_id is None:
            _ENGINE_INSTANCES.clear()
        else:
            _ENGINE_INSTANCES.pop(agent_id, None)
