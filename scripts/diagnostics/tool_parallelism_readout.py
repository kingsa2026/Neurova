#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具并行收益的取数入口（M3 前置，方案 §10.1「先量后说」）。

## 为什么要有这条命令

方案 §10.1 把"先量后说"写成 M3 的**硬性前置**：从既有观测面拉两条读数，
多工具批次占比低于 ~5% 就据此**放弃** M3 及之后的一切。在那之前，提交说明里
不得出现任何加速百分比。这要求取数本身是**一条可重跑的命令**，而不是"某次
会话里顺手 print 过一遍"——后者无法被复核，也无法在数据变了之后重算。

## 两条读数

1. **批次形态分布**（`neurova_tool_batch_shapes_total`，按调度路径分档）：
   `single_call`（本轮只有一个调用）/ `multi_serial`（多调用、零成组批 ——
   M3 的目标客户）/ `multi_parallel`（已成组）。**两个占比口径并列输出**：
   §10.1 原文口径（多工具轮 / 全部轮）与参考口径（成组批 / 多调用轮）——
   它们回答两个不同的问题，同一份数据可以给出相反结论（见 `batchShapeVerdict`
   的 docstring），故不许折叠成一个 `share` 字段。
2. **工具耗时分布**（`neurova_tool_execution_seconds` 直方图）：逐桶计数、
   逐工具 `_sum`/`_count`，给出均值与"落在各桶区间"的分布。方案 §10.1 要求
   的耗时分布就是这一份，不另造一套账。

**`path` 分档必须读，不能合并**：`AnthropicLoop.handle_tool_calls` 在批里含
`computer` 时逐条转发 `super().handle_tool_calls([单条])`，那些批恒为
`single_call`；其余批整批交基类。并进总数就会把这条残留盲区读成"M3 没有
收益"，据此砍方案是拿失明当结论。

**读数要区分四件事，其中三种"没结论"的处置各不相同**：

- `sparse` / `worthwhile` 是**判据结论**（否证成立 / 未成立）；
- `no_data` 是**判据输入没采到**（无法判定，不构成否证）—— 把它读成"没收益"
  就是拿失明当结论；
- `no_data` 自身还分三种成因，**处置各不相同**：`absent_in_this_scrape`（本份抓取里
  没有这一族的家族头 ⇒ 先**核对抓取**，确为完整抓取时才指向**部署**）、
  `zero_samples`（仪表在位、只是还没有样本 ⇒ 可达且已就位，该**等真实轮次**）与
  `schema_drift`（抓取里有本词表不认识的形态标签 ⇒ **分母残缺**，该动**词表**）。
  三者原先同形，读者无从分辨该修哪里（见 `instrumentPresence` / `shapeCause`）。

**词表是单一事实源，不在本脚本里另写一份**：`SHAPE_LABELS` 派生自写入侧
（`core/tool_capability.ToolBatchShape`）。两边各写一遍字面量，漂移时的表现不是
报错而是**静默丢样本**——实测 8 轮里 5 轮不认识，读数在残缺分母上给出 `sparse`。

输入不可用（文件读不到 / 内容不是 Prometheus 文本）另走一条路：非零退出码点名
收场，不抛解释器栈（真抓取被反代吞成 HTML 正是这条路径的真实形态）。

用法：
    python scripts/diagnostics/tool_parallelism_readout.py            # 人类可读
    python scripts/diagnostics/tool_parallelism_readout.py --json     # 机器可读
    python scripts/diagnostics/tool_parallelism_readout.py --metrics-file FILE
        # 离线复算：喂一份 /metrics 抓取文本（不连后端也能核对读数算法）
        # 输入不可用时退出码 2（无法判定），不是 0 也不是判定结论
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHAPE_METRIC = "neurova_tool_batch_shapes_total"
DURATION_METRIC = "neurova_tool_execution_seconds"

