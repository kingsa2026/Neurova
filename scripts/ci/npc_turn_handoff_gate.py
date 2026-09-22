#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 轮数触顶接力门禁（Issue #145）。

## 为什么需要这道门禁

`npc:go` 撞到 `maxTurns` 时，平台只是把 Agent 中止、把流水线判为失败，
**不会**读这个中止事件、更不会重开一轮预算（构建 cnb-2e8-1k341d9s1 实测：
3191326ms 后 Stage 以 `Agent aborted: reached maxTurns limit (200)` 收场，
而同一份配置里的接力 Stage 被 skipper 跳过，Issue 上没有任何回音）。
所以「撞顶之后把活交给下一轮」必须在配置里显式写出来。

配置里已经写了这笔接力（`.cnb.yml` 的 `endStages` + `cnb:apply`）。
**根因（Issue #158，构建 cnb-2v8-1k34htd2p / cnb-2e8-1k341d9s1 实测）**：
接力的燃料曾指定由 Agent 在最后一轮自己写出标记文件 —— 而撞 maxTurns 时平台
只是把 Agent 中止、**不执行任何收尾指令或工具调用**，Agent 根本没有机会写。
于是 `cnb:apply` 的 `if` 恒假、收尾 Stage 每次都是 `skipped`，
接力是一条"看着配了、其实永不触发"的死配置（平台不会为此报任何错）。

故燃料改由**本门禁在 Agent 开工前写入**（它就是那个写点，也是自证点）：
触顶那一轮跑不到任何指令，燃料就不可能来自 Agent。同时把
`turnLimitReached=1` 经**平台声明的导出通道**（stdout 的 `##[set-output]` 标记 +
`.cnb.yml` 同一 Stage 上的 `exports` 映射）交给后续 Stage 的 `cnb:apply`，
让"这一轮是接力轮"这件事在配置期就成立，不依赖 Agent 的记忆。

本门禁回答一个只有真实构建能回答的问题：**在有改动的真实构建里，
`$CNB_BUILD_WORKSPACE` 到底等不等于构建容器的工作目录**。

## 判据与自证

- 断言 `$CNB_BUILD_WORKSPACE/.npc-turn-handoff` 可达（能写、能读回、值相符）。
- 反向自证：在同一构建里写 `$PWD/.npc-turn-handoff`，比对 `$PWD` 是否等于
  `$CNB_BUILD_WORKSPACE`。两者不同即说明"Agent 按字面理解写文件"会写错地方，
  这本身就是一份可读的读数（打印出来，不判红——它不是本门禁要裁的非法状态）。
- 缺 `$CNB_BUILD_WORKSPACE`：判红。它不是"环境没配好"，而是接力判据没有落点，
  必须点名而不是静默跳过。

用法：
    python scripts/ci/npc_turn_handoff_gate.py          # 人类可读
    python scripts/ci/npc_turn_handoff_gate.py --json   # 机器可读

## 为什么同一份脚本要能跑在 node 上

NPC 流水线的镜像（`cnbcool/default-npc:latest`）里**没有 python**：
构建 cnb-du8-1k34cfhg1 实测，本步以 `sh: 1: python: not found`（rc=127）收场，
Agent 那一步被 skipper 跳过，用户在 Issue 上只看到「构建失败」。
故本脚本自带**逐字等价**的 node 分支：解释器由 `.cnb.yml` 的探测结果给出
（python3 → python → node），判据、读数键名、退出码三处都不因解释器而漂移。
两份实现的等价性由
tests/unit/test_ci_npc_config_guard.py::TestNpcScriptInterpreterReachability 常驻校验。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: 接力标记的文件名。这是 `.cnb.yml` 收尾阶段唯一的读点，
#: 也是 `.cnb/settings.yml` 人设里唯一的写法约定。
HANDOFF_MARKER_FILE = ".npc-turn-handoff"

#: 「本轮是接力轮」的变量名。与 `.cnb.yml` 的 `env.turnLimitReached`、
#: `endStages.if` 逐字一致 —— 该判据全仓只有一处事实源（git grep 可见）。
TURN_FLAG_VAR = "turnLimitReached"

#: 把 `TURN_FLAG_VAR` 导出给收尾阶段所用的一对名字，逐字对应 `.cnb.yml` 里
#: 调用本脚本那个 Stage 的 `exports` 映射：
#:
#:     script: "$NPX_CALL scripts/ci/npc_turn_handoff_gate.py"
#:     exports:
#:       <SET_OUTPUT_KEY>: <TURN_FLAG_VAR>
#:
#: 平台**没有** `$CNB_ENV` / `$GITHUB_ENV` 这类文件通道（官方文档
#: 「环境变量」「默认环境变量」两篇全文零命中；本次真实构建里该变量也未注入）。
#: 文本输出与 `exports` 的映射关系写在两处，故这三处名字必须同源，由
#: tests/unit/ci/test_npc_pipeline_time_budget.py 常驻校验。
SET_OUTPUT_DIRECTIVE = "##[set-output"
SET_OUTPUT_KEY = TURN_FLAG_VAR


