# -*- coding: utf-8 -*-
"""手工取证脚本的**结论派生**单点（§6-471）。

## 为什么收这一处

`tests/manual/context_persistence_baseline_90.py` 曾把 2026-09-21 的结论写死在报告字符串里，
而同一份报告里紧挨着的就是当天实算的读数。2026-11-02 实跑出来的形态是自相矛盾：

    模拟重启后的新实例：常驻 0 条；recall_evicted = 20（归档活不过重启）
    结论：写入进程的归档在新进程里取不到 → A1 当前为红     ← 上一行刚印出 recall_evicted 20
    无会话池（session_id=None）召回条数 = 0，且无 filter_by_scope 闸口 → 房间内容可见

三份结论今天全部为假，而读数全部为真。写死结论的那半没有通道复核——**取证档不进 CI，
散文里的结论就没人读**，于是它比缺陷本身更坏：读的人拿它当今天的事实源（本仓已因此差点把
「生产复刻了第二份作用域规则」登记成真）。

本模块只承担一件事：**结论形态必须由读数派生**，且解析不出来时点名「不可用」，
绝不沿用上一次运行留下的话。判据落 `tests/unit/context/test_baselineForensicsVerdictsDeriveFromReadings.py`。

同族的正例形态是 assert（`context_ledger_gc_90.py:117`、`fold_layer_index_t11b_90.py:174`）——
断言消息只在失败时出现，天然不会与读数冲突；本模块服务于"必须打印结论"的容量基线档。
"""
import re

__all__ = ["tailCount", "a1Verdict", "visibilityVerdict"]


def tailCount(text, marker):
    """从读数行里取 `marker` 后面那个整数；取不到返回 None（不猜）。"""
    match = re.search(re.escape(marker) + r"\s+(\d+)", text or "")
    return int(match.group(1)) if match else None


def a1Verdict(readerRecall):
    """A1（跨进程能否取回归档）只能由 reader 子件的召回条数派生。"""
    if readerRecall is None:
        return "本行不可用：reader 子件读数里取不到 recall_evicted 的数（输出形状变了，不猜）"
    return "A1 绿（新进程取得到写入进程的归档）" if readerRecall else "A1 红（新进程取不到）"


def visibilityVerdict(hits):
    """房间内容可见与否，同样只由召回条数派生。"""
    return "不可见" if not hits else "仍可见（闸口失效）"
