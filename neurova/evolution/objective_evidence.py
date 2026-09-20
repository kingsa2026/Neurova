"""服务端客观票据 → 三条臂的成败来源（工单 010）。

仓库里唯一真门是 `neurova/skills/creation_governance.py` 的执行证据账本：逐工具
三重核验（`success is True` + `result is not None` + 非 `is_policy_denial`）、失败
粘性 `MIN(success)`、按独立任务计数。此前三条臂（`PatternCrystallizer` /
`ExperienceFeedback` / EKB 写入）谁都不查它，成败来自模型自述、`tool_result`
聚合与关键词粗分 —— 于是「自述成功」与「服务端确证成功」在库里不可区分。

本模块是唯一的取票口，口径三句话：

1. **票据有结论即覆盖一切自述**（含 002 从 `tool_result.success` 得到的值）：
   票据比本轮回执严格，因为它连「结果为空」「策略拒绝」都算失败；
2. **查无票据 ⇒ 002 的记录聚合降为旁路证据**：条目照常入库（D1 不砍量），但
   `evidence` 为 None，落库即 `unevidenced`，检索侧（007）不得再当成功票；
3. **查不了票 ⇒ 判「票据不可读」并 WARNING**，绝不降级成「无票据」：那会把每一轮
   都标成 `unevidenced`，把「我们读不到证据」误报成「不存在证据」，比缺陷本身更糟。

结构身份的形状对齐（本票真正的雷）：写入侧 `record_tool_execution(tool, params, …)`
收的是解析后的 dict，而本轮 `tool_call` 展示记录的 `params` 有两种生产者形态 ——
`agent/loops/base.py` 给 dict，`tool_executor.py` 的肌肉记忆通道给模板串；
`normalize_steps` 只吃 dict，喂字符串直接 `ValueError: Invalid skill tool/params`。
⇒ `parse_turn_steps` 负责把两侧对齐到同一个 `structure_key`。

装配点只有一个：`post_chat_pipeline._step_record_experience`（它同时握着 agent、
本轮工具记录与 002 的三态）。票据按 agent 分库且无全局单例，唯一入口是
`SkillService(agent_id=…).creation_evidence`（与 `finish_task` 同一取法）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.evolution.rsi.gate_verdict import GateVerdict

logger = get_logger(__name__)

# 取票过程的结果（不是判据三态本身 —— 判据一律用 `GateVerdict`，见 D5）。
# `evidenced`：查到了这条结构的票（全绿或含失败，结论写在 verdict 里）；
# `absent`：查得动，库里这条结构确实没有历史票；
# `unreadable`：查不了（参数串断在解析上 / 无 agent 身份 / 证据库不可用）。
TICKET_EVIDENCED = "evidenced"
TICKET_ABSENT = "absent"
TICKET_UNREADABLE = "unreadable"

# 与写入侧 `record_tool_execution` 同口径：封装动作本身不进结构身份，
# 否则「这轮顺手封装了技能」会算出库里永不存在的身份。
_EXCLUDED_TOOLS = frozenset({"create_skill"})


def parse_turn_steps(records: Optional[List[Dict[str, Any]]]
                     ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """本轮 `tool_call` 记录 → `normalize_steps` 可吃的结构 + 读不懂的工具名清单。

    只有 `tool_call` 进步骤（`tool_result` 是回执不是执行步骤，算进去会让身份比
    写入侧多一倍）；`params` 为字符串时按 JSON 解析，解析失败或解析出非 dict
    一律进 `unreadable`，由调用方判「票据不可读」—— 这里绝不静默丢步骤，
    丢出来的半截结构可能错配到另一条序列的票据上。
    """
    steps: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    for record in records or []:
        if not isinstance(record, dict) or record.get("type") != "tool_call":
            continue
        tool_name = str(record.get("tool_name") or "").strip()
        if not tool_name or tool_name in _EXCLUDED_TOOLS:
            continue
        params = record.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params) if params.strip() else {}
            except (ValueError, TypeError):
                unreadable.append(tool_name)
                continue
        if not isinstance(params, dict):
            unreadable.append(tool_name)
            continue
        steps.append({"tool": tool_name, "params": params})
    return steps, unreadable


@dataclass(frozen=True)
class TicketEvidence:
    """一轮的成败结论 + 它的证据等级。构造请走 `resolve_ticket_evidence`。"""

    verdict: GateVerdict
    lookup: str
    record: Optional[bool] = None
    steps: Tuple[Dict[str, Any], ...] = ()

    @property
    def ticket(self) -> Optional[bool]:
        """服务端票据的结论；None = 本轮没有票据（缺席或读不出）。"""
        if self.verdict.state == GateVerdict.STATE_PASSED:
            return True
        if self.verdict.state == GateVerdict.STATE_FAILED:
            return False
        return None

    @property
    def outcome(self) -> Optional[bool]:
        """三条臂共用的成败结论：票据覆盖自述，无票据退到 002 的记录聚合。

        返回 None 只有一种情况：既没有票据也没有工具回执 —— 此时下游的关键词
        粗分只能当标签，不得进 `success_rate`（工单 010 §涉及层）。
        """
        return self.record if self.ticket is None else self.ticket

    @property
    def evidence(self) -> Optional[bool]:
        """EKB `evidence_state` 的等级：只有服务端票据算证据（D1）。"""
        return self.ticket


def _agent_id(agent: Any) -> str:
    """票据库按 agent 分目录，身份在 `agent.config.agent_id`（A-03 同源）。"""
    return str(getattr(getattr(agent, "config", None), "agent_id", "") or "").strip()


def _unreadable(reason: str, record: Optional[bool],
                steps: Tuple[Dict[str, Any], ...]) -> TicketEvidence:
    logger.warning("票据不可读：%s —— 本轮不按「无票据」处理，取证面已断", reason)
    return TicketEvidence(
        verdict=GateVerdict.unevidenced(reason=f"票据不可读：{reason}"),
        lookup=TICKET_UNREADABLE, record=record, steps=steps)


def resolve_ticket_evidence(agent: Any,
                            records: Optional[List[Dict[str, Any]]]) -> TicketEvidence:
    """查本轮工具序列的服务端票据，产出三条臂共用的成败结论。

    Args:
        agent: 本轮 Agent（只读 `config.agent_id` 定位票据库）
        records: 本轮工具展示记录（`_collect_tool_messages()` 的产物）

    票据结论 = 该结构在**独立任务**上的历史聚合（失败粘性：任一任务失败即失败）。
    本轮自身的那张票要到 `chat_pipeline.execute()` 收尾的 `finish_task` 才落库，
    晚于 post-chat，所以这里读到的是"这条序列此前被服务端确证到什么程度"——
    正是"客观"二字的含义，不是本轮回执的别名。
    """
    from neurova.agent.turn_state import resolve_tool_outcome

    record = resolve_tool_outcome(records)
    steps, unreadable = parse_turn_steps(records)
    if unreadable:
        return _unreadable(
            f"{len(unreadable)} 个工具参数无法解析为对象（{', '.join(unreadable[:3])}）",
            record, tuple(steps))
    if not steps:
        return TicketEvidence(
            verdict=GateVerdict.unevidenced(reason="本轮无工具执行结构，无从查票"),
            lookup=TICKET_ABSENT, record=record)

    agent_id = _agent_id(agent)
    if not agent_id:
        return _unreadable("agent 无身份，票据库按 agent 分库定位不到", record, tuple(steps))

    try:
        from neurova.skills.skill_service import SkillService

        results = SkillService(agent_id=agent_id).creation_evidence.task_results(steps)
    except Exception as err:  # noqa: BLE001 - 查不了票必须出声，不许当成"没票"
        return _unreadable(f"证据库查询失败: {err}", record, tuple(steps))

    if not results:
        return TicketEvidence(
            verdict=GateVerdict.unevidenced(reason="该工具序列无服务端票据"),
            lookup=TICKET_ABSENT, record=record, steps=tuple(steps))

    total = len(results)
    failures = sum(1 for ok in results.values() if not ok)
    if failures:
        verdict = GateVerdict.failed(
            reason=f"服务端票据 {failures}/{total} 个独立任务失败（失败粘性）")
    else:
        verdict = GateVerdict.passed(
            reason=f"服务端票据 {total} 个独立任务全绿", evidence={"tasks": total})
    return TicketEvidence(verdict=verdict, lookup=TICKET_EVIDENCED,
                          record=record, steps=tuple(steps))