#: 形态词汇**派生**自写入侧的单一事实源（`core/tool_capability.ToolBatchShape`）：
#: 读数侧自己再写一份字面量就会漂移，漂移的后果不是报错而是**静默丢样本**——
#: 不认识的标签被跳过，读数照着一个不完整的分母给出 `sparse`（拿失明当结论）。
from neurova.core.tool_capability import ToolBatchShape  # noqa: E402

SHAPE_LABELS = tuple(shape.value for shape in ToolBatchShape)

#: 形态仪表在**抓取文本里的家族名**：`prometheus_client` 暴露 counter 时族名去
#: `_total` 后缀（`neurova/api/endpoints/analytics.py` 的两处读侧正是栽在这里）。
#: 由 `SHAPE_METRIC` **派生**而非另写一份字面量：两处各写一遍就会漂移。
SHAPE_FAMILY = SHAPE_METRIC.removesuffix("_total")

#: 方案 §10.1 的否证阈值：多调用轮里成组批的占比低于它就说明 M3 收益不成立。
#: 写在脚本里而非散在说明里，是为了让"低于阈值就放弃"这件事**可机器判定**。
SPARSE_SHARE = 0.05

#: 逐工具「值不值得为它成组等待」的门槛（秒）。M3 的收益按工具分布**极不均匀**：
#: 真机读数（Issue #271）里 `file_read` 34ms 落门外、`memory_search` 991ms 冷 /
#: 83ms 热落在边界上。这个量级在仓内另有同源目标可援引：检索路径的延迟目标是
#: `< 200ms`（`docs/01-architecture/20-retrieval-context-injection.md` §10）。
#:
#: 它是**读数门槛**，不是放行门禁：结论只回答"这个工具的常态耗时值不值得等"，
#: 要不要把某个工具声明为可并行，仍由逐工具论证（依据行）决定——把读数当门禁
#: 用，就是拿一个通用数字替掉本该逐条给出的依据。
WORTH_WAITING_BUDGET_S = 0.2


class ReadoutInputError(RuntimeError):
    """取数输入不可用（读不到 / 不是 Prometheus 文本）。

    为什么要有这个类型、而不是让它以 `ValueError` 栈冒出去：取数命令的读者是
    **做决策的人**。实测（Issue #271 取数）：把反代吞成 HTML 的抓取体喂进来，
    脚本抛的是 `ValueError: invalid metric name:<!DOCTYPE html>...` —— 读者分不清
    "判定结果是 sparse"与"你喂的不是 /metrics 文本"。这两种情形必须分得开，
    且"输入不可用"是**无法判定**，不是**判定为否证**。
    """


def _metricText(metrics_file: str) -> str:
    """取数源：优先显式文件（离线复算），否则生成当前进程注册表的文本。

    两条"输入不可用"的路径（文件读不到 / 内容不是 Prometheus 文本）在这里
    一并收口——它们是同一个事实的两半，分别在两处兜底就是两处可独立漂移的口径。
    """
    if not metrics_file:
        # 先**装配**仪表再导出 —— `/metrics` 端点就是这么做的
        # （`api/app.py::_register_metrics_endpoint` 第一行 `get_metrics()`）。
        # 少了这一步，`generate_metrics_text()` 会导出一个**空注册表**，
        # 于是"本进程还没装配仪表"被读成"这份部署里没有仪表"，把处置指向
        # 无辜的部署 —— 判据必须关于部署，不能关于本进程有没有先热身。
        from neurova.core.metrics import generate_metrics_text, get_metrics

        get_metrics()
        return generate_metrics_text()

    path = Path(metrics_file)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ReadoutInputError(f"读不到 metrics 文件 {path}：{exc}") from exc
    return raw


