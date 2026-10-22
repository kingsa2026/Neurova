"""
循环门控系统

StopAction 三态：
- BYPASS: 继续（无干预）
- INTERRUPT_AND_CONTINUE: 注入提示后继续（软干预，把 gate 意见告知 LLM）
- TERMINATE: 终止循环（硬停止，循环立即结束）

StopGate ABC：check(ctx) → StopDecision。GateRunner 按优先级执行全部门控，
故障隔离（gate 异常 = BYPASS + warning），TERMINATE 优先于一切。

接入点（openai_loop）：
- 每轮工具调用后（含 skill/router 结果）：GateRunner.on_round_end(...)
- **主出口**（模型不再调用工具）：同一 GateRunner，ctx 带 `isLoopExit=True` ——
  假完成（停手且目标未达成）正是在这里才可被识别，工具轮内求值永远看不到它
- 上下文 ctx 携带轮次计数/累计 token/本轮回复签名/目标与判定结果
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class StopAction(Enum):
    BYPASS = "bypass"
    INTERRUPT_AND_CONTINUE = "interrupt_and_continue"
    TERMINATE = "terminate"


@dataclass
class StopDecision:
    action: StopAction
    reason: str = ""
    gate_name: str = ""
    # INTERRUPT_AND_CONTINUE 时注入给 LLM 的提示文本
    continuation_prompt: str = ""

    @classmethod
    def bypass(cls) -> "StopDecision":
        return cls(action=StopAction.BYPASS)


def terminationNotice(gate_name: str, reason: str) -> str:
    """循环被提前终止时给用户的交代文本（**正文是唯一可见通道**，也是落库那一份）。

    为什么必须有：这条原因此前只进 `logger.warning`，加上一份瞬时的 reasoning 文案；
    落库正文停在半截（事故读数：以「…我改用单条命令重试：」结尾），用户看到的是
    「模型自己说了一半」，而不是「被哪道判定掐了、为什么掐」。
    """
    return f"\n\n⚠️ 本轮已提前终止（{gate_name}）：{reason}"


#: 停滞判定（连续重复响应/调用）的成因——文案单源在此，两条环各写一份就是第二份定义
STAGNATION_GATE = "stagnation"
STAGNATION_REASON = "检测到连续重复的响应/调用，已停止工具循环，避免无效重试。"


def appendTerminationNotice(response: Any, gate_name: str, reason: str) -> None:
    """非流式路径就地并进 `response.content`——那条路没有事件通道可走。

    幂等：原因已在正文里就不再追加（同一份事实不得出现两遍）。
    """
    if not reason:
        return
    content = getattr(response, "content", "") or ""
    if reason in content:
        return
    response.content = content + terminationNotice(gate_name, reason)


class StopGate(ABC):
    """循环停止门控基类。"""

    name: str = "gate"
    priority: int = 100  # 数字小先执行

    @abstractmethod
    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        """判定当前循环状态。ctx 键：tool_rounds / round_reply / round_usage /
        last_tool_calls / goal（可选，goal 模式注入）。"""


def _settingsLimitDefaults() -> Dict[str, int]:
    """轮次与 token 预算两档门限的默认值：**取自**配置单源，不在此手抄第二份数字。

    此前这两个门的签名默认值写的是死数字 20 与 100000，与
    `security/agent_limits_settings.DEFAULTS` 各持一份；而 `IterationGate` 的 None 分支引用的
    `ROUND_BUDGET_FALLBACK` **只在 GoalGate 上定义**——"缺省时取什么"这条路上，一份手抄数字与
    一条会崩的分支并排放着。同族的第三把门（`DoomLoopGate`）已经改成这个形态（见
    `_settingsDoomLoopDefaults()`），本批把剩下两把接上（教义第 5 条：同一根因全命中点）。
    """
    from neurova.security.agent_limits_settings import DEFAULTS

    return {
        "max_rounds": int(DEFAULTS["max_loop_rounds"]),
        "max_tokens": int(DEFAULTS["token_budget"]),
    }


class IterationGate(StopGate):
    """轮次上限门控。缺省取配置单源（见 `_settingsLimitDefaults()`），不在此写数字。"""

    def __init__(self, max_rounds: Optional[int] = None):
        self.name = "iteration"
        self.priority = 10
        self.max_rounds = (
            int(max_rounds) if max_rounds is not None
            else _settingsLimitDefaults()["max_rounds"]
        )

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        rounds = int(ctx.get("tool_rounds") or 0)
        if rounds >= self.max_rounds:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"工具调用轮次达到上限 {self.max_rounds}",
                gate_name=self.name,
            )
        return StopDecision.bypass()


class TokenBudgetGate(StopGate):
    """累计 token 预算门控。缺省取配置单源（见 `_settingsLimitDefaults()`），不在此写数字。"""

    def __init__(self, max_tokens: Optional[int] = None):
        self.name = "token_budget"
        self.priority = 20
        self.max_tokens = (
            int(max_tokens) if max_tokens is not None
            else _settingsLimitDefaults()["max_tokens"]
        )

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        usage = ctx.get("round_usage") or {}
        total = int((usage or {}).get("total_tokens") or 0)
        if total >= self.max_tokens:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"累计 token 达到预算上限 {self.max_tokens}",
                gate_name=self.name,
            )
        return StopDecision.bypass()


#: 近似比对的长度上界。签名由 `_toolSignatures` 拼（参数已截 64 字符），这里再兜一层
#: 是给成本一个**写在上界**的理由：`check()` 每轮都要把窗口里的每条都比一遍，
#: 而 `SequenceMatcher` 是 O(n·m)——不兜的话，一条超长参数就能把每轮判定放大。
_SIGNATURE_COMPARE_CAP = 256


def _signaturesSimilar(a: str, b: str, threshold: float) -> bool:
    """两条轮次签名是否算"同一件事又做了一遍"。

    阈值 1.0 ⇒ 逐字相等（本门实装至今的语义，保留可达且是生产默认）；
    小于 1.0 ⇒ 取字符序列比值的**近似**判定，快路径先走逐字相等（多数命中不必算比值）。

    实测比值（签名由生产单源 `_toolSignatures` 拼出，不是手造的）：
    同参空转（offset 10→11）0.978、翻页（page 1→2）0.976、顺序读不同文件 0.932 / 0.843、
    不同工具同参数 0.902、多调用一轮 vs 单调用 0.489。
    所以 0.95 这一档抓到的是空转与翻页、放掉的是正常换文件与换工具——
    **翻页是这一档的已知代价**，生产默认因此留在 1.0，收紧由配置键显式决定。
    """
    if a == b:
        return True
    if threshold >= 1.0:
        return False
    if threshold <= 0.0:
        # 非法下界不解释成"全都算重复"（那等于把门控变成无条件开火），退回逐字相等；
        # 合法域由配置侧夹紧到 (0, 1]，走到这里只可能是直接构造出的坏值。
        return False
    from difflib import SequenceMatcher

    return SequenceMatcher(
        None, a[:_SIGNATURE_COMPARE_CAP], b[:_SIGNATURE_COMPARE_CAP]).ratio() >= threshold


def _settingsDoomLoopDefaults() -> Dict[str, float]:
    """死循环门三个在用阈值的默认值：**取自**配置单源，不在此手抄第二份数字。

    单源不可导入是真实故障，交给 import 出声（与 `agent/swarm.py` 同口径），
    不吞异常改成静默常量。
    """
    from neurova.security.agent_limits_settings import DEFAULTS

    return {
        "window_size": int(DEFAULTS["doom_loop_window_size"]),
        "max_interrupts": int(DEFAULTS["doom_loop_max_interrupts"]),
        "similarity_threshold": float(DEFAULTS["doom_loop_similarity_threshold"]),
    }


class DoomLoopGate(StopGate):
    """死循环门控。

    三个在用的阈值默认值**取自** `security/agent_limits_settings.DEFAULTS` 单源
    （先例 `agent/swarm.py:_settingsDefaultSubagentDepth()`）——此前它们是类字面量，
    而唯一装配点无参构造本门，于是「几次重复算死循环」这件事不受任何配置键管辖。

    `similarity_threshold` 的历史：它被收下、存进实例，而 `check()` 判的是签名**逐字
    相等**——近似比较从未实装，所以它是一格只写不读的死旋钮（台账 §6-239 点的名）。
    2026-10-16 用户裁定"实装签名相似度判定"，本轮起它**真的在管比对**：判定见
    `_signaturesSimilar`，代价与实测比值写在那里。生产默认留 1.0（等于逐字相等，
    线上开火时点一字不变），收紧到 0.95 会抓同参空转但也会把翻页判成重复。
    """

    def __init__(
        self,
        window_size: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        max_interrupts: Optional[int] = None,
    ):
        defaults = _settingsDoomLoopDefaults()
        self.name = "doom_loop"
        self.priority = 5
        self.window_size = (
            defaults["window_size"] if window_size is None else int(window_size)
        )
        self.similarity_threshold = (
            defaults["similarity_threshold"]
            if similarity_threshold is None else float(similarity_threshold)
        )
        self.max_interrupts = (
            defaults["max_interrupts"] if max_interrupts is None else int(max_interrupts)
        )
        self._window: List[str] = []
        self._interrupt_count = 0

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        signature = str(ctx.get("round_signature") or "")
        if not signature:
            return StopDecision.bypass()

        if any(_signaturesSimilar(signature, seen, self.similarity_threshold)
               for seen in self._window):
            self._interrupt_count += 1
            if self._interrupt_count >= self.max_interrupts:
                observed = self._interrupt_count  # reset 前捕获（reset 会清零）
                self.reset_session()
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"检测到死循环（重复签名出现 {observed} 次）",
                    gate_name=self.name,
                )
            return StopDecision(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                continuation_prompt=(
                    "检测到重复的工具调用模式。请更换策略，避免重复已失败的路径。"
                ),
                gate_name=self.name,
            )

        self._window.append(signature)
        if len(self._window) > self.window_size:
            self._window.pop(0)
        self._interrupt_count = 0
        return StopDecision.bypass()

    def reset_session(self) -> None:
        self._window.clear()
        self._interrupt_count = 0


class GoalGate(StopGate):
    """目标达成门控：工具轮预算（既有）+ **主出口的假完成拦截**（G2）。

    两种 ctx 语义，同一个类：

    - **工具轮**（既有）：`ctx["goal"]` + 可选 `completion_check` 回调（同步、
      低成本判据），未达成时保持现状（继续跑工具轮，不额外发声）。
    - **主出口**（`ctx["isLoopExit"]` 为真）：模型已自认完成。此时"未达成"
      就是假完成，必须发声——判据来自 `ctx["goal_verdict"]`（由 Loop 在出口处
      完成异步判定后放入，故本门控保持纯同步、无 I/O）。续跑次数由
      `ctx["goal_continuations"]` 计数，上限是 `maxContinuations`（**唯一的
      配置绑定阈值**，配置键 `goal_max_continuations`）。

    工具轮预算 `max_rounds` 由配置单源 `goal_round_budget` 提供，且只在**有目标
    声明**时才比较——没有目标时这个上限不替 IterationGate 开火（它的意义是
    "目标没达成但轮次用完了"，没有目标时该命题不存在）。

    判据不可用（`parse_ok` 为假）时一律 BYPASS：绝不因判据坏掉而阻断正常回复；
    该情形由出口处的观测面以诚实形态暴露。
    """

    #: 无配置键可用时的兜底轮次预算（fail-soft 用，**不是**默认值）。
    #: 生产装配点一律显式传 `goal_round_budget`——若这里成了一个被实际取到的值，
    #: 说明又出现了"装配不传它"的形态，上限会再次不受配置管辖。故它取的是
    #: 合法域下界而非某个"看着合适"的数：越早开火越容易被看见。
    ROUND_BUDGET_FALLBACK = 2

    def __init__(
        self,
        goal: Optional[Dict[str, Any]] = None,
        completion_check: Optional[Callable[[Dict[str, Any], Dict[str, Any]], tuple]] = None,
        max_rounds: Optional[int] = None,
        maxContinuations: int = 2,
    ):
        self.name = "goal"
        self.priority = 15
        self.goal = dict(goal or {})
        self._completion_check = completion_check
        self.max_rounds = (
            int(max_rounds) if max_rounds is not None else self.ROUND_BUDGET_FALLBACK
        )
        # 续跑预算独立于工具轮预算：一次续跑消耗一格 goal_max_continuations，
        # 不消耗工具轮预算。两者绑定**不同的配置键**，故阈值可达性为 single_source
        # （不得与 max_loop_rounds 共享尺度来源——那是 IterationGate 被机器算成
        # scaled_sparse 的成因，本门控不得再现该形态）。
        self.maxContinuations = maxContinuations

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        """两种 ctx 语义并在一个判定体内（阈值比较也在此，便于机器复算可达性）。"""
        rounds = int(ctx.get("tool_rounds") or 0)
        spent = int(ctx.get("goal_continuations") or 0)
        goal_id = (self.goal.get("id") or "goal")[:24]
        goal = dict(ctx.get("goal") or self.goal or {})

        if ctx.get("isLoopExit"):
            # 主出口求值：只对"未达成"发声，达成与判据不可用都放行。
            verdict = ctx.get("goal_verdict") or {}
            if not verdict.get("parse_ok"):
                # 判据不可用（解析失败/通道故障）→ 不拦截；观测面已在出口处记过。
                return StopDecision.bypass()
            if verdict.get("achieved"):
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"目标达成: {verdict.get('explanation') or ''}".strip(),
                    gate_name=self.name,
                )
            if spent >= self.maxContinuations:
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=(
                        f"目标未达成且续跑预算耗尽（{self.maxContinuations}）: "
                        + self._missingSummary(verdict)
                    ),
                    gate_name=self.name,
                )
            return StopDecision(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                reason=f"模型自认完成但目标未达成: {self._missingSummary(verdict)}",
                gate_name=self.name,
                continuation_prompt=self._buildReopenPrompt(goal, verdict),
            )

        if self._completion_check is not None:
            try:
                achieved, summary = self._completion_check(goal or self.goal, ctx)
            except Exception as e:
                logger.warning("goal completion check 异常（忽略）: %s", e)
                achieved, summary = False, ""
            if achieved:
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"目标达成: {summary or goal_id}",
                    gate_name=self.name,
                )

        # 轮次预算只在**本门控真的在管这个目标**时才比较：无目标声明时它不替
        # IterationGate 开火（出口求值点已按 D-4 在无目标时整体跳过，工具轮分支
        # 此前仍无条件比较 —— 于是普通对话在第 15 轮被一个与它无关的"goal 模式
        # 轮次预算耗尽"终止，IterationGate 的配置形同虚设）。
        if (goal or self.goal) and rounds >= self.max_rounds:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"goal 模式轮次预算耗尽（{self.max_rounds}）",
                gate_name=self.name,
            )
        return StopDecision.bypass()

    @staticmethod
    def _missingSummary(verdict: Dict[str, Any]) -> str:
        missing = [str(item) for item in (verdict.get("missing") or []) if str(item or "").strip()]
        return "；".join(missing) if missing else "（判定未给出缺失条目）"

    def _buildReopenPrompt(self, goal: Dict[str, Any], verdict: Dict[str, Any]) -> str:
        """续跑提示：点名目标、缺失条目与要求，使模型知道差在哪。"""
        statement = str(goal.get("statement") or "")
        lines = ["【目标未完成，请继续】"]
        if statement:
            lines.append(f"目标：{statement}")
        lines.append(f"尚未完成：{self._missingSummary(verdict)}")
        explanation = str(verdict.get("explanation") or "").strip()
        if explanation:
            lines.append(f"判定说明：{explanation}")
        lines.append("请补齐上述缺口后再给出最终答复；不要重复已经完成的步骤。")
        return "\n".join(lines)

class GateRunner:
    """门控执行器：按优先级执行全部门控，故障隔离。"""

    def __init__(self, gates: Optional[List[StopGate]] = None):
        self._gates: List[StopGate] = list(gates or [])

    def add_gate(self, gate: StopGate) -> None:
        self._gates.append(gate)
        self._gates.sort(key=lambda g: g.priority)

    @property
    def gates(self) -> List[StopGate]:
        return list(self._gates)

    def on_round_end(self, ctx: Dict[str, Any]) -> StopDecision:
        """按优先级执行全部门控；TERMINATE 立即返回，INTERRUPT 记录最后一条，
        其余 BYPASS 继续。gate 异常故障隔离为 BYPASS。全 BYPASS 时返回
        显式 bypass 决策（调用方无须判 None）。"""
        final: Optional[StopDecision] = StopDecision.bypass()
        for gate in sorted(self._gates, key=lambda g: g.priority):
            try:
                decision = gate.check(ctx)
            except Exception as e:
                logger.warning("门控 %s 异常（故障隔离为 BYPASS）: %s", gate.name, e)
                continue
            if decision.action == StopAction.TERMINATE:
                return decision  # TERMINATE 优先于一切
            if decision.action == StopAction.INTERRUPT_AND_CONTINUE:
                final = decision
        return final

    def reset_session(self) -> None:
        """重置所有门控的会话级状态（2026-09-07：轮次状态必须 per-request，
        跨请求残留会让 DoomLoopGate 把新一轮的正常调用误判为死循环）。"""
        for gate in self._gates:
            if hasattr(gate, "reset_session"):
                gate.reset_session()
