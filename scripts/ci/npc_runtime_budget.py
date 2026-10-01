#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 运行期预算自查（Issue #272）—— 把「离被平台中止还有多久」算给 Agent 看。

## 为什么需要它（本仓已付过的代价）

平台对 NPC 流水线同时施加三道上限，而它们的**可见性完全不同**：

| 上限 | 默认 | 仓库侧可配 | 撞上时的表现 |
|------|------|-----------|-------------|
| 流水线整体运行时长 | 由 Runner 下发 | 改不掉 | 整轮会话被中止 |
| Job / Stage 单次最长 | 2h | `timeout`，最大 12h | 该 Stage 以 error 收场 |
| `npc:go` 的一次工具执行 | 取所在 Stage 的 `timeout` | 同上 | 该次工具调用失败 |
| 无输出超时 | 10 分钟 | 同上（声明 `timeout` 后与之等长） | 该 Stage 被掐断 |

四种阈值混在一起，Agent 此前**没有任何量尺**：它只能靠猜，而猜的结果是零余量撞墙 ——
本仓实测（构建 cnb-m74-1k3cm87o9）跑了 222 轮 / 7,330,218ms 后被平台中止，
改而未提交的成果（工作树不跨轮保存）随容器一起丢，Issue 上只留下一条构建号。
日志里另有多处「上限大概 2h 吧」的推理 —— 上限本就是平台注入的环境变量，
一条 `env` 就能看到，保密既没保住、又拿走了做预算的依据。

## 它给什么：四态判据

读 `CNB_PIPELINE_MAX_RUN_TIME`（总额，毫秒）与 `CNB_BUILD_START_TIME`（起点），
按已用比例给出一行机器可读结论：

    verdict=continue   < 70%   还有余量
    verdict=wrapup     ≥ 70%   停止开新工作面，先落盘再回帖
    verdict=halt       ≥ 85%   立刻收尾落盘 + 回帖
    verdict=unknown    变量缺失 按保守纪律走（先落盘一次，别当「时间还很多」）

阈值取 70 / 85 而不是「跑到墙上」：本仓两条失败读数分别落在 119.3 / 121.1 分钟
（上限 120 分钟）—— 只要在任意一个 70% 节点停下来落盘并回帖，就不会连结论都发不出。

## 退出码恒为 0

它是**决策输入**，不是判据：机器可读的真值是 `verdict=` 那一行，不是退出码。
把退出码做成判据，等于让「量不出时间」本身变成一次红灯，与任务成败无关。

用法：
    python scripts/ci/npc_runtime_budget.py              # 人类可读
    python scripts/ci/npc_runtime_budget.py --json       # 机器可读（含读数与判据）
    python scripts/ci/npc_runtime_budget.py --predicate  # 收尾接力的判据片段（`true`/`false`）

调用时机（由角色人设约束）：开工第一件事跑一次；**每次准备开新工作面之前再跑一次**。

`--predicate` 是给**收尾接力**用的（Issue #327）：判据此前只问「有没有被中止在
Agent 那一格」，于是平台 AI 网关的中途掐断与撞满配额被混为一谈，前者被放大成
每约 7 分钟一轮的自动续跑链条（构建 cnb-urv-1k3lagkdv：第 36 轮 / 7.4 分钟，
四道上限一道未触达）。第三问「可归因到时长配额吗」复用本脚本的
`meetsQuotaWall()`，阈值与解析口径因此只有一处定义。

## 为什么同一份脚本要能跑在 node 上

NPC 流水线的镜像（`cnbcool/default-npc:latest`）里**没有 python**，故本脚本自带
**逐字等价**的 node 分支：读数键名、判据、阈值三处都不因解释器而漂移。
解释器由 `.cnb.yml` 的探测结果给出（python3 → python → node），
`node` 分支经桥脚本 `scripts/ci/run_gate_under_node.sh` 执行
（node 按扩展名解析模块，`.py` 交 node 会在解析前以
`ERR_UNKNOWN_FILE_EXTENSION` 退出，构建 cnb-9cc-1k34ff3t1 实测 rc=1）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from datetime import datetime, timezone

#: 到这里就该收：停止开新工作面，先落盘（commit / 建 PR / 写产物）再回帖。
WRAP_PCT = 70

#: 到这里就必须停：立刻收尾落盘 + 回帖，别再开新工作面。
HALT_PCT = 85