def _rejectNonPrometheusText(text: str, source: str) -> None:
    """内容不是 Prometheus 文本时点名原因。

    判据是**解析器本身**（`text_string_to_metric_families`）而不是我们自己写的
    形态嗅探：第二份"什么算 Prometheus 文本"的判定就是第二份事实源，两边一漂移，
    真正的抓取体反而会被拒。这里只把解析器抛的错**归类并点名**，不改它的判定。
    """
    from prometheus_client.parser import text_string_to_metric_families

    try:
        list(text_string_to_metric_families(text))
    except ValueError as exc:
        head = " ".join(text.strip().split())[:120]
        raise ReadoutInputError(
            f"{source} 不是 Prometheus 文本（解析器点名：{exc}）；开头是 {head!r}。"
            "常见成因：抓取被反代/网关吞成了 HTML —— 该地址上没有 /metrics 观测面。"
        ) from exc


def _families(text: str):
    from prometheus_client.parser import text_string_to_metric_families

    return list(text_string_to_metric_families(text))


def instrumentPresence(text: str) -> Dict[str, Any]:
    """两条判据仪表**在不在这份抓取里**——"在位"与"有样本"是两件事。

    `no_data` 的成因由此分开，因为两种成因的**处置相反**：

    - `absent_in_this_scrape`（本份抓取里家族头都不在）：在这份文本上判据**没有
      输入** —— 先核对抓取本身（子集抓取 / 被反代截断 / 抓错服务都长这样）；
      确为完整抓取时才成立"该部署里的 `core/metrics.py` 早于埋点提交
      （实测镜像 revision `d5210625` 对 `tool_batch_shapes` 零命中），再跑多少轮、
      再等多久都不会有样本"这一**可核实**结论，处置是重新部署当前版本。
    - `zero_samples`（家族头在、样本数为 0）：判据**可达且已就位** —— 仪表是
      进程级的，重启清空计数器，样本随真实工具轮到达。要动的是**等真实轮次**
      （或去看那套部署为什么一轮工具都没跑）。

    两件事在改前的输出里同形（都只印一个 `no_data`），读者无从分辨该修部署
    还是该等样本。判据落在**导出文本本身**：家族头在不在是导出器的事实，
    不是我们从别处猜的意图。**也正因为判据只关于文本，成因名与处置都不许越过
    文本去断言部署**：同一份"本份抓取里没有这一族"的读数，既可能是部署早于埋点
    提交，也可能只是抓了子集 / 被反代截断 / 抓错了服务。故成因落
    `absent_in_this_scrape`，部署分支保留为**可核实的条件**（见
    `_CAUSE_DISPOSITION`），由读者拿抓取本身去证。
    """
    presence: Dict[str, Any] = {
        "shape_family": {"name": SHAPE_FAMILY, "present": False, "sample_total": 0},
        "duration_family": {"name": DURATION_METRIC, "present": False, "sample_total": 0},
    }
    for family in _families(text):
        if family.name in (SHAPE_METRIC, SHAPE_FAMILY):
            presence["shape_family"]["present"] = True
            presence["shape_family"]["sample_total"] += len(family.samples)
        elif family.name == DURATION_METRIC:
            presence["duration_family"]["present"] = True
            presence["duration_family"]["sample_total"] += len(family.samples)
    return presence


def segmentCause(instrument: Dict[str, Any], family_key: str) -> str:
    """某一段读数的成因分型（**唯一一处**）：仪表缺席，还是仪表在位但零样本。

    按**该段自己的仪表**判，不借用别段的结论：形态段与耗时段在观测面上是两支
    独立的仪表（`tool_execution_seconds` 的历史比形态表早得多，实测那份旧部署
    里它在位、形态表缺席）—— 把形态段的成因抄给耗时段，就是拿另一支仪表的
    事实冒充这一支，读者会照着错的处置去动。

    返回值的作用域**只是本份抓取**：`absent_in_this_scrape` 回答"这份文本里没有"，
    不回答"那套部署里没有"（后者要读者拿完整抓取去证，见 `_CAUSE_DISPOSITION`）。
    """
    if not instrument[family_key]["present"]:
        return "absent_in_this_scrape"
    return "zero_samples"


