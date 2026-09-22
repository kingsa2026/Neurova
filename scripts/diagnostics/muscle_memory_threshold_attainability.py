"""肌肉记忆阈值可达性重算（工单 008 验收项）。

票面要求：「`0.85`（装配起点）与 RSI 目标 `0.8` 在新指纹分布下的实际触发率
（**给出分母**）；并据此更新 ADR 0016 的"参数梯度"账」。

为什么需要这个读数：007 把脏参数条目的裁定档位收紧后，`tool_memory.muscle_memory_threshold`
是 RSI 参数寻优臂**唯一还有真实梯度的旋钮**（起点 0.85 / setpoint 0.8）。008 换了指纹
口径（字符 n-gram）与写侧参数形状，"这个旋钮还能不能调到、调到之后行为变不变"必须
**用数据重算**，不得默认 ADR 0016 的结论仍成立。

口径：
- 语料是**真实形态的近似问法对**（逐字 / 只差标点 / 换实体 / 换语序 / 无关对照），
  不走网络、不合成模板句；
- 每条配对：先经 `record_usage` 写入（走生产写侧归一），再用第二句 `match_by_query`；
- 触发率分母 = **配对总数**（含无关对照），分子 = confidence ≥ 阈值的条数；
- 无关对照若越过 0.8 即"阈值无区分力"，一并印出。

用法：
    python scripts/diagnostics/muscle_memory_threshold_attainability.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 装配起点（agent_core 经 AgentConfig 实传）与 RSI setpoint，取自 ADR 0016 的表。
START_THRESHOLD = 0.85
SETPOINT_THRESHOLD = 0.8
SEMI_THRESHOLD_RATIO = 0.7

# (写入问法, 命中问法, 关系)。"无关" 是对照组：它越过阈值即阈值失去区分力。
QUERY_PAIRS: List[Tuple[str, str, str]] = [
    ("许昌今天天气怎么样", "许昌今天天气怎么样", "逐字"),
    ("许昌今天天气怎么样", "许昌今天天气怎么样？", "只差标点"),
    ("许昌今天天气怎么样", "许昌明天天气怎么样", "换实体"),
    ("帮我查一下许昌的天气", "帮我查一下北京的天气", "换实体"),
    ("今天天气如何", "今天的天气如何", "换语序"),
    ("查一下明天下雨吗", "查一下后天有没有雨", "换实体"),
    ("许昌今天天气怎么样", "帮我写一段 Python 排序代码", "无关"),
    ("帮我查一下许昌的天气", "把季度报表导出成 PDF", "无关"),
    ("明天许昌下雨吗", "明天许昌会不会下雨", "换措辞"),
    ("把这份周报导出成 PDF", "把这份月报导出成 PDF", "换实体"),
]


def measure(threshold: float) -> Dict[str, Any]:
    """在真实写读路径上量一次触发率（分母 = 全部配对）。"""
    from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory

    with tempfile.TemporaryDirectory() as scratch:
        memory = MuscleMemory(storage_dir=scratch)
        rows: List[Dict[str, Any]] = []
        for index, (written, queried, relation) in enumerate(QUERY_PAIRS):
            memory.record_usage(
                tool_name=f"tool_{index}", query=written,
                parameters={"location": "许昌"} if relation != "无关" else {"query": "x"},
                success=True,
            )
            matches = memory.muscle_memory_matches(queried) if hasattr(memory, "muscle_memory_matches") else memory.match_by_query(queried)
            other_tools = [m for m, _ in matches if m.tool_name != f"tool_{index}"]
            score = 0.0
            for item, confidence in matches:
                if item.tool_name == f"tool_{index}":
                    score = confidence
                    break
            rows.append({
                "relation": relation,
                "written": written,
                "queried": queried,
                "confidence": round(score, 4),
                "triggered": score >= threshold,
                "cross_tool_hits": [m.tool_name for m in other_tools],
            })

    triggered = [r for r in rows if r["triggered"]]
    relevant = [r for r in rows if r["relation"] != "无关"]
    unrelated = [r for r in rows if r["relation"] == "无关"]
    # 梯度带：真输入里落在 (setpoint, start) 开区间内的条数。RI端把阈值从 0.85
    # 调到 0.8 只在**这个带内**改变行为；带里没人 = 旋钮还在但旋不动。
    band = [
        r for r in rows
        if r["relation"] != "无关" and SETPOINT_THRESHOLD < r["confidence"] < START_THRESHOLD
    ]
    return {
        "threshold": threshold,
        "denominator": len(QUERY_PAIRS),
        "triggered": len(triggered),
        "trigger_rate": round(len(triggered) / len(QUERY_PAIRS), 4),
        "relevant_denominator": len(relevant),
        "relevant_triggered": sum(1 for r in relevant if r["triggered"]),
        "unrelated_false_positive": sum(1 for r in unrelated if r["triggered"]),
        "gradient_band_population": len(band),
        "rows": rows,
    }


def build_report() -> Dict[str, Any]:
    start = measure(START_THRESHOLD)
    setpoint = measure(SETPOINT_THRESHOLD)
    return {
        "start_threshold": START_THRESHOLD,
        "setpoint_threshold": SETPOINT_THRESHOLD,
        "start": start,
        "setpoint": setpoint,
        "gradient_band_population": start["gradient_band_population"],
        "decision_changes": start["relevant_triggered"] != setpoint["relevant_triggered"],
        "crossings": start["unrelated_false_positive"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="肌肉记忆阈值可达性重算")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认人类可读）")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for label in ("start", "setpoint"):
        block = report[label]
        print(f"[{label}] 阈值 {block['threshold']}："
              f"触发 {block['triggered']}/{block['denominator']} "
              f"（率 {block['trigger_rate']}）；"
              f"相关配对 {block['relevant_triggered']}/{block['relevant_denominator']}；"
              f"无关误报 {block['unrelated_false_positive']}")
    print(f"梯度带 (0.8,0.85) 内真输入条数：{report['gradient_band_population']}"
          f"（分母 {report['start']['relevant_denominator']} 条相关配对）")
    print(f"0.85 与 0.8 是否产生不同裁定：{report['decision_changes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
