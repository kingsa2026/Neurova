"""窗口切分的工具组边界（reference_ad 上下文工程 P2-7）。

纯函数模块，零 I/O：只回答"切分点落在哪里不会拆散同组展示单元"。
同组单元＝一条带非空 `tool_calls` 的 assistant 消息与其后**连续**的
`role == "tool"` 结果消息（OpenAI 语义：tool 结果必须能找到声明它的调用，
前端也按这一形态成组展示）。预算切分若落在组中间，kept 侧出现孤儿
tool 结果、dropped 侧出现悬空 tool_calls。

职责边界（单一事实源）：本模块只做"边界不拆组"的切点判定；配对修复
（孤儿转注记、悬空补合成结果）仍归 `neurova.context.recovery.repair_tool_turns`，
孤儿判定同源 `declaredToolCallIds`，此处不复制其逻辑、不造第二套口径。
组边界判定全仓仅此一处定义，编排器 / context_pool 不得另写。
"""

import typing


def _opensToolGroup(msg: typing.Any) -> bool:
    """assistant 消息且携带非空 tool_calls——工具组的起始边界。"""
    return (
        isinstance(msg, dict)
        and msg.get("role") == "assistant"
        and bool(msg.get("tool_calls"))
    )


def _isToolResult(msg: typing.Any) -> bool:
    """role == "tool" 的结果消息。"""
    return isinstance(msg, dict) and msg.get("role") == "tool"


def groupBoundaries(msgs: typing.List[dict]) -> typing.List[int]:
    """返回合法切分点下标集合（升序，取值 0..len(msgs)）。

    下标与 `split_window_by_budget` 的 ``kept_count`` 同口径：边界 ``b``
    表示"保留尾部 ``b`` 条、折叠头部 ``len(msgs)-b`` 条"。对每组
    ``[a, g]``（``a`` 为带 tool_calls 的 assistant 下标，``g`` 为其最后一条
    连续 tool 结果下标），把组拆到切分两侧的 ``b`` 都不合法——非法区间为
    ``[len(msgs)-g, len(msgs)-a-1]``；无 tool_calls 的普通消息之间任意位置
    皆可切。结果必含 ``0`` 与 ``len(msgs)``。

    畸形输入容忍：``msgs`` 为 None 按空序列处理；None / 非 dict 元素不构成
    组成员（其后的 tool 结果视为无主孤儿，交由 recovery 处理），不抛异常。
    """
    seq = msgs if isinstance(msgs, (list, tuple)) else []
    n = len(seq)
    illegal: typing.Set[int] = set()
    i = 0
    while i < n:
        if _opensToolGroup(seq[i]):
            j = i + 1
            while j < n and _isToolResult(seq[j]):
                j += 1
            # 组 [i, j-1]：组内切分对应的 kept 区间 [n-(j-1), n-i-1] 全部非法
            for b in range(n - (j - 1), n - i):
                illegal.add(b)
            i = j
        else:
            i += 1
    return [b for b in range(n + 1) if b not in illegal]


def snapBoundaryToGroup(msgs: typing.List[dict], index: int) -> int:
    """把候选切点下标吸附到 ≤index 的最大合法边界（向头部方向找）。

    对预算切分给出的保留条数，返回不拆任何工具组的最大不超标保留条数：
    吸附**只减不增**——宁多折叠以保组完整，绝不把保留量放大过原预算选择；
    无工具组时原值返回。向头部方向找不到合法切点（含 ``index`` 非法/为负）
    返回 ``0``（全部折叠，组必然完整）。
    """
    legal = set(groupBoundaries(msgs))
    try:
        b = int(index)
    except (TypeError, ValueError):
        return 0
    if b < 0:
        return 0
    while b > 0 and b not in legal:
        b -= 1
    return b if b in legal else 0