def shapeCause(instrument: Dict[str, Any], unrecognized: Dict[str, int]) -> str:
    """形态段成因：**词汇漂移优先于零样本**（两者的处置方向相反）。

    漂移时仪表在位、样本也有——它们只是不是这份词表的名字。判成 `zero_samples`
    会把读者指向"等真实轮次"，而那一等永远等不来；正确处置是**对齐词表**
    （写侧新增了形态，或这份抓取来自另一个版本的部署）。
    """
    if unrecognized:
        return "schema_drift"
    return segmentCause(instrument, "shape_family")


#: 成因 → 人类可读的一句话（处置不同，故不许折叠成一句"无数据"）。
_CAUSE_DISPOSITION = {
    "absent_in_this_scrape": (
        "本份抓取里**没有**这一族的仪表（连家族头都不在）—— 先**核对抓取**本身："
        "是否只抓了一个族、是否被反代/网关截断成子集、是否抓对了服务；"
        "确为**完整抓取**时成因才落到部署（实测镜像 revision `d5210625` 早于埋点提交，"
        "等多久都不会有样本），处置是**重新部署当前版本**"
    ),
    "zero_samples": (
        "判据仪表在位、样本数为 0 —— 判据**可达且已就位**，"
        "样本随真实工具轮到达，重跑本命令即出结论"
    ),
    "schema_drift": (
        "抓取里有**不认识**的形态标签 —— 分母不完整，结论无从谈起；"
        "该动的是**词表**（写侧新增了形态，或这份抓取来自另一个版本的部署），不是等样本"
    ),
}


def _emptyReadoutLine(cause: str, segment: str) -> str:
    """零样本两行（形态段 / 耗时段）的成因标注：两段共用一套处置词汇。"""
    disposition = _CAUSE_DISPOSITION.get(cause, "成因未判定")
    return f"  （无样本，成因={cause or '?'}：{disposition}{segment}）"


def parseBatchShapes(text: str) -> Dict[str, Dict[str, int]]:
    """`{path: {shape: 轮数}}`——按调度路径分档，不合并。

    匹配落在**样本名**上（`neurova_tool_batch_shapes_total`）：`prometheus_client`
    暴露 counter 时族名是去 `_total` 后缀的归一形态，按族名比会恒不命中——
    `neurova/api/endpoints/analytics.py` 的两处读侧正是栽在这里（本片一并根修）。
    """
    out: Dict[str, Dict[str, int]] = {}
    for path, shape, count in _shapeSamples(text):
        bucket = out.setdefault(path, {})
        bucket[shape] = bucket.get(shape, 0) + count
    return out


def unrecognizedShapeLabels(text: str) -> Dict[str, int]:
    """抓取里出现、但**不在写入侧词表里**的形态标签及其轮数。

    这些样本此前的处置是"跳过"——于是它们从分母里消失，而读数照样给出一个有把握
    的结论：实测 3 个 `single_call` + 5 个 `multi_pipeline`，读数报
    `多工具轮 / 全部轮 = 0` ⇒ `sparse`（"该放弃 M3"）。真相是"8 轮里有 5 轮形态不明"，
    正确处置是**先对齐词表**（写侧加了新形态、或抓的是别的版本的部署）。

    非空即意味着分母不完整 ⇒ `batchShapeVerdict` 不得出结论（见其成因分型）。
    """
    drift: Dict[str, int] = {}
    for _, shape, count in _shapeSamples(text):
        if shape in SHAPE_LABELS:
            continue
        drift[shape] = drift.get(shape, 0) + count
    return drift


def _shapeSamples(text: str):
    """形态表的原始三元组 `(path, shape, 轮数)`——取数只在这里落一次。"""
    for family in _families(text):
        for sample in family.samples:
            if sample.name != SHAPE_METRIC:
                continue
            yield (
                str(sample.labels.get("path") or "?"),
                str(sample.labels.get("shape") or "?"),
                int(sample.value),
            )


