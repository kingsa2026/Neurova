# -*- coding: utf-8 -*-
"""P2-7 同组单元聚合截断：窗口预算切点不拆散 assistant(tool_calls)+tool 组。

判据来源：reference_ad 上下文专项 teardown 轴3 / P2-7 卡。

契约：
1. groupBoundaries：合法切分点集合（下标与 kept_count 同口径——"保留尾部 b
   条"）。带非空 tool_calls 的 assistant 与其后连续 role=tool 结果段是同组
   单元，任何把组内消息拆到切分两侧的 b 都不合法。
2. snapBoundaryToGroup：候选切点向头部方向吸附到 ≤index 的最大合法边界；
   吸附只减不增 kept（宁多折叠以保组完整），找不到回 0。
3. split_window_by_budget 接入组边界：超预算且切点落在组中间时，切点吸附到
   组边界，kept 内 tool 结果都能找到声明调用的 assistant；无工具组的窗口
   切点与旧算法逐字节一致（向后兼容判据）。
"""
from neurova.context.window_compactor import WindowTokenMeter, split_window_by_budget
from neurova.context.window_partition import groupBoundaries, snapBoundaryToGroup


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistantToolCalls(cid: str, content: str = "调用工具") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": "ls", "arguments": "{}"}}
        ],
    }


def _toolResult(cid: str, content: str = "工具结果") -> dict:
    return {"role": "tool", "tool_call_id": cid, "content": content}


def _lenMeter() -> WindowTokenMeter:
    """len() 计量：token 即字符数 + 协议开销，断点完全确定可推理。"""
    return WindowTokenMeter(estimator=lambda text: len(text or ""))


def _oldSplit(msgs, budget_tokens, keep_min_messages, target_ratio, meter):
    """改前算法原样复算（测试内对照，判据 4 的"旧算法"基准）。"""
    msgs = list(msgs or [])
    if not msgs:
        return [], []
    if meter.total(msgs) <= budget_tokens:
        return [], msgs
    target = max(budget_tokens * target_ratio, 1.0)
    acc = 0.0
    kept_count = 0
    for m in reversed(msgs):
        t = meter.one(m)
        if kept_count >= keep_min_messages and acc + t > target:
            break
        acc += t
        kept_count += 1
    kept_count = min(kept_count, len(msgs))
    kept = msgs[len(msgs) - kept_count:] if kept_count else []
    dropped = msgs[: len(msgs) - kept_count] if kept_count < len(msgs) else []
    return dropped, kept


def testGroupBoundariesKeepsToolGroupIntact():
    """assistant(tool_calls)+tool 段内部点不是合法边界；组前后皆可切。"""
    msgs = [
        _user("问题"),
        _assistantToolCalls("c1"),
        _toolResult("c1"),
        _user("追问"),
    ]
    # n=4，组 [1,2]：kept=2（只留 [tool, 追问]）把 tool 结果与其 assistant 拆开 → 非法
    assert groupBoundaries(msgs) == [0, 1, 3, 4]

    # 多条连续 tool 结果的组：组内任意切分都非法
    msgs2 = [
        _user("问题"),
        _assistantToolCalls("c1"),
        _toolResult("c1", "结果一"),
        _toolResult("c1", "结果二"),
        _user("追问"),
    ]
    # n=5，组 [1,3]：kept=2/3 都会把组拆开
    assert groupBoundaries(msgs2) == [0, 1, 4, 5]


def testSnapBoundaryMovesCutBeforeGroup():
    """候选切点落在组中间时向头部吸附到组边界；只减不增。"""
    msgs = [
        _user("问题"),
        _assistantToolCalls("c1"),
        _toolResult("c1"),
        _user("追问"),
    ]
    # 2 = 只留 [tool, 追问]：拆组 → 吸附到 1（整组落折叠区）
    assert snapBoundaryToGroup(msgs, 2) == 1
    # 合法切点原样返回
    assert snapBoundaryToGroup(msgs, 3) == 3
    assert snapBoundaryToGroup(msgs, 4) == 4
    # 超界夹取到 len(msgs)；负值/0 回 0
    assert snapBoundaryToGroup(msgs, 99) == 4
    assert snapBoundaryToGroup(msgs, 0) == 0
    assert snapBoundaryToGroup(msgs, -7) == 0

    # 组贴序列尾部：要么整组保留要么整组折叠，不能只留结果
    tail_msgs = [_user("问题"), _assistantToolCalls("c2"), _toolResult("c2")]
    assert snapBoundaryToGroup(tail_msgs, 1) == 0
    assert snapBoundaryToGroup(tail_msgs, 2) == 2


