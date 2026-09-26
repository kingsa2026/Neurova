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

**`path` 分档必须读，不能合并**：`AnthropicLoop.handle_tool_calls` 逐条转发
`super().handle_tool_calls([单条])`，那条路径上永远只会是 `single_call`——
并进总数就把一条路径的盲区读成"M3 没有收益"，据此砍方案是拿失明当结论。

**读数的三种"没有结论"必须分得开**：`sparse` 是判据结论（否证成立）、
`worthwhile` 是判据结论（否证未成立）、`no_data` 是**判据输入没采到**（无法
判定，不构成否证）。把 `no_data` 读成"没收益"就是拿失明当结论 —— 故它在输出
里显式标注，输入不可用（文件读不到 / 内容不是 Prometheus 文本）则以非零退出码
点名收场，不抛解释器栈（真抓取被反代吞成 HTML 正是这条路径的真实形态）。

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

#: 方案 §10.1 的否证阈值：多调用轮里成组批的占比低于它就说明 M3 收益不成立。
#: 写在脚本里而非散在说明里，是为了让"低于阈值就放弃"这件事**可机器判定**。
SPARSE_SHARE = 0.05


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
        from neurova.core.metrics import generate_metrics_text

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


def parseBatchShapes(text: str) -> Dict[str, Dict[str, int]]:
    """`{path: {shape: 轮数}}`——按调度路径分档，不合并。

    匹配落在**样本名**上（`neurova_tool_batch_shapes_total`）：`prometheus_client`
    暴露 counter 时族名是去 `_total` 后缀的归一形态，按族名比会恒不命中——
    `neurova/api/endpoints/analytics.py` 的两处读侧正是栽在这里（本片一并根修）。
    """
    out: Dict[str, Dict[str, int]] = {}
    for family in _families(text):
        for sample in family.samples:
            if sample.name != SHAPE_METRIC:
                continue
            path = str(sample.labels.get("path") or "?")
            shape = str(sample.labels.get("shape") or "?")
            bucket = out.setdefault(path, {})
            bucket[shape] = bucket.get(shape, 0) + int(sample.value)
    return out


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
        rows.append(
            {
                "name": name,
                "count": count,
                "avg_ms": round(sums[name] / count * 1000, 2) if count else 0.0,
                "segments_s": {k: v for k, v in segments.items() if v},
            }
        )
    return rows


def batchShapeVerdict(shapes: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
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
    for path, counts in shapes.items():
        single_call = int(counts.get("single_call", 0))
        multi_serial = int(counts.get("multi_serial", 0))
        multi_parallel = int(counts.get("multi_parallel", 0))
        sub = multi_serial + multi_parallel
        perPath[path] = {
            "single_call": single_call,
            "multi_serial": multi_serial,
            "multi_parallel": multi_parallel,
            # 本路径内：成组批 / 多调用轮（"多调用轮里成组吃到了多少"）
            "grouped_share": round(multi_parallel / sub, 4) if sub else None,
            # 本路径内：多工具轮 / 全部轮（§10.1 口径，逐路径给）
            "multi_tool_round_share": round(sub / (sub + single_call), 4)
            if (sub + single_call)
            else None,
        }
        grouped += multi_parallel
        total_multi += sub
        total_rounds += sub + single_call

    multi_tool_round_share = (
        round(total_multi / total_rounds, 4) if total_rounds else None
    )
    grouped_parallel_share = round(grouped / total_multi, 4) if total_multi else None

    if multi_tool_round_share is None:
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
    out: Dict[str, Any] = {
        "batch_shapes": shapes,
        "tool_durations": parseToolDurations(text),
        "sparse_share_threshold": SPARSE_SHARE,
    }
    out.update(batchShapeVerdict(shapes))
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

    print("工具批次形态（按调度路径分档——不合并，见下方两个口径）：")
    if not payload["batch_shapes"]:
        print("  （无样本——本条读数由 base.handle_tool_calls 落点产生，先跑几轮对话）")
    for path, counts in payload["batch_shapes"].items():
        row = payload["per_path"][path]
        grouped = row["grouped_share"]
        multi_round = row["multi_tool_round_share"]
        print(
            f"  {path}: 单调用 {counts.get('single_call', 0)} | "
            f"多调用串行 {counts.get('multi_serial', 0)} | "
            f"多调用成组 {counts.get('multi_parallel', 0)} | "
            f"成组/多调用轮 {'无多调用轮' if grouped is None else f'{grouped * 100:.1f}%'} | "
            f"多工具轮/全部轮 {'无样本' if multi_round is None else f'{multi_round * 100:.1f}%'}"
        )

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
        print(
            "结论：no_data"
            "   # 不是 sparse，**不构成 §10.1 的否证**：这是判据输入没采到，"
            "无法判定。不得据此放弃 M3 —— 先取到真 /metrics 抓取文本再判。"
        )
    else:
        print(
            f"结论：{verdict}"
            "   # sparse = §10.1 的否证条件成立，应据此放弃 M3 及之后；"
            "worthwhile = 否证未成立，可继续 M3 逐工具论证"
        )

    print("\n工具耗时分布（均值来自直方图本体）：")
    if not payload["tool_durations"]:
        print("  （无样本）")
    for row in payload["tool_durations"]:
        print(f"  {row['name']}: n={row['count']} 均值={row['avg_ms']}ms 区间={row['segments_s']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