def percentileBracket(bounds: List[float], cumulative: Dict[float, int], count: int, quantile: float):
    """分位所在桶的**夹逼区间** `(lower, upper]`（秒）；无样本时 `None`。

    为什么是夹逼而不是一个点：直方图只报"落在哪个桶"，真值在桶内何处是**未知**的。
    `neurova/api/endpoints/analytics.py` 的 p95 取"分位所在桶的上限、无插值"，
    同一诚实语义；本函数额外给出下界，是因为逐工具判据要问的是"整段区间在门槛的
    哪一侧"——只给上界会把跨门槛的情形（`(0.1s, 0.25s]`）硬判成一侧。

    `lower` 的取值：首个累计过半的桶界**之前**的那个桶界（没有更小桶时是 0）；
    `upper` 就是那个桶界本身。
    """
    if count <= 0:
        return None
    target = quantile * count
    ordered = sorted(b for b in bounds if b != float("inf"))
    for index, bound in enumerate(ordered):
        if cumulative.get(bound, 0) >= target:
            lower = 0.0 if index == 0 else ordered[index - 1]
            return (lower, bound)
    # 分位落在 `+Inf` 桶（样本比最大有限桶还慢）：下界是最大有限桶界，上界未知。
    if ordered:
        return (ordered[-1], float("inf"))
    return None


def parallelWorthiness(bracket, slow_bound: Optional[float]) -> Dict[str, Any]:
    """逐工具判据：**P50 与门槛比**；冷路径另档，不进这一判断。

    三态而非二态（`True` / `False` / `None`）：桶界把 P50 夹在 `(lower, upper]` 里，
    区间**整段**在门槛之上判 `True`、整段在门槛之下判 `False`、**跨过门槛则 `None`**
    （"边界"）。给跨门槛的区间硬挑一侧，就是拿仪表分辨率装出来的确定性。

    冷路径（`slow_share`）**不参与**：它是部署/超时该管的事，不是并行收益该管的事。
    混进来就会把"这个部署有冷启动样本"读成"这个工具常态很慢"，进而给一个常态只要
    几十毫秒的工具发并行资格——那正是真机读数里 `memory_search` 的双峰形态。
    """
    verdict = None
    if bracket is not None:
        lower, upper = bracket
        if lower >= WORTH_WAITING_BUDGET_S:
            verdict = True
        elif upper <= WORTH_WAITING_BUDGET_S:
            verdict = False
    return {"worth_waiting": verdict, "slow_bound_s": slow_bound}


