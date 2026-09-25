"""轮次级请求状态 ContextVar（审计 P0-B1：Agent 单例并发互踩修复）

Agent 是进程级单例（AppState.agents 共享池），轮次级状态原挂在实例属性
（_current_user_id/_tool_messages_list 等）上——两个用户并发对同一 agent
发消息时，请求 B 的 set_request_identity 会覆盖请求 A 的身份，A 的回复
可能带上 B 的归属；工具展示消息也会跨请求串流。

本模块把轮次级状态迁到 ContextVar：
- 值绑定在请求任务/线程上下文，并发请求天然隔离
- asyncio.to_thread 会拷贝当前 context，同步降级路径同样隔离
- Agent 的轮次级显式 API（P3-c）读写这里；旧实例属性名经 __getattr__
  透传兼容（渐进收窄）

与 identity_context.py 的分工：那里只管 JWT user_id 的跨层注入；
这里管 Agent 全部轮次级展示/归属状态。
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

# 每个变量 default 取"未设置"安全值；Agent API 层负责兜底语义
_user_input_var: ContextVar = ContextVar("neurova_turn_user_input", default=None)
_session_id_var: ContextVar = ContextVar("neurova_turn_session_id", default=None)
_user_id_var: ContextVar = ContextVar("neurova_turn_user_id", default=None)
_reasoning_var: ContextVar = ContextVar("neurova_turn_reasoning", default=None)
_tool_messages_var: ContextVar = ContextVar("neurova_turn_tool_messages", default=None)
_tool_events_var: ContextVar = ContextVar("neurova_turn_tool_events", default=None)
_skill_funnel_var: ContextVar = ContextVar("neurova_turn_skill_funnel", default=None)
_skill_view_var: ContextVar = ContextVar("neurova_turn_skill_view", default=None)
# 工单 009：本轮工具执行耗时合计（秒）。唯一写入方是执行咽喉
# （`ToolExecutor._execute_single_tool_inner` 的 finally），读方是 post-chat 的
# 经验落库。此前 `execution_time` 列在生产写侧**根本没有来源**（库实测
# nonNULL 0/103），因为咽喉算出的 elapsed 只喂了钩子、没人往轮级聚合。
#
# 存的是**可变累加器对象**而不是 float，这不是风格选择：
# `ContextVar.set()` 只改**当前任务**的上下文副本。同轮多条调用若都声明了
# 并行安全，`agent/loops/base.py` 走 `asyncio.gather`，而每个调用最终经
# `ToolCoordinator.run_with_timeout` 的 `ensure_future` 落到子任务里执行 ——
# 子任务 `set()` 的是它自己那份副本，父轮次读回 0.0（实测：单工具轮
# `[ADD] task=Task-1`、双工具轮 `[ADD] task=Task-8/Task-9`，`[POST] elapsed=0.0`）。
# 轮首绑一个对象、子任务与父轮次持有同一引用、就地累加，跨任务即一致 ——
# 与 `_tool_messages_var` 既有的"跨 task 边界共享同一列表对象"契约同形。
_tool_elapsed_var: ContextVar = ContextVar("neurova_turn_tool_elapsed", default=None)
_skills_off_var: ContextVar = ContextVar("neurova_turn_skills_off", default=False)
# 反思效力闭环（2026-09-15 P0a）：本轮被注入 prompt 的反思日志 id 痕迹。
# build_context 选中注入时写入；post_chat 落盘读它挂进 assistant metadata，
# /chat/feedback 与 Step 8.5 困惑降权据此裁决效力。
_injected_reflections_var: ContextVar = ContextVar("neurova_turn_injected_reflections", default=None)


def set_turn_injected_reflections(ids: Optional[list]) -> None:
    _injected_reflections_var.set(list(ids) if ids else None)


def get_turn_injected_reflections() -> Optional[list]:
    return _injected_reflections_var.get()

# 工单 006（经验回写通路）：本轮被注入 prompt 的 EKB 经验行 id。
# 检索侧（chat_pipeline._retrieve_ekb_experience）写入，回合末
# （post_chat._step_record_experience）按本轮客观成败回写 injected_count /
# adoption_outcome。没有这份身份集，"经验到底帮没帮上忙"就无处落账。
_injected_experiences_var: ContextVar = ContextVar("neurova_turn_injected_experiences", default=None)


class TurnElapsedAccumulator:
    """轮级工具耗时累加器：对象在轮首绑定，跨任务边界按引用共享。

    为什么必须是对象：见 `_tool_elapsed_var` 声明处的实测记录——并行工具轮里
    各调用跑在子任务中，不可变 float 的 `set()` 落不到父轮次的上下文。
    """

    __slots__ = ("seconds", "samples")

    def __init__(self) -> None:
        self.seconds = 0.0
        #: 累加被调用过几次 = "本轮到底测没测到"。0 秒是合法读数，
        #: 不能用读数真假值回答"测没测到"（票 004 同款折叠）。
        self.samples = 0


def _elapsed_accumulator() -> TurnElapsedAccumulator:
    """取当前上下文的累加器；缺席则在此绑定一个（生产路径由轮首 reset 先绑）。"""
    accumulator = _tool_elapsed_var.get()
    if not isinstance(accumulator, TurnElapsedAccumulator):
        accumulator = TurnElapsedAccumulator()
        _tool_elapsed_var.set(accumulator)
    return accumulator


def add_turn_tool_elapsed(seconds: float) -> None:
    """累加本轮工具执行耗时（执行咽喉唯一写入方；就地累加，对父轮次可见）。"""
    accumulator = _elapsed_accumulator()
    try:
        accumulator.seconds += float(seconds or 0.0)
    except (TypeError, ValueError):
        return
    accumulator.samples += 1


def get_turn_tool_elapsed() -> float:
    """本轮工具执行耗时合计（秒）；轮首未绑定或本轮没有工具执行时为 0.0。"""
    accumulator = _tool_elapsed_var.get()
    if not isinstance(accumulator, TurnElapsedAccumulator):
        return 0.0
    try:
        return float(accumulator.seconds)
    except (TypeError, ValueError):
        return 0.0


def has_turn_tool_measurement() -> bool:
    """本轮是否**测到过**工具耗时（与"测得多少"分开回答）。

    消费方落库 `execution_time` 时据此判 NULL：`None` 只该表示"本轮没有工具执行"，
    不得表示"测到的值恰好是 0.0"——后者是合法读数，折成 NULL 就不可复算了。
    """
    accumulator = _tool_elapsed_var.get()
    return isinstance(accumulator, TurnElapsedAccumulator) and accumulator.samples > 0


def reset_turn_tool_elapsed() -> None:
    """轮首换绑一个空累加器（**必须换绑新对象**，不能把已绑定的那个清零）。

    清零看起来等价，实则不同：并行轮的子任务在轮首之后才创建，若沿用同一对象，
    上一轮残留的读数会被本轮续累（本仓 `_tool_messages_var` 同款纪律）。
    """
    _tool_elapsed_var.set(TurnElapsedAccumulator())


def set_turn_injected_experiences(ids: Optional[list]) -> None:
    _injected_experiences_var.set(list(ids) if ids else [])


def get_turn_injected_experiences() -> Optional[list]:
    return _injected_experiences_var.get()

# 会话级轮次计数（2026-09-15 反思/成长链路排查根因修复）：
# 原为 ContextVar——uvicorn 每请求在独立 task 上下文执行，set() 不跨请求
# 传播 → increment 后恒 1，post_chat "每 10 轮强制反思"门控数学上永不成立。
# 轮次号的语义是"会话内第几轮"，与会话身份 ContextVar（每请求绑定）不同，
# 必须跨请求持久累积：改为模块级 {session_id: count} + RLock。
# 消费方（任务号/幂等键 f"{session}#{count}"）语义不变且并发同会话的
# 幂等键碰撞顺带根治（原每请求恒 1）。
_session_turn_counts: Dict[str, int] = {}
_turn_count_lock = threading.RLock()
_MAX_TRACKED_SESSIONS = 4096


def set_turn_identity(
    user_input: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """记录本轮请求级身份（user_id 缺省落 "default" 与原语义一致）。"""
    _user_input_var.set(user_input)
    _session_id_var.set(session_id)
    _user_id_var.set(user_id or "default")


def set_turn_user_input(value: Optional[str]) -> None:
    """单写轮次用户输入（A-04：Agent._current_user_input property 的
    setter 后端；传 None 即重置，兼容 init_conversation 的置空语义）。"""
    _user_input_var.set(value)


def get_turn_user_input() -> Optional[str]:
    return _user_input_var.get()


def get_turn_session_id() -> Optional[str]:
    return _session_id_var.get()


def get_turn_user_id() -> Optional[str]:
    return _user_id_var.get()


def set_turn_reasoning(reasoning: Optional[str]) -> None:
    _reasoning_var.set(reasoning)


def get_turn_reasoning() -> Optional[str]:
    return _reasoning_var.get()


def reset_turn_tool_messages() -> None:
    """清空本轮工具展示记录（轮次开始时调用；任务上下文内安全）。

    P0-1 技能质量漏斗：轮次账本与工具展示记录同生命周期（同一轮次起点重置、
    同一收尾消费），一并清空——两个账本永不错位，调用方无需改签名。
    """
    _tool_messages_var.set(None)
    _skill_funnel_var.set(None)
    reset_turn_tool_elapsed()
    from neurova.skills.creation_governance import begin_task
    begin_task()


def append_turn_tool_messages(records: List[Dict[str, Any]]) -> None:
    """追加工具展示记录；损坏态自愈为列表（对齐原 append_tool_messages）。"""
    current = _tool_messages_var.get()
    if current is None:
        current = []
        _tool_messages_var.set(current)
    current.extend(records or [])


def get_turn_tool_messages_snapshot() -> List[Dict[str, Any]]:
    """工具展示记录快照（副本）。"""
    current = _tool_messages_var.get()
    return list(current) if current else []


# ── 技能质量漏斗轮次账本──
# tool_executor.execute_skill_tool 每次技能派发记一条；PostChatPipeline
# 回合收尾统一按"任务完成 + 兜底完成不计功"归因后写穿 SkillService manifest。
# ContextVar 列表与 _tool_messages_var 同语义：跨 task 边界共享同一列表对象，
# 子任务记录可见于父轮次（既有轮次账本契约，非新增行为）。


def record_turn_skill_funnel(
    skill_id: str,
    applied: bool,
    ok: bool,
    pool: str = "agent",
    owner_key: str = "",
) -> None:
    """记一条本轮技能派发：applied=是否真正进入执行，ok=执行是否成功。

    Wave H-W1 三层库：pool/owner_key 记录命中的副本所在库（agent 库默认，
    与既有调用零差异），flush 据此路由回写各库账本。"""
    current = _skill_funnel_var.get()
    if not isinstance(current, list):
        current = []
        _skill_funnel_var.set(current)
    current.append(
        {
            "skill_id": skill_id,
            "applied": bool(applied),
            "ok": bool(ok),
            "pool": str(pool or "agent"),
            "owner_key": str(owner_key or ""),
        }
    )


def get_turn_skill_funnel() -> List[Dict[str, Any]]:
    """本轮技能派发账本（副本）。"""
    current = _skill_funnel_var.get()
    return list(current) if isinstance(current, list) else []


# ── 轮级技能可见视图（Wave H-W2，三层库装配快照）──────────


def set_turn_skill_view(view):
    """挂载本轮 SkillView（chat 装配步调用）；返回 token 供复位。"""
    return _skill_view_var.set(view)


def reset_turn_skill_view(token) -> None:
    _skill_view_var.reset(token)


def get_turn_skill_view():
    """本轮可见视图；未装配返回 None（消费方回退现状行为）。"""
    return _skill_view_var.get()


# ── 回合级技能库总开关（P2-4 cold/warm A/B 的执行面）──────


def set_turn_skills_off(value: bool):
    """本回合对模型隐藏技能库（schema/目录同时缺席）；返回 token 供复位。"""
    return _skills_off_var.set(bool(value))


def reset_turn_skills_off(token) -> None:
    _skills_off_var.reset(token)


def get_turn_skills_off() -> bool:
    return bool(_skills_off_var.get())


def append_turn_tool_event(event: Dict[str, Any]) -> None:
    """追加工具降级/异常事件（openai_loop 降级路径）。"""
    current = _tool_events_var.get()
    if not isinstance(current, list):
        current = []
        _tool_events_var.set(current)
    current.append(event)


def get_turn_tool_events() -> List[Dict[str, Any]]:
    """工具事件列表（无则空列表）。"""
    current = _tool_events_var.get()
    return current if isinstance(current, list) else []


def increment_turn_count() -> int:
    """会话轮次计数 +1，返回新值（按会话跨请求单调）。"""
    key = _session_id_var.get() or "default"
    with _turn_count_lock:
        if key not in _session_turn_counts and len(_session_turn_counts) >= _MAX_TRACKED_SESSIONS:
            # 插入序淘汰最旧会话（dict 保序；防长进程无界增长）
            for stale in list(_session_turn_counts)[: _MAX_TRACKED_SESSIONS // 2]:
                _session_turn_counts.pop(stale, None)
        new_value = int(_session_turn_counts.get(key, 0)) + 1
        _session_turn_counts[key] = new_value
    return new_value


def get_turn_count() -> int:
    key = _session_id_var.get() or "default"
    with _turn_count_lock:
        return int(_session_turn_counts.get(key, 0))


def clear_turn_state() -> None:
    """teardown/测试用：清空全部轮次级状态（含会话轮次计数）。"""
    for var in (
        _user_input_var,
        _session_id_var,
        _user_id_var,
        _reasoning_var,
        _tool_messages_var,
        _tool_events_var,
        _skill_funnel_var,
        _skill_view_var,
        _skills_off_var,
        _injected_reflections_var,
        _injected_experiences_var,
    ):
        if var is _skills_off_var:
            var.set(False)
        else:
            var.set(None)
    reset_turn_tool_elapsed()
    with _turn_count_lock:
        _session_turn_counts.clear()


__all__ = [
    "set_turn_identity",
    "set_turn_user_input",
    "get_turn_user_input",
    "get_turn_session_id",
    "get_turn_user_id",
    "set_turn_reasoning",
    "get_turn_reasoning",
    "reset_turn_tool_messages",
    "append_turn_tool_messages",
    "get_turn_tool_messages_snapshot",
    "record_turn_skill_funnel",
    "get_turn_skill_funnel",
    "set_turn_skill_view",
    "reset_turn_skill_view",
    "get_turn_skill_view",
    "set_turn_skills_off",
    "reset_turn_skills_off",
    "get_turn_skills_off",
    "add_turn_tool_elapsed",
    "TurnElapsedAccumulator",
    "get_turn_tool_elapsed",
    "has_turn_tool_measurement",
    "reset_turn_tool_elapsed",
    "set_turn_injected_reflections",
    "get_turn_injected_reflections",
    "append_turn_tool_event",
    "get_turn_tool_events",
    "increment_turn_count",
    "get_turn_count",
    "clear_turn_state",
]
