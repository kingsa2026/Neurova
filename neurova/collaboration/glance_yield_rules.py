"""
Neurova GLANCE_YIELD_RULES - Multi-Agent Coordination Protocol
七层防御体系核心协议，定义 agent 协作的基本原则

"""

import asyncio
import json
import os
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import time

from neurova.core.logger import get_logger
from neurova.core.app_settings import get_advanced_settings
from neurova.collaboration import triage_feedback
from neurova.collaboration.triage_rules import evaluateTriage
from neurova.collaboration.neu_judge import NeuJudge

logger = get_logger(__name__)

# ── Layer 6 分诊门三档开关（计划 §7 治理开关）────────────────────────────
# env 显式值最优先（off/shadow/enforce，非法值警告后按 off），
# 其次设置面板键 advanced.triage_gate_enabled（字符串，默认 off）。
TRIAGE_GATE_ENV = "NEUROVA_TRIAGE_GATE_MODE"
TRIAGE_GATE_SETTING_KEY = "triage_gate_enabled"
TRIAGE_GATE_MODES = ("off", "shadow", "enforce")


def triageGateMode() -> str:
    """解析分诊门当前档位：env > 设置键 > 兜底 off（沿 acceptance_gate 的回落惯例）。"""
    raw = (os.environ.get(TRIAGE_GATE_ENV) or "").strip().lower()
    if raw:
        if raw in TRIAGE_GATE_MODES:
            return raw
        logger.warning(
            "%s=%r 非法（合法值 %s），按 off 处理", TRIAGE_GATE_ENV, raw, "/".join(TRIAGE_GATE_MODES)
        )
        return "off"
    try:
        value = get_advanced_settings().get(TRIAGE_GATE_SETTING_KEY, "off")
    except Exception:  # noqa: BLE001 - 设置不可读回落默认关（不因设置故障改变闸行为）
        return "off"
    mode = str(value or "off").strip().lower()
    if mode not in TRIAGE_GATE_MODES:
        logger.warning(
            "设置 %s=%r 非法（合法值 %s），按 off 处理",
            TRIAGE_GATE_SETTING_KEY, value, "/".join(TRIAGE_GATE_MODES),
        )
        return "off"
    return mode

class YieldReason(str, Enum):
    """Yield decision reasons"""
    CONCURRENT_AGENT = "concurrent_agent"
    DETERMINISTIC_SPACING = "deterministic_spacing"
    ADAPTIVE_PACER = "adaptive_pacer"
    COLLISION_DETECTED = "collision_detected"
    VERBATIM_DUP = "verbatim-dup"
    TRIAGE_GATE = "triage_gate"
    COST_THRESHOLD = "cost_threshold"
    MODEL_PIN_VIOLATION = "model_pin_violation"

@dataclass
class YieldDecision:
    """Yield decision result"""
    should_yield: bool
    reason: Optional[YieldReason] = None
    wait_time_seconds: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_yield": self.should_yield,
            "reason": self.reason.value if self.reason else None,
            "wait_time_seconds": self.wait_time_seconds,
            "details": self.details,
        }

@dataclass
class AgentModelPin:
    """Agent model pin configuration"""
    agent_id: str
    model_name: str
    pinned_at: datetime = field(default_factory=datetime.utcnow)
    reason: Optional[str] = None