def parseToolDurations(text: str) -> List[Dict[str, Any]]:
    """逐工具耗时：均值来自 `_sum`/`_count`；另给**区间**分布。

    分布必须由累计桶**逐段相减**得出：Prometheus 的 `_bucket` 是「≤ le」的累计
    计数，直接把累计值当分布读会得到"每个桶都一样大"的假象（实测：3 个样本时
    所有桶都读 3）。方案 §10.1 要的是"耗时落在哪一段"，累计值回答不了。
    """
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    cumulative: Dict[str, Dict[float, int]] = {}
    for family in _families(text):
        if family.name != DURATION_METRIC or family.type != "histogram":
            continue
        for sample in family.samples:
            name = str(sample.labels.get("tool_name") or "?")
            if sample.name.endswith("_sum"):
                sums[name] = sums.get(name, 0.0) + float(sample.value)
            elif sample.name.endswith("_count"):
                counts[name] = counts.get(name, 0) + int(sample.value)
            elif sample.name.endswith("_bucket"):
                le = str(sample.labels.get("le"))
                bound = float("inf") if le == "+Inf" else float(le)
                cumulative.setdefault(name, {})[bound] = int(sample.value)

    rows: List[Dict[str, Any]] = []
    for name in sorted(sums):
        count = counts.get(name, 0)
        bounds = sorted(cumulative.get(name, {}))
        segments: Dict[str, int] = {}
        previous = 0.0
        for index, bound in enumerate(bounds):
            running = cumulative[name][bound]
            # 区间的**上沿**就是本桶的按名边界：`(prev, bound]`，不是下一个桶。
            # 拿 `previous` 当上沿会造出"1.0s 桶里的样本记成 >0.1s"这种错位标签——
            # 读数一旦贴错段，耗时分布就不可复算。
            if bound == float("inf"):
                label = ">%gs" % bounds[index - 1] if index else ">0s"
            else:
                lower = 0.0 if index == 0 else bounds[index - 1]
                label = "<=%gs" % bound if index == 0 else "%gs<..<=%gs" % (lower, bound)
            segments[label] = max(0, running - int(previous))
            previous = running
        bracket = percentileBracket(bounds, cumulative.get(name, {}), count, 0.5)
        # 冷路径的**保守下界**：只数"确定比门槛慢"的样本。桶界中点附近的样本
        # （`(0.1s, 0.25s]` 里跨 200ms 的那些）在读数上无从分辨，不算进来——
        # 少报一个已知下界，好过把不确定的样本算成确定很慢。
        slow_bound = next((b for b in bounds if b != float("inf") and b >= WORTH_WAITING_BUDGET_S), None)
        slow_share = (
            round((count - cumulative[name].get(slow_bound, 0)) / count, 4)
            if (slow_bound is not None and count)
            else None
        )
        row: Dict[str, Any] = {
            "name": name,
            "count": count,
            "avg_ms": round(sums[name] / count * 1000, 2) if count else 0.0,
            "p50_lower_ms": round(bracket[0] * 1000, 2) if bracket else None,
            "p50_upper_ms": (
                round(bracket[1] * 1000, 2) if (bracket and bracket[1] != float("inf")) else None
            ),
            "slow_share": slow_share,
            "segments_s": {k: v for k, v in segments.items() if v},
        }
        row.update(parallelWorthiness(bracket, slow_bound))
        rows.append(row)
    return rows