#: 收尾接力的判据片段（Issue #327）：本次中止是否撞在**时长配额**上。
#: 它被 shell 的 `eval` 读，取值只能是这两条 —— 不在这里印第三份口径。
PREDICATE_QUOTA_WALL = "true"
PREDICATE_NOT_QUOTA_WALL = "false"

#: 缺变量时的判据（按保守纪律走，不默认「时间还很多」）。
VERDICT_UNKNOWN = "unknown"
VERDICT_CONTINUE = "continue"
VERDICT_WRAPUP = "wrapup"
VERDICT_HALT = "halt"

def parseMilliseconds(raw) -> int:
    """把平台的毫秒读数解析成整数；非数值 / 非正值一律返回 0（= 量不出）。"""
    text = str(raw or "").strip()
    if not text.isdigit():
        return 0
    value = int(text)
    return value if value > 0 else 0


def parseStartEpoch(raw) -> float:
    """把 `CNB_BUILD_START_TIME` 解析成 epoch 秒；解析不出返回 0.0（= 量不出）。

    平台给的是 ISO 8601（形如 `2026-09-26T14:32:35.364Z`）。容忍末尾 `Z`
    与小数秒；其余形态一律算量不出 —— 猜时间比不猜更危险。
    """
    text = str(raw or "").strip()
    if not text:
        return 0.0
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        stamp = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def readElapsedPct(env: dict, now_epoch: float) -> int:
    """已用百分比；两处口径（总额 / 起点）任一缺失即 -1（= 量不出）。

    与 readBudget 共用同一套解析与取整，故「量尺里的读数」与「接力判据里的读数」
    不可能分叉（Issue #327：判据要回答的正是"这次中止是不是撞在时长上"）。
    """
    total_ms = parseMilliseconds(env.get("CNB_PIPELINE_MAX_RUN_TIME"))
    start_epoch = parseStartEpoch(env.get("CNB_BUILD_START_TIME"))
    if not total_ms or not start_epoch:
        return -1
    total_s = total_ms // 1000
    if not total_s:
        return -1
    elapsed_s = max(0, int(now_epoch - start_epoch))
    return min(100, elapsed_s * 100 // total_s)


def meetsQuotaWall(env: dict, now_epoch: float) -> bool:
    """本次中止能否归因到**时长配额**（= 已用比例触达 HALT_PCT）。

    判据方向（Issue #327 的根因）：收尾接力此前只问「是不是被中止在 Agent 那一格」，
    于是**平台网关在中途掐断**（构建 cnb-urv-1k3lagkdv：第 36 轮 / 7.4 分钟 /
    `Pipeline has been stopped, Agent aborted`）也被当成「用满配额」，被放大成
    每约 7 分钟一轮的自动续跑链条，每一轮都真实计入 LLM 成本。
    现在多问一句：中止时刻离配额墙还有多远 —— 远未触达即外部中止，不续跑。

    拿不出读数（变量缺失/解析失败）时返回 False：**不续跑**。
    教义第 2 条——「量不出来」不得被转写成一次烧配额的接力。
    """
    elapsed_pct = readElapsedPct(env, now_epoch)
    return elapsed_pct >= HALT_PCT


def verdictFor(elapsed_pct: int) -> str:
    """已用比例 → 判据（阈值边界一并在这里，读数是它唯一的输入）。"""
    if elapsed_pct >= HALT_PCT:
        return VERDICT_HALT
    if elapsed_pct >= WRAP_PCT:
        return VERDICT_WRAPUP
    return VERDICT_CONTINUE


def readBudget(env: dict, now_epoch: float) -> dict:
    """产出读数与判据。两处口径（总额 / 起点）任一缺失即 `unknown`。"""
    total_ms = parseMilliseconds(env.get("CNB_PIPELINE_MAX_RUN_TIME"))
    start_epoch = parseStartEpoch(env.get("CNB_BUILD_START_TIME"))
    reading = {
        "total_ms": total_ms or None,
        "build_start_time": (env.get("CNB_BUILD_START_TIME") or "").strip() or None,
        "elapsed_s": None,
        "remaining_s": None,
        "elapsed_pct": None,
    }
    if not total_ms or not start_epoch:
        reading["verdict"] = VERDICT_UNKNOWN
        reading["reason"] = (
            "平台未下发 CNB_PIPELINE_MAX_RUN_TIME，或 CNB_BUILD_START_TIME 缺失/无法解析"
        )
        return reading

    total_s = total_ms // 1000
    elapsed_s = max(0, int(now_epoch - start_epoch))
    elapsed_pct = min(100, elapsed_s * 100 // total_s) if total_s else 0
    reading.update({
        "total_s": total_s,
        "elapsed_s": elapsed_s,
        "remaining_s": max(0, total_s - elapsed_s),
        "elapsed_pct": elapsed_pct,
        "verdict": verdictFor(elapsed_pct),
    })
    return reading


def formatDuration(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


def renderHuman(reading: dict) -> str:
    lines = ["[npc-runtime-budget] 流水线运行时长预算（平台下发，仓库侧改不掉）"]
    if reading["verdict"] == VERDICT_UNKNOWN:
        lines.append(f"  结论 verdict={VERDICT_UNKNOWN}")
        lines.append(f"  ⚠️ {reading['reason']}")
        lines.append("     按保守纪律走：先落盘一次（commit / 建 PR / 写产物），再决定是否继续。")
        return "\n".join(lines)
    lines.append(
        "  总额 {} ｜ 已用 {}（{}%）｜ 剩余 {}".format(
            formatDuration(reading["total_s"]),
            formatDuration(reading["elapsed_s"]),
            reading["elapsed_pct"],
            formatDuration(reading["remaining_s"]),
        )
    )
    lines.append(f"  结论 verdict={reading['verdict']}")
    if reading["verdict"] == VERDICT_HALT:
        lines.append(f"  🛑 已用 ≥{HALT_PCT}%：**立刻收尾** —— 落盘 + 回帖「本轮到哪了 + 下一步」，")
        lines.append("     别再开新工作面。")
    elif reading["verdict"] == VERDICT_WRAPUP:
        lines.append(f"  ⚠️ 已用 ≥{WRAP_PCT}%：**停止开新工作面** —— 先落盘，再回帖说清")
        lines.append("     「本轮到哪了 + 下一步」，然后按能做完的范围收尾。")
    else:
        lines.append("  ✅ 还有余量：开新工作面之前再跑一次这个脚本就行。")
    return "\n".join(lines)


#: node 分支的实现：与 Python 分支**逐字等价**（同读数键名、同阈值、同判据）。
#: 它是本文件的第二运行时入口，不是第二份口径 —— 两者的输出由
#: tests/unit/ci/test_npc_runtime_budget.py 逐字比对。
NODE_IMPLEMENTATION = r"""
const WRAP_PCT = 70, HALT_PCT = 85;
const PREDICATE_QUOTA_WALL = "true", PREDICATE_NOT_QUOTA_WALL = "false";
function parseMilliseconds(raw) {
  const text = String(raw || "").trim();
  if (!/^[0-9]+$/.test(text)) return 0;
  const value = parseInt(text, 10);
  return value > 0 ? value : 0;
}
function parseStartEpoch(raw) {
  const text = String(raw || "").trim();
  if (!text) return 0;
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? ms / 1000 : 0;
}
function readElapsedPct(env, nowEpoch) {
  const totalMs = parseMilliseconds(env.CNB_PIPELINE_MAX_RUN_TIME);
  const startEpoch = parseStartEpoch(env.CNB_BUILD_START_TIME);
  if (!totalMs || !startEpoch) return -1;
  const totalS = Math.floor(totalMs / 1000);
  if (!totalS) return -1;
  const elapsedS = Math.max(0, Math.floor(nowEpoch - startEpoch));
  return Math.min(100, Math.floor(elapsedS * 100 / totalS));
}
function meetsQuotaWall(env, nowEpoch) {
  return readElapsedPct(env, nowEpoch) >= HALT_PCT;
}
function verdictFor(pct) {
  if (pct >= HALT_PCT) return "halt";
  if (pct >= WRAP_PCT) return "wrapup";
  return "continue";
}
function readBudget(env, nowEpoch) {
  const totalMs = parseMilliseconds(env.CNB_PIPELINE_MAX_RUN_TIME);
  const startEpoch = parseStartEpoch(env.CNB_BUILD_START_TIME);
  const reading = {
    total_ms: totalMs || null,
    build_start_time: String(env.CNB_BUILD_START_TIME || "").trim() || null,
    elapsed_s: null, remaining_s: null, elapsed_pct: null,
  };
  if (!totalMs || !startEpoch) {
    reading.verdict = "unknown";
    reading.reason = "平台未下发 CNB_PIPELINE_MAX_RUN_TIME，或 CNB_BUILD_START_TIME 缺失/无法解析";
    return reading;
  }
  const totalS = Math.floor(totalMs / 1000);
  const elapsedS = Math.max(0, Math.floor(nowEpoch - startEpoch));
  const elapsedPct = totalS ? Math.min(100, Math.floor(elapsedS * 100 / totalS)) : 0;
  reading.total_s = totalS;
  reading.elapsed_s = elapsedS;
  reading.remaining_s = Math.max(0, totalS - elapsedS);
  reading.elapsed_pct = elapsedPct;
  reading.verdict = verdictFor(elapsedPct);
  return reading;
}
function formatDuration(seconds) {
  if (seconds >= 3600) {
    return Math.floor(seconds / 3600) + "h" + String(Math.floor((seconds % 3600) / 60)).padStart(2, "0") + "m";
  }
  if (seconds >= 60) {
    return Math.floor(seconds / 60) + "m" + String(seconds % 60).padStart(2, "0") + "s";
  }
  return seconds + "s";
}
function renderHuman(reading) {
  const lines = ["[npc-runtime-budget] 流水线运行时长预算（平台下发，仓库侧改不掉）"];
  if (reading.verdict === "unknown") {
    lines.push("  结论 verdict=unknown");
    lines.push("  ⚠️ " + reading.reason);
    lines.push("     按保守纪律走：先落盘一次（commit / 建 PR / 写产物），再决定是否继续。");
    return lines.join("\n");
  }
  lines.push("  总额 " + formatDuration(reading.total_s) + " ｜ 已用 " + formatDuration(reading.elapsed_s)
    + "（" + reading.elapsed_pct + "%）｜ 剩余 " + formatDuration(reading.remaining_s));
  lines.push("  结论 verdict=" + reading.verdict);
  if (reading.verdict === "halt") {
    lines.push("  🛑 已用 ≥85%：**立刻收尾** —— 落盘 + 回帖「本轮到哪了 + 下一步」，");
    lines.push("     别再开新工作面。");
  } else if (reading.verdict === "wrapup") {
    lines.push("  ⚠️ 已用 ≥70%：**停止开新工作面** —— 先落盘，再回帖说清");
    lines.push("     「本轮到哪了 + 下一步」，然后按能做完的范围收尾。");
  } else {
    lines.push("  ✅ 还有余量：开新工作面之前再跑一次这个脚本就行。");
  }
  return lines.join("\n");
}
const wantJson = process.argv.includes("--json");
const wantPredicate = process.argv.includes("--predicate");
const nowEpoch = Date.now() / 1000;
if (wantPredicate) {
  process.stdout.write((meetsQuotaWall(process.env, nowEpoch)
    ? PREDICATE_QUOTA_WALL : PREDICATE_NOT_QUOTA_WALL) + "\n");
} else {
  const reading = readBudget(process.env, nowEpoch);
  process.stdout.write((wantJson ? JSON.stringify(reading) : renderHuman(reading)) + "\n");
}
"""


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description="NPC 运行期预算自查")
    parser.add_argument("--json", action="store_true", help="输出机器可读读数")
    parser.add_argument("--predicate", action="store_true",
                        help="只输出收尾接力的判据片段（true/false）——被 `eval` 读")
    parser.add_argument("--now", type=float, default=None,
                        help="覆盖「现在」（epoch 秒），仅供判据侧复算")
    args = parser.parse_args(argv)

    now_epoch = args.now if args.now is not None else datetime.now(timezone.utc).timestamp()
    if args.predicate:
        print(PREDICATE_QUOTA_WALL if meetsQuotaWall(dict(os.environ), now_epoch)
              else PREDICATE_NOT_QUOTA_WALL)
        return 0
    reading = readBudget(dict(os.environ), now_epoch)
    if args.json:
        print(json.dumps(reading, ensure_ascii=False))
    else:
        print(renderHuman(reading))
    return 0


if __name__ == "__main__":
    # 只在作为进程运行时重配控制台：本文件会被 `test_deploy_config_guard.py` 之类
    # 用 importlib 在 pytest 进程内加载，模块级 reconfigure 等于改宿主进程的捕获流。
    # 中文 Windows 的 cp936 编不出 ⚠️/🛑/→，`print` 会抛 UnicodeEncodeError 把门禁自己打死
    # （Linux CI 看不见这条）。同仓先例 scripts/ci_static_gate.py 是模块级——它不被 import。
    if hasattr(sys.stdout, "reconfigure"):
        # `newline="\n"`：读数只准出现 LF。不钉死则 Windows 上文本流把 '\n' 写成
        # os.linesep（CRLF），而本文件的 node 孪生实现恒写 LF —— 同一条判据的两个身体
        # 吐出不同字节，逐字比的双运行时 parity 判据在 Windows 上恒假红（工单集 §39/§40）。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