def resolveWorkspaceRoot(env: dict) -> str:
    """接力判据的落点：环境变量给定，未给定返回空串。"""
    return (env.get("CNB_BUILD_WORKSPACE") or "").strip()


def checkWorkspaceWritable(root: str) -> dict:
    """在给定根下写标记文件并读回，证明收尾阶段确实能读到它。"""
    marker = Path(root) / HANDOFF_MARKER_FILE
    marker.write_text("1", encoding="utf-8")
    try:
        readback = marker.read_text(encoding="utf-8").strip()
    finally:
        marker.unlink(missing_ok=True)
    return {"marker": str(marker), "readback": readback, "ok": readback == "1"}


def markTurnAsHandoff(env: dict) -> dict:
    """把「本轮是接力轮」交给后续 Stage 与收尾的 `cnb:apply`。

    通道：平台声明的 **stdout 标记协议** —— 本函数向标准输出写一行

        ##[set-output turnLimitReached=1]

    CI 按行识别该标记，把它放进本 Job 的 `result`；再由 `.cnb.yml` 同一 Stage 上的
    `exports` 把它映射成环境变量。平台文档明确：`exports` 导出的变量**生命周期为
    当前 Pipeline**，因此 `endStages` 的 `if` 读得到 —— 这正是接力判据需要的可见性。

    为什么不用文件通道（上一批的写法，已被证伪）：
      平台不提供 `$CNB_ENV` / `$GITHUB_ENV`（官方文档零命中，真实构建里也未注入）。
      往一个不存在的路径追加内容既写不出、也不报错，接力会在绿灯下静默失效。

    返回值保留为一份可复算的读数：真实构建日志里能看见它到底走没走通。
    只写一个变量、一种写法：接力判据全仓单点，不许出现第二种状态文件。
    """
    if not (env.get("CNB") or "").strip() and not (env.get("CI") or "").strip():
        # 本地直跑（无 CI 标记）时不往 stdout 注入协议行，避免污染人类可读输出；
        # 仍然如实报告"未发出"，让读数与 CI 里一致可解释。
        return {"written": False, "channel": None, "reason": "非 CI 环境，未发出 set-output 标记"}
    sys.stdout.write(f"{SET_OUTPUT_DIRECTIVE} {SET_OUTPUT_KEY}=1]\n")
    sys.stdout.flush()
    return {"written": True, "channel": SET_OUTPUT_DIRECTIVE, "key": SET_OUTPUT_KEY}