def batchShapeVerdict(
    shapes: Dict[str, Dict[str, int]],
    unrecognized: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """按 §10.1 给结论，**两个口径各自正名、并列输出**。

    这两个口径回答的是**两个不同的问题**，且会在同一份数据上给出**相反**的
    结论——实测（21 个单调用轮 + 1 个成组轮）：

    - `multi_tool_round_share` = 多工具轮 / **全部轮** = 1/22 ≈ 0.045 ⇒ 落在
      §10.1 的否证条件里（"多工具批次本身就极少，M3 没有客户"）；
    - `grouped_parallel_share` = 成组批 / **多调用轮** = 1.0 ⇒ 看起来值得做。

    两者都对，但只有前者是 §10.1 的原文口径（"若量出**多工具批次的占比**低于
    ~5%…"）——故 `verdict` 落前者，后者作为"已有多调用轮里成组吃的比例"并列呈现。
    折叠成一个 `share` 字段会让同一份数据既能读出 `worthwhile` 又能读出 `sparse`，
    而读法取决于实现者当时选了哪个分母（本片改前正是这样：名字是原文口径、
    算法是后者）。
    """
    perPath: Dict[str, Any] = {}
    grouped = 0
    total_multi = 0
    total_rounds = 0
    singleLabel, serialLabel, parallelLabel = SHAPE_LABELS
    for path, counts in shapes.items():
        single_call = int(counts.get(singleLabel, 0))
        multi_serial = int(counts.get(serialLabel, 0))
        multi_parallel = int(counts.get(parallelLabel, 0))
        sub = multi_serial + multi_parallel
        # 逐路径的占比与顶层同一处置：词表漂移时分母同样残缺，故一并回退成 None。
        # 顶层说"读不了"、逐路径印 0.0%，读者会拿后者当结论（那正是本片要防的形态）。
        driftFree = not unrecognized
        perPath[path] = {
            singleLabel: single_call,
            serialLabel: multi_serial,
            parallelLabel: multi_parallel,
            # 本路径内：成组批 / 多调用轮（"多调用轮里成组吃到了多少"）
            "grouped_share": round(multi_parallel / sub, 4) if (sub and driftFree) else None,
            # 本路径内：多工具轮 / 全部轮（§10.1 口径，逐路径给）
            "multi_tool_round_share": round(sub / (sub + single_call), 4)
            if ((sub + single_call) and driftFree)
            else None,
        }
        grouped += multi_parallel
        total_multi += sub
        total_rounds += sub + single_call

    grouped_parallel_share = round(grouped / total_multi, 4) if total_multi else None

    # 词汇漂移时**分母不完整**：不认识标签的样本已经从分子分母里消失了。
    # 此时任何占比都是"在残缺样本上算出来的数"，而读者会把它当成结论
    # （实测 8 轮里 5 轮不认识，读数报占比 0 且结论 sparse）。故先判漂移，
    # 占比回退成 None：宁可说"这一份读不了"，也不给一个不完整的数字。
    drifted = bool(unrecognized)
    multi_tool_round_share = (
        None if (drifted or not total_rounds) else round(total_multi / total_rounds, 4)
    )
    if drifted:
        grouped_parallel_share = None

    if drifted:
        verdict = "no_data"
    elif multi_tool_round_share is None:
        verdict = "no_data"
    elif multi_tool_round_share < SPARSE_SHARE:
        verdict = "sparse"
    else:
        verdict = "worthwhile"
    return {
        "per_path": perPath,
        "multi_tool_round_share": multi_tool_round_share,
        "grouped_parallel_share": grouped_parallel_share,
        "verdict": verdict,
    }


def collect(metrics_file: str = "") -> Dict[str, Any]:
    text = _metricText(metrics_file)
    _rejectNonPrometheusText(text, str(metrics_file) if metrics_file else "进程注册表")
    shapes = parseBatchShapes(text)
    instrument = instrumentPresence(text)
    drift = unrecognizedShapeLabels(text)
    out: Dict[str, Any] = {
        "batch_shapes": shapes,
        "tool_durations": parseToolDurations(text),
        "sparse_share_threshold": SPARSE_SHARE,
        "instrument": instrument,
        # 只写不读是断点，而这个字段**有**读侧：下面按它分型。空值也留着，
        # 是为了让"这一份读数是干净的"成为一个可断言的事实，而不是缺席。
        "unrecognized_shape_labels": drift,
    }
    out.update(batchShapeVerdict(shapes, drift))
    # 成因是 `no_data` **专属**：有结论的读数上挂一个成因，就是给无人消费的槽位
    # 留了个位置（协作红线：只写不读的字段是断点）。
    out["no_data_cause"] = (
        shapeCause(instrument, drift) if out["verdict"] == "no_data" else ""
    )
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="工具并行收益取数（M3 前置）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--metrics-file", default="", help="离线复算用的 /metrics 抓取文本")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    try:
        payload = collect(args.metrics_file)
    except ReadoutInputError as exc:
        # 输入不可用 ⇒ 无法判定。以非零退出码 + 一句话点名收场，不抛解释器栈：
        # 读者必须一眼看出"这次没量到"，而不是从 traceback 里猜是不是判定结论。
        print(f"取数未完成：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    cause = payload.get("no_data_cause") or ""

    print("工具批次形态（按调度路径分档——不合并，见下方两个口径）：")
    if not payload["batch_shapes"]:
        print(_emptyReadoutLine(cause, "；本条读数由 base.handle_tool_calls 落点产生"))
    for path, counts in payload["batch_shapes"].items():
        row = payload["per_path"][path]
        grouped = row["grouped_share"]
        multi_round = row["multi_tool_round_share"]
        print(
            f"  {path}: 单调用 {counts.get(SHAPE_LABELS[0], 0)} | "
            f"多调用串行 {counts.get(SHAPE_LABELS[1], 0)} | "
            f"多调用成组 {counts.get(SHAPE_LABELS[2], 0)} | "
            f"成组/多调用轮 {'无多调用轮' if grouped is None else f'{grouped * 100:.1f}%'} | "
            f"多工具轮/全部轮 {'无样本' if multi_round is None else f'{multi_round * 100:.1f}%'}"
        )

    drift = payload.get("unrecognized_shape_labels") or {}
    if drift:
        # 把名字印出来：成因只说"有漂移"，读者仍需自己去 grep 是哪几个标签。
        named = "、".join(f"{k}（{v} 轮）" for k, v in sorted(drift.items()))
        print(f"\n⚠ 抓取里有本词表不认识的形态标签：{named}")
        print(f"  本读数只认识：{'、'.join(SHAPE_LABELS)}")
        print("  这些样本已从本节的分母里排除——占比回退为空值，不得据此出结论。")

    print("\n两个口径（回答的是两个不同的问题，同一份数据可以给出相反结论）：")
    print(
        f"  §10.1 原文口径  多工具轮 / 全部轮 = {payload['multi_tool_round_share']}"
        f"（否证阈值 {SPARSE_SHARE}）"
    )
    print(
        f"  参考口径        成组批 / 多调用轮 = {payload['grouped_parallel_share']}"
    )
    verdict = payload["verdict"]
    if verdict == "no_data":
        # 关键：**输入缺失**不是**判据结论**。no_data 落在同一行旁不说话，
        # 就会被读成"没收益"，即拿失明当结论（本仓已为此付过代价）。
        # 成因同样要出声：**仪表缺席**与**零样本**的处置相反（修部署 vs 等样本），
        # 只印一个 no_data 等于把这条判断留在我们自己脑内。
        print(
            "结论：no_data"
            "   # 不是 sparse，**不构成 §10.1 的否证**：这是判据输入没采到，"
            "无法判定。不得据此放弃 M3 —— 先取到真 /metrics 抓取文本再判。"
        )
        print(
            f"      成因：{cause or '未判定'} —— "
            f"{_CAUSE_DISPOSITION.get(cause, '成因未判定')}"
        )
    else:
        print(
            f"结论：{verdict}"
            "   # sparse = §10.1 的否证条件成立，应据此放弃 M3 及之后；"
            "worthwhile = 否证未成立，可继续 M3 逐工具论证"
        )

    print("\n工具耗时分布（均值来自直方图本体）：")
    for row in payload["tool_durations"]:
        print(f"  {row['name']}: n={row['count']} 均值={row['avg_ms']}ms 区间={row['segments_s']}")
    if payload["tool_durations"]:
        print(
            f"\n逐工具「值不值得为它成组等待」（判据：P50 与 {WORTH_WAITING_BUDGET_S * 1000:g}ms 门槛比；"
            "冷路径另档，不进这一判断）："
        )
        for row in payload["tool_durations"]:
            bracket = (
                f"({row['p50_lower_ms']}ms, {row['p50_upper_ms']}ms]"
                if row.get("p50_upper_ms") is not None
                else f">{row.get('p50_lower_ms')}ms（超出最大有限桶，上界未知）"
                if row.get("p50_lower_ms") is not None
                else "无样本"
            )
            verdict = row.get("worth_waiting")
            if verdict is True:
                judgement = "值得等（P50 整段在门槛之上）"
            elif verdict is False:
                judgement = "不值得等（P50 整段在门槛之下）"
            elif verdict is None and row.get("count"):
                judgement = (
                    f"**边界**：P50 夹逼区间跨过 {WORTH_WAITING_BUDGET_S * 1000:g}ms 门槛，"
                    "本副仪表的分辨率答不出"
                    "（要么补精细桶，要么等更多样本），不硬挑一侧"
                )
            else:
                judgement = "无样本"
            slow = row.get("slow_share")
            slow_note = (
                f"｜冷路径下界 {slow * 100:.1f}%（另档，不进上面的判断）"
                if slow is not None else ""
            )
            print(f"  {row['name']}: P50={bracket} ⇒ {judgement}{slow_note}")
    else:
        # 耗时段按**它自己的**仪表判成因（与形态表各自独立，见 segmentCause）。
        print(_emptyReadoutLine(segmentCause(payload["instrument"], "duration_family"), ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