class GlanceYieldChecker:
    """
    GLANCE_YIELD_RULES implementation

    Seven-layer defense system for multi-agent coordination:

    Layer 1: Per-agent model pin (固定模型版本)
    Layer 2: Big-brain concurrency cap (限制并发大模型调用)
    Layer 3: Deterministic spawn spacing (最小间隔避免 thundering herd)
      3a: Triage concurrency cap (小模型分类器并发限制)
      3b: AdaptivePacer (速率限制自适应调整)
      3c: Wake debounce & coalesce (去抖窗口)
    Layer 4: Rate-limit cooldown (单次限流冷却)
    Layer 5: Freshness preflight (提交前检查新消息)
      5b: Atomic verbatim-dup detection (重复内容检测)
      5c: Stall pipeline (静默 conversation 唤醒)
    Layer 6: Small-brain triage gate (小模型过滤无意义对话)
    Layer 7: Standing prompt + yield rules (协作原则)

    Key Principles:
    - Simple over complex
    - Observable over opaque
    - Conservative defaults
    - Easy opt-out when needed
    """

    # Configuration defaults
    DEFAULT_MAX_CONCURRENT_AGENTS = 6
    DEFAULT_MIN_SPAWN_INTERVAL_MS = 500  # 0.5 seconds
    DEFAULT_TRIAGE_CONCURRENT_LIMIT = 8
    DEFAULT_WAKE_DEBOUNCE_MS = 2500  # 2.5 seconds
    DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60
    # 占用槽位的租约上限：崩在半路、没走到 record_operation_complete 的操作
    # 不能永久占位（同一形态在 `core/agent_run_store` 用 lease + 启动 reconcile 兜）
    ACTIVE_OP_LEASE_SECONDS = 600.0

    def __init__(self):
        # Layer 1: Model pins
        self._agent_pins: Dict[str, AgentModelPin] = {}

        # Layer 2: Concurrency tracking
        # model_name -> {agent_id: (operation_hash, startedAt)}
        # 计数由这张表**派生**，不再单独维护一个 int——占位与释放都只有一条路径，
        # 才不会"查询即占用"（旧形态：判一次加一次，唯一减点在 unregister）。
        self._activeOps: Dict[str, Dict[str, tuple]] = {}

        # Layer 3: Spacing and pacing
        self._last_spawn_time: Dict[str, float] = {}  # agent_id -> timestamp
        self._pacing_stats: Dict[str, Dict[str, Any]] = {}  # model -> stats

        # Layer 4: Rate limit state
        self._rate_limited_agents: Dict[str, float] = {}  # agent_id -> cooldown_end

        # Layer 5: Seen cursors (integrated with SeenBoundary)
        self._seen_sequences: Dict[str, int] = {}  # (agent, convo) -> seq

        # Layer 6: 分诊门（规则 R0-R4 + 灰区 NeuJudge 级联，窗口每轮现算，
        # 无跨轮缓存——旧的 triage 结果缓存字典随 SB-4 退役）。
        self._triage_model: Optional[NeuJudge] = None
        self._triage_model_failed = False

        # 分域阈值目录（Jeff catalogue 启发）：agent_id → 阈值覆盖，懒加载，
        # 文件缺失/损坏按无目录处理（全部回落默认阈值）。
        self._judge_catalogue: Optional[Dict[str, Any]] = None
        self._judge_catalogue_loaded = False

        # Statistics
        self._stats = {
            'total_checks': 0,
            'yields': 0,
            'proceeds': 0,
            # Layer 6 分诊门计数（get_stats 透出）
            'triage_checks': 0,
            'triage_rule_skips': 0,
            'triage_model_skips': 0,
            'triage_shadow_would_skip': 0,
            'triage_model_unavailable': 0,
            'triage_events_unavailable': 0,
            'triage_gate_errors': 0,
            # SB-5 回流：skip 样本落盘失败次数（遥测旁路，不影响闸决策）
            'triage_feedback_errors': 0,
        }

        logger.info("GlanceYieldChecker initialized")

    def register_agent(
        self,
        agent_id: str,
        model_name: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Layer 1: Register agent with model pin

        Ensures consistent model behavior per agent
        """
        pin = AgentModelPin(
            agent_id=agent_id,
            model_name=model_name,
            reason=reason,
        )

        self._agent_pins[agent_id] = pin

        logger.info(f"Registered agent {agent_id} with model {model_name}")

    def _occupiedModel(self, agent_id: str) -> str:
        """该 agent 占的是哪个模型桶；没有 pin 时落 "unknown"（与 complete 侧同口径）。"""
        pin = self._agent_pins.get(agent_id)
        return pin.model_name if pin else "unknown"

    def _reapExpiredOps(self) -> int:
        """回收超过租约的占位。返回回收条数。"""
        deadline = time.time() - self.ACTIVE_OP_LEASE_SECONDS
        reaped = 0
        for model_name in list(self._activeOps):
            slots = self._activeOps[model_name]
            for agent_id, (_op, startedAt) in list(slots.items()):
                if startedAt < deadline:
                    slots.pop(agent_id, None)
                    reaped += 1
            if not slots:
                self._activeOps.pop(model_name, None)
        if reaped:
            logger.warning("让位并发槽按租约回收 %d 个占位（未走到 complete 的操作）", reaped)
        return reaped

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister agent —— 同时释放它占着的并发槽。"""
        if agent_id in self._agent_pins:
            for slots in self._activeOps.values():
                slots.pop(agent_id, None)
            self._activeOps = {m: s for m, s in self._activeOps.items() if s}

            del self._agent_pins[agent_id]

    def check_yield_rules(
        self,
        agent_id: str,
        model_name: str,
        proposed_operations: List[str],
        conversation_id: Optional[str] = None,
        adoptModelSwitch: bool = False,
        userInput: str = "",
    ) -> YieldDecision:
        """
        Main entry point: Check all yield rules

        `adoptModelSwitch` 只由**客户端显式选型**的入口传 True（控制台、
        `/v1/chat*`）：那里的模型变化是用户的决定，不是 agent 漂移。渠道/自动
        入口保持 False——它们未来若开始传显式模型，仍按漂移判。

        Returns decision on whether agent should proceed or yield
        """
        # Update stats
        self._stats['total_checks'] += 1
        # Layer 1: Model pin validation
        decision = self._check_model_pin(agent_id, model_name, adoptModelSwitch)
        if decision.should_yield:
            return decision

        # Layer 2: Concurrency check
        decision = self._check_concurrency_limit(agent_id, model_name)
        if decision.should_yield:
            return decision

        # Layer 3: Spawn spacing
        decision = self._check_spawn_spacing(agent_id)
        if decision.should_yield:
            return decision

        # Layer 3b: Adaptive pacing
        decision = self._check_adaptive_pacer(agent_id, model_name)
        if decision.should_yield:
            return decision

        # Layer 4: Rate limit
        decision = self._check_rate_limit(agent_id)
        if decision.should_yield:
            return decision

        # Layer 5: Freshness preflight
        if conversation_id:
            decision = self._check_freshness_preflight(agent_id, conversation_id)
            if decision.should_yield:
                return decision

        # Layer 6: Triage gate
        if conversation_id:
            decision = self._check_triage_gate(conversation_id, userInput, agent_id)
            if decision.should_yield:
                return decision

        # All checks passed - proceed
        self._stats['proceeds'] += 1
        return YieldDecision(should_yield=False)

    def _check_model_pin(
        self, agent_id: str, model_name: str, adoptModelSwitch: bool = False
    ) -> YieldDecision:
        """Layer 1: Validate model pin

        `adoptModelSwitch=True` 时，模型变化＝用户改选，重设 pin 后放行；否则
        维持"等也不会自愈"的漂移判定。这个开关只能由入口层按 `entry` 派生，
        不能让闸自己猜——闸分不清"用户换模型"和"agent 私自漂移"。
        """
        if not (model_name or "").strip():
            # 未归因的回合**不建立 pin，也不判漂移**。默认路径就这样：前端没选
            # 模型时不传 model（`ChatPage.vue` 的 `selectedModel.value || undefined`），
            # 把空串钉成 pin 后，用户一选手动模型就撞上 MODEL_PIN_VIOLATION——而那
            # 是闸里唯一"等多久都不会自愈"的原因，第一次判定就直接挂起。
            return YieldDecision(should_yield=False)

        if agent_id not in self._agent_pins:
            # First time - set pin
            self.register_agent(agent_id, model_name)
            return YieldDecision(should_yield=False)

        pinned_model = self._agent_pins[agent_id].model_name
        if model_name != pinned_model:
            if adoptModelSwitch:
                # 客户端选型入口：用户改选就是新事实。不重设 pin 的话，下一轮
                # 同一模型仍会撞旧 pin；而 pin 同时是并发槽的归因键，跟着改才
                # 能占对桶（完成侧按本回合模型释放，见 record_operation_complete）。
                logger.info(
                    "Model pin adopted (client-selected): agent=%s, %s -> %s",
                    agent_id, pinned_model, model_name,
                )
                self.register_agent(agent_id, model_name)
                return YieldDecision(should_yield=False)

            logger.warning(
                f"Model pin violation: agent={agent_id}, "
                f"pinned={pinned_model}, requested={model_name}"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.MODEL_PIN_VIOLATION,
                details={
                    "pinned_model": pinned_model,
                    "requested_model": model_name,
                },
            )

        return YieldDecision(should_yield=False)

    def _check_concurrency_limit(
        self,
        agent_id: str,
        model_name: str,
    ) -> YieldDecision:
        """Layer 2: Check big-brain concurrency cap

        **纯读**：查询不改变占用。占用只由 `record_operation_start` 发生、
        只由 `record_operation_complete`/`unregister_agent`/租约到期释放。
        旧形态在这里 `+1`（"temporarily increment"），而那个临时值从来没有被减回去
        ——同一个 Agent 问 6 次就把该模型额度占满，之后所有同模型 Agent 恒让位。
        """
        self._reapExpiredOps()
        current_count = len(self._activeOps.get(model_name, {}))

        if current_count < self.DEFAULT_MAX_CONCURRENT_AGENTS:
            return YieldDecision(should_yield=False)

        # Limit exceeded - second and subsequent agents must yield
        logger.warning(
            f"Concurrency limit exceeded: "
            f"model={model_name}, current={current_count}, max={self.DEFAULT_MAX_CONCURRENT_AGENTS}"
        )

        return YieldDecision(
            should_yield=True,
            reason=YieldReason.CONCURRENT_AGENT,
            wait_time_seconds=1.0,
            details={
                "model": model_name,
                "current_count": current_count,
                "max_allowed": self.DEFAULT_MAX_CONCURRENT_AGENTS,
            },
        )

    def _check_spawn_spacing(self, agent_id: str) -> YieldDecision:
        """Layer 3: Check deterministic spawn spacing"""
        last_time = self._last_spawn_time.get(agent_id, 0)
        elapsed_ms = (time.time() - last_time) * 1000

        if elapsed_ms < self.DEFAULT_MIN_SPAWN_INTERVAL_MS:
            wait_ms = self.DEFAULT_MIN_SPAWN_INTERVAL_MS - elapsed_ms
            wait_seconds = wait_ms / 1000

            logger.debug(
                f"Spawn spacing violated: "
                f"agent={agent_id}, elapsed={elapsed_ms:.0f}ms, "
                f"required={self.DEFAULT_MIN_SPAWN_INTERVAL_MS}ms"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.DETERMINISTIC_SPACING,
                wait_time_seconds=wait_seconds,
                details={
                    "elapsed_ms": elapsed_ms,
                    "required_ms": self.DEFAULT_MIN_SPAWN_INTERVAL_MS,
                },
            )

        return YieldDecision(should_yield=False)

    def _check_adaptive_pacer(self, agent_id: str, model_name: str) -> YieldDecision:
        """Layer 3b: Adaptive pacing based on error rate"""
        stats = self._pacing_stats.get(model_name, {"success_rate": 1.0})
        success_rate = stats.get("success_rate", 1.0)

        # Exponential backoff if error rate high
        if success_rate < 0.5:
            base_wait = 2.0
            backoff_factor = (1.0 - success_rate) * 2
            wait_seconds = base_wait * backoff_factor

            logger.warning(
                f"Adaptive pacer triggered: "
                f"model={model_name}, success_rate={success_rate:.1%}"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.ADAPTIVE_PACER,
                wait_time_seconds=wait_seconds,
                details={"success_rate": success_rate},
            )

        return YieldDecision(should_yield=False)

    def _check_rate_limit(self, agent_id: str) -> YieldDecision:
        """Layer 4: Check rate limit cooldown"""
        cooldown_end = self._rate_limited_agents.get(agent_id, 0)

        if time.time() < cooldown_end:
            remaining = cooldown_end - time.time()

            logger.info(
                f"Rate limit active: "
                f"agent={agent_id}, remaining={remaining:.0f}s"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.COLLISION_DETECTED,
                wait_time_seconds=remaining,
            )

        # Clear cooldown
        if agent_id in self._rate_limited_agents:
            del self._rate_limited_agents[agent_id]

        return YieldDecision(should_yield=False)

    def _check_freshness_preflight(
        self,
        agent_id: str,
        conversation_id: str,
    ) -> YieldDecision:
        """Layer 5: Freshness preflight check"""
        # This integrates with SeenBoundary
        # For now, simplified version

        key = f"{agent_id}:{conversation_id}"
        current_seq = int(time.time() * 1000)
        last_seq = self._seen_sequences.get(key, 0)

        if current_seq == last_seq:
            # No new activity
            return YieldDecision(should_yield=False)

        # Update sequence
        self._seen_sequences[key] = current_seq

        return YieldDecision(should_yield=False)

    def _check_triage_gate(self, conversation_id: str, user_input: str = "",
                           agent_id: str = "") -> YieldDecision:
        """Layer 6: Small-brain triage gate（SB-4 接线：规则守高置信区 + 模型守灰区）。

        计划出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md §3/§6/§7。
        - off：恒放行（与旧缓存空壳行为一致，零副作用）；
        - shadow：恒放行，仅计 `triage_shadow_would_skip`；
        - enforce：规则命中（R2/R3）或模型 p<SKIP_P 才拦截，其余保守放行。

        整条链保持同步；事件源/规则/模型的意外异常一律按「调用方降级」契约
        转放行 + 计数 + warning 留痕（不静默）。
        """
        mode = triageGateMode()
        if mode == "off":
            return YieldDecision(should_yield=False)

        self._stats['triage_checks'] += 1
        try:
            return self._triageGateDecision(conversation_id, user_input, mode, agent_id)
        except Exception:  # noqa: BLE001 - 闸不吞异常≠不降级：计数与日志即留痕
            self._stats['triage_gate_errors'] += 1
            logger.warning(
                "分诊门判定意外失败，按放行降级：conversation=%s", conversation_id, exc_info=True
            )
            return YieldDecision(should_yield=False)

    def _triageGateDecision(
        self, conversation_id: str, user_input: str, mode: str, agent_id: str = ""
    ) -> YieldDecision:
        """分诊门判定本体（mode 必为 shadow/enforce）。"""
        # 进料口：会话事件单一事实源（SessionSyncManager），同步内存快照
        try:
            from neurova.sync.session_sync_manager import get_session_sync_manager

            manager = get_session_sync_manager()
            if manager.get_session(conversation_id) is None:
                self._stats['triage_events_unavailable'] += 1
                logger.debug("分诊门无会话窗口，放行：conversation=%s", conversation_id)
                return YieldDecision(should_yield=False)
            events = manager.get_messages(conversation_id, 50)
        except Exception:  # noqa: BLE001 - 取不到窗口按放行 + 计数（不吞成拦截）
            self._stats['triage_events_unavailable'] += 1
            logger.warning("分诊门取会话窗口失败，按放行降级：conversation=%s", conversation_id, exc_info=True)
            return YieldDecision(should_yield=False)

        verdict = evaluateTriage(events or [], user_input)
        features = dict(verdict.features)

        if verdict.action == "skip":
            if mode == "shadow":
                self._stats['triage_shadow_would_skip'] += 1
                self._recordSkipFeedback(conversation_id, "rules", verdict.reason,
                                         None, features, mode, events)
                return YieldDecision(should_yield=False)
            self._stats['triage_rule_skips'] += 1
            self._recordSkipFeedback(conversation_id, "rules", verdict.reason,
                                     None, features, mode, events)
            logger.info(
                "分诊门规则拦截：conversation=%s rule=%s", conversation_id, verdict.reason
            )
            return YieldDecision(
                should_yield=True,
                reason=YieldReason.TRIAGE_GATE,
                details={"source": "rules", "rule": verdict.reason, "features": features},
            )

        # 规则高置信放行（R0/R1）直接过；灰色区（default_allow）问 NeuJudge
        if verdict.reason != "default_allow":
            return YieldDecision(should_yield=False)

        model = self._triageModel()
        if model is None:
            # 模型产物不可用：诚实降级为仅规则（规则层本身仍是闸）
            return YieldDecision(should_yield=False)

        p = model.score(features)
        detailed = model.decideDetailed(p, self._agentThresholds(agent_id))
        decision = detailed["action"]
        if decision == "skip":
            if mode == "shadow":
                self._stats['triage_shadow_would_skip'] += 1
                self._recordSkipFeedback(conversation_id, "model", verdict.reason,
                                         p, features, mode, events)
                return YieldDecision(should_yield=False)
            self._stats['triage_model_skips'] += 1
            self._recordSkipFeedback(conversation_id, "model", verdict.reason,
                                     p, features, mode, events)
            logger.info(
                "分诊门模型拦截：conversation=%s p=%.4f", conversation_id, p
            )
            return YieldDecision(
                should_yield=True,
                reason=YieldReason.TRIAGE_GATE,
                details={"source": "model", "p": p, "features": features,
                         "judge": detailed},
            )
        # allow / abstain → 保守放行（弃权带与原门"拿不准→响应"同构）
        return YieldDecision(should_yield=False)

    def _loadJudgeCatalogue(self) -> Dict[str, Any]:
        """懒加载分域阈值目录（Jeff catalogue 启发）：agent_id → 阈值覆盖。

        文件缺失/损坏按无目录处理（全部回落产物默认阈值）；进程内只读一次。
        """
        if self._judge_catalogue_loaded:
            return self._judge_catalogue or {}
        self._judge_catalogue_loaded = True
        try:
            path = Path(__file__).resolve().parent / "neu_judge_catalogue.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
                    self._judge_catalogue = payload["profiles"]
        except Exception:  # noqa: BLE001 - 目录不可用降级为无覆盖
            self._judge_catalogue = {}
        return self._judge_catalogue or {}

    def _agentThresholds(self, agent_id: str) -> Optional[Dict[str, float]]:
        """按 agent_id 取目录中的阈值覆盖；无目录/无档案返回 None（用默认）。"""
        profiles = self._loadJudgeCatalogue()
        profile = profiles.get(agent_id) if agent_id else None
        if not isinstance(profile, dict):
            return None
        thresholds = profile.get("thresholds")
        return thresholds if isinstance(thresholds, dict) and thresholds else None

    def _recordSkipFeedback(
        self,
        conversationId: str,
        source: str,
        rule: str,
        p: Optional[float],
        features: Dict[str, Any],
        mode: str,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """SB-5 回流：skip 样本落盘（遥测旁路，失败计 triage_feedback_errors）。

        出处：计划 §5.3 人工标注回流。shadow/enforce 两档都记（mode 字段区分），
        失败只计数不外抛——回流断了闸照常工作。events 作为窗口快照随样本落盘
        （golden case 与 admin 复核用）。
        """
        try:
            recorded = triage_feedback.recordSkipSample(
                conversationId=conversationId, source=source, rule=rule,
                p=p, features=features, mode=mode, window=events,
            )
        except Exception:  # noqa: BLE001 - 回流失败绝不影响闸决策
            recorded = False
        if not recorded:
            self._stats['triage_feedback_errors'] += 1

    def _triageModel(self) -> Optional[NeuJudge]:
        """懒加载 NeuJudge 默认产物并缓存在 checker 上；失败置标记只警告一次。"""
        if self._triage_model_failed:
            return None
        if self._triage_model is None:
            try:
                self._triage_model = NeuJudge.loadDefault()
            except Exception:  # noqa: BLE001 - 产物缺失/损坏：点名降级，不 fail-open 到无闸
                self._triage_model_failed = True
                self._stats['triage_model_unavailable'] += 1
                logger.warning("NeuJudge 默认产物不可用，分诊门降级为仅规则模式", exc_info=True)
                return None
        return self._triage_model

    def record_operation_start(self, agent_id: str, operation_hash: str) -> None:
        """开工：记间距时间戳，并占一个并发槽（同一 agent 幂等——只占一格）。"""
        self._last_spawn_time[agent_id] = time.time()
        pin = self._agent_pins.get(agent_id)
        if pin is None:
            # 归因不到模型就**不占槽**：硬塞进一个 "unknown" 桶，会让毫不相干的
            # 调用方共用同一份额度——那正是本批在修的"挤进同一个桶"形态。
            logger.warning(
                "record_operation_start 无 pin，无法归因到模型，本次不占并发槽：agent=%s",
                agent_id,
            )
            return
        model_name = pin.model_name
        slots = self._activeOps.setdefault(model_name, {})
        if agent_id not in slots:
            slots[agent_id] = (operation_hash, time.time())
        else:
            existingOp, startedAt = slots[agent_id]
            slots[agent_id] = (existingOp, startedAt)

    def record_operation_complete(
        self,
        agent_id: str,
        operation_hash: str,
        success: bool,
        modelName: Optional[str] = None,
    ) -> None:
        """Record operation completion and update pacing stats

        `modelName` 是**本回合实际使用的模型**（闸的结论自带）。换 pin 之后不能再按
        `_occupiedModel()` 读当前 pin：同一 agent 两个标签页各用一个模型时，后开工的
        回合会把前一个模型的槽释放错，旧槽要等 600s 租约才回收。
        """
        model_name = modelName or self._occupiedModel(agent_id)
        if model_name in self._activeOps:
            self._activeOps[model_name].pop(agent_id, None)
            if not self._activeOps[model_name]:
                self._activeOps.pop(model_name, None)

        stats = self._pacing_stats.setdefault(model_name, {
            "total_ops": 0,
            "successful_ops": 0,
        })

        stats["total_ops"] += 1
        if success:
            stats["successful_ops"] += 1

        # Calculate success rate
        stats["success_rate"] = (
            stats["successful_ops"] / stats["total_ops"]
            if stats["total_ops"] > 0
            else 1.0
        )

        logger.debug(
            f"Operation completed: "
            f"agent={agent_id}, model={model_name}, "
            f"success_rate={stats['success_rate']:.1%}"
        )

    def trigger_rate_limit(self, agent_id: str) -> None:
        """Trigger rate limit cooldown for agent"""
        self._rate_limited_agents[agent_id] = (
            time.time() + self.DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        )

        logger.warning(f"Rate limit triggered for agent: {agent_id}")

    def get_stats(self) -> Dict[str, Any]:
        """Get checker statistics"""
        self._reapExpiredOps()
        return {
            "registered_agents": len(self._agent_pins),
            "active_per_model": {m: len(s) for m, s in self._activeOps.items()},
            "pacing_stats": dict(self._pacing_stats),
            **self._stats,
        }

# Global instance management
_glance_checker_instance: Optional[GlanceYieldChecker] = None
_glance_checker_lock = asyncio.Lock()

async def get_glance_yield_checker() -> GlanceYieldChecker:
    """Get global GlanceYieldChecker instance"""
    global _glance_checker_instance

    if _glance_checker_instance is None:
        async with _glance_checker_lock:
            if _glance_checker_instance is None:
                _glance_checker_instance = GlanceYieldChecker()

    return _glance_checker_instance

async def reset_glance_yield_checker() -> None:
    """Reset GlanceYieldChecker instance (for testing)"""
    global _glance_checker_instance
    _glance_checker_instance = None