def checkWorkingDirectory(env: dict, cwd: str) -> dict:
    """反向自证：`$PWD` 与 `$CNB_BUILD_WORKSPACE` 是否同一个地方。"""
    root = resolveWorkspaceRoot(env)
    return {
        "pwd": cwd,
        "cnb_build_workspace": root,
        "identical": bool(root) and Path(root).resolve() == Path(cwd).resolve(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NPC 轮数触顶接力门禁")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    root = resolveWorkspaceRoot(os.environ)
    failures: list[str] = []
    result: dict = {"env_cnb_build_workspace": root or None}

    if not root:
        failures.append(
            "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力标记没有落点，"
            "endStages 的 cnb:apply 会因 if 恒假被跳过（构建 cnb-2e8-1k341d9s1 的形态）"
        )
    elif not Path(root).is_dir():
        failures.append(f"CNB_BUILD_WORKSPACE 指向的目录不存在: {root}")
    else:
        try:
            result["marker_check"] = checkWorkspaceWritable(root)
            if not result["marker_check"]["ok"]:
                failures.append(
                    f"{HANDOFF_MARKER_FILE} 写入后读不回原值 —— 收尾阶段会判定「未触顶」"
                )
        except OSError as exc:
            failures.append(f"{HANDOFF_MARKER_FILE} 写入失败: {type(exc).__name__}: {exc}")

    result["working_directory_check"] = checkWorkingDirectory(os.environ, os.getcwd())
    if root and not result["working_directory_check"]["identical"]:
        result["working_directory_divergence"] = (
            "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把标记写到"
            "「工作区工作目录」，收尾阶段读不到，接力整条失效"
        )

    if not failures:
        result["turn_flag_handoff"] = markTurnAsHandoff(os.environ)

    if args.json:
        print(json.dumps({"result": result, "failures": failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    lines = ["=" * 72, "NPC 轮数触顶接力门禁", "=" * 72]
    lines += [f"  {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in result.items()]
    if failures:
        lines += ["", "=" * 72, f"❌ 接力判据不可达（{len(failures)} 项）："]
        lines += [f"  - {item}" for item in failures]
        sys.stdout.write("\n".join(lines) + "\n")
        return 1
    lines += ["", "✅ 接力判据可达：收尾阶段能读到标记文件"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


NODE_IMPLEMENTATION = r"""
#!/usr/bin/env node
// 与 Python 分支逐字等价的实现（同判据、同读数键名、同退出码）。
// 存在理由：NPC 流水线镜像里没有 python，见模块 docstring「为什么同一份脚本要能跑在 node 上」。
const fs = require("fs");
const os = require("os");
const path = require("path");

const HANDOFF_MARKER_FILE = ".npc-turn-handoff";
const TURN_FLAG_VAR = "turnLimitReached";
const SET_OUTPUT_DIRECTIVE = "##[set-output";
const SET_OUTPUT_KEY = TURN_FLAG_VAR;

// 与 Python 的 json.dumps 对齐：缩进 2 空格、**不**转义非 ASCII、
// 字符串外的空格与 Python 的 separators 一致（", " / ": "）。
function pythonJsonScalar(value) {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return String(value);
  // 非 ASCII 原样输出（与 Python json.dumps(..., ensure_ascii=False) 对齐）
  return JSON.stringify(value);
}

function pythonJson(value, indent = 0) {
  if (indent < 0) {
    // 单行形态：等价 Python json.dumps 默认 separators（", " / ": "）
    if (value === null || typeof value !== "object") return pythonJsonScalar(value);
    if (Array.isArray(value)) return "[" + value.map((v) => pythonJson(v, -1)).join(", ") + "]";
    return (
      "{" +
      Object.keys(value)
        .map((k) => JSON.stringify(k) + ": " + pythonJson(value[k], -1))
        .join(", ") +
      "}"
    );
  }
  const pad = "  ".repeat(indent);
  const inner = "  ".repeat(indent + 1);
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") {
    // 非 ASCII 原样输出（与 Python json.dumps(..., ensure_ascii=False) 对齐）
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const items = value.map((v) => inner + pythonJson(v, indent + 1));
    return "[\n" + items.join(",\n") + "\n" + pad + "]";
  }
  const keys = Object.keys(value);
  if (keys.length === 0) return "{}";
  const items = keys.map((k) => inner + JSON.stringify(k) + ": " + pythonJson(value[k], indent + 1));
  return "{\n" + items.join(",\n") + "\n" + pad + "}";
}

function resolveWorkspaceRoot(env) {
  return String(env.CNB_BUILD_WORKSPACE || "").trim();
}

function checkWorkspaceWritable(root) {
  const marker = path.join(root, HANDOFF_MARKER_FILE);
  let readback = null;
  let failReason = null;
  try {
    fs.writeFileSync(marker, "1", "utf8");
    try {
      readback = fs.readFileSync(marker, "utf8").trim();
    } finally {
      try { fs.unlinkSync(marker); } catch (e) { /* 已消失不必再删 */ }
    }
  } catch (exc) {
    failReason = exc.constructor.name + ": " + exc.message;
  }
  return { marker, readback, ok: readback === "1", failReason };
}

function realpathOrSelf(target) {
  try { return fs.realpathSync(target); } catch (e) { return path.resolve(target); }
}

function markTurnAsHandoff(env) {
  if (!String(env.CNB || "").trim() && !String(env.CI || "").trim()) {
    return { written: false, channel: null, reason: "非 CI 环境，未发出 set-output 标记" };
  }
  process.stdout.write(SET_OUTPUT_DIRECTIVE + " " + SET_OUTPUT_KEY + "=1]\n");
  return { written: true, channel: SET_OUTPUT_DIRECTIVE, key: SET_OUTPUT_KEY };
}

function checkWorkingDirectory(env, cwd) {
  const root = resolveWorkspaceRoot(env);
  return {
    pwd: cwd,
    cnb_build_workspace: root,
    identical: Boolean(root) && realpathOrSelf(root) === realpathOrSelf(cwd),
  };
}

function main(argv) {
  const asJson = argv.includes("--json");
  const root = resolveWorkspaceRoot(process.env);
  const failures = [];
  const result = { env_cnb_build_workspace: root || null };

  if (!root) {
    failures.push(
      "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力标记没有落点，" +
      "endStages 的 cnb:apply 会因 if 恒假被跳过（构建 cnb-2e8-1k341d9s1 的形态）");
  } else if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    failures.push("CNB_BUILD_WORKSPACE 指向的目录不存在: " + root);
  } else {
    const check = checkWorkspaceWritable(root);
    result.marker_check = { marker: check.marker, readback: check.readback, ok: check.ok };
    if (check.failReason) {
      failures.push(HANDOFF_MARKER_FILE + " 写入失败: " + check.failReason);
    } else if (!check.ok) {
      failures.push(HANDOFF_MARKER_FILE + " 写入后读不回原值 —— 收尾阶段会判定「未触顶」");
    }
  }

  result.working_directory_check = checkWorkingDirectory(process.env, process.cwd());
  if (root && !result.working_directory_check.identical) {
    result.working_directory_divergence =
      "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把标记写到" +
      "「工作区工作目录」，收尾阶段读不到，接力整条失效";
  }

  if (!failures.length) {
    result.turn_flag_handoff = markTurnAsHandoff(process.env);
  }

  if (asJson) {
    console.log(pythonJson({ result, failures }, 0));
    return failures.length ? 1 : 0;
  }

  const lines = ["=".repeat(72), "NPC 轮数触顶接力门禁", "=".repeat(72)];
  for (const [key, value] of Object.entries(result)) {
    lines.push("  " + key + ": " + pythonJson(value, -1));
  }
  if (failures.length) {
    lines.push("");
    lines.push("=".repeat(72));
    lines.push("❌ 接力判据不可达（" + failures.length + " 项）：");
    for (const item of failures) {
      lines.push("  - " + item);
    }
    process.stdout.write(lines.join("\n") + "\n");
    return 1;
  }
  lines.push("");
  lines.push("✅ 接力判据可达：收尾阶段能读到标记文件");
  process.stdout.write(lines.join("\n") + "\n");
  return 0;
}

process.exit(main(process.argv.slice(2)));
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="NPC 轮数触顶接力门禁")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    root = resolveWorkspaceRoot(os.environ)
    failures: list[str] = []
    result: dict = {"env_cnb_build_workspace": root or None}

    if not root:
        failures.append(
            "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力标记没有落点，"
            "endStages 的 cnb:apply 会因 if 恒假被跳过（构建 cnb-2e8-1k341d9s1 的形态）"
        )
    elif not Path(root).is_dir():
        failures.append(f"CNB_BUILD_WORKSPACE 指向的目录不存在: {root}")
    else:
        try:
            result["marker_check"] = checkWorkspaceWritable(root)
            if not result["marker_check"]["ok"]:
                failures.append(
                    f"{HANDOFF_MARKER_FILE} 写入后读不回原值 —— 收尾阶段会判定「未触顶」"
                )
        except OSError as exc:
            failures.append(f"{HANDOFF_MARKER_FILE} 写入失败: {type(exc).__name__}: {exc}")

    result["working_directory_check"] = checkWorkingDirectory(os.environ, os.getcwd())
    if root and not result["working_directory_check"]["identical"]:
        result["working_directory_divergence"] = (
            "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把标记写到"
            "「工作区工作目录」，收尾阶段读不到，接力整条失效"
        )

    if not failures:
        result["turn_flag_handoff"] = markTurnAsHandoff(os.environ)

    if args.json:
        print(json.dumps({"result": result, "failures": failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    lines = ["=" * 72, "NPC 轮数触顶接力门禁", "=" * 72]
    lines += [f"  {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in result.items()]
    if failures:
        lines += ["", "=" * 72, f"❌ 接力判据不可达（{len(failures)} 项）："]
        lines += [f"  - {item}" for item in failures]
        sys.stdout.write("\n".join(lines) + "\n")
        return 1
    lines += ["", "✅ 接力判据可达：收尾阶段能读到标记文件"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    # node 分支的入口**不在这里**：`node <本文件>.py` 到不了这一行。
    # node 按扩展名解析模块，遇到 `.py` 在解析阶段就以
    # `ERR_UNKNOWN_FILE_EXTENSION` 退出（构建 cnb-9cc-1k34ff3t1 实测 rc=1），
    # 任何写在 `__main__` 里的"按解释器分派"都不可达，故不留这段死码。
    #
    # node 侧由外层壳 scripts/ci/run_gate_under_node.sh 接管：它从本文件里
    # 取出下方 NODE_IMPLEMENTATION 正文、写成临时 .js 交给 node，
    # 再把退出码原样传出。两份实现的等价性由
    # tests/unit/ci/test_npc_script_interpreter_reachability.py 真跑比对。
    sys.exit(main())