def testSplitWindowByBudgetSnapsToGroupBoundary():
    """超预算窗口：旧算法切点落在组中间（kept 出现孤儿 tool 结果），
    新逻辑把切点吸附到组边界，kept 内 tool 结果都能找到声明调用的 assistant。"""
    meter = _lenMeter()
    u_head = _user("测" * 200)
    a1 = _assistantToolCalls("c1", "调用一")
    t1 = _toolResult("c1", "结果一")
    a2 = _assistantToolCalls("c2", "调用二")
    t2 = _toolResult("c2", "结果二")
    u_tail = _user("尾部消息")
    msgs = [u_head, a1, t1, a2, t2, u_tail]

    # 预算取"旧算法从尾部恰好装到 t1 为止"：target=budget/2=Σone(尾部4条)，
    # 循环在 a1 处 break → 旧 kept=[t1,a2,t2,u_tail]，t1 成孤儿（a1 被折叠）。
    s = meter.one(u_tail) + meter.one(t2) + meter.one(a2) + meter.one(t1)
    budget = 2 * s
    keep_min = 1

    dropped, kept = split_window_by_budget(
        msgs, budget, keep_min_messages=keep_min, meter=meter
    )
    # 吸附后 kept 收缩（4 → 3）：被拆散的组 [a1,t1] 整体落折叠区
    assert kept == [a2, t2, u_tail]
    assert dropped == [u_head, a1, t1]
    # kept 内配对完整：每条 tool 结果的 tool_call_id 都能在 kept 的
    # assistant.tool_calls 中找到声明
    declared = {c["id"] for m in kept for c in (m.get("tool_calls") or [])}
    for m in kept:
        if m.get("role") == "tool":
            assert m.get("tool_call_id") in declared, m

    # 旧算法（测试内复算）确实切在组中间：kept 首条是孤儿 tool 结果
    old_dropped, old_kept = _oldSplit(msgs, budget, keep_min, 0.5, meter)
    assert [m.get("role") for m in old_kept] == ["tool", "assistant", "tool", "user"]
    assert old_kept[0].get("tool_call_id") == "c1"
    assert old_dropped[-1] is a1
    assert len(old_kept) > len(kept), "吸附只减不增 kept"


def testSplitWindowUnchangedWithoutTools():
    """无 tool 消息：切点与旧算法（测试内复算 token 累计）逐条一致。"""
    meter = _lenMeter()
    msgs = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}条：" + "测" * 80}
        for i in range(10)
    ]
    budget = 600
    dropped, kept = split_window_by_budget(
        msgs, budget, keep_min_messages=3, meter=meter
    )
    old_dropped, old_kept = _oldSplit(msgs, budget, 3, 0.5, meter)
    assert (dropped, kept) == (old_dropped, old_kept)
    assert dropped and kept, "确有切分发生，判据非空转"

    # 未超预算：零行为变化
    assert split_window_by_budget(msgs, 10 ** 9, meter=meter) == ([], msgs)


def testGroupBoundaryToleratesMalformed():
    """None 元素/缺字段/非 dict 元素不抛异常；畸形项不构成组成员。"""
    msgs = [
        None,
        {"role": "assistant", "tool_calls": [{"id": "c1"}]},  # 缺 content
        "不是字典",
        42,
        {"role": "tool", "tool_call_id": "c1"},
        {"tool_calls": [{"id": "c2"}]},  # 缺 role
        None,
    ]
    bounds = groupBoundaries(msgs)  # 不抛
    assert bounds[0] == 0 and bounds[-1] == len(msgs)
    assert snapBoundaryToGroup(msgs, len(msgs)) == len(msgs)
    assert snapBoundaryToGroup(msgs, None) == 0
    # 空序列 / None 整体输入
    assert groupBoundaries(None) == [0]
    assert groupBoundaries([]) == [0]
    assert snapBoundaryToGroup([], 5) == 0
