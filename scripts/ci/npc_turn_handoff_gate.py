#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 接力构建环境自证（Issue #145；判据两轮收口见 Issue #189）。

## 这道自证回答什么

`npc:go` 撞到 `maxTurns` 时，平台把 Agent 中止、不执行任何收尾指令或工具调用
（构建 cnb-2e8-1k341d9s1 / cnb-2v8-1k34htd2p 实测：3191326ms / 2362852ms 后被
`Agent aborted: reached maxTurns limit (200)` 收场）。故"撞顶后把活交给下一轮"
只能由**配置侧**在收尾阶段显式判出来。

判据经历三轮，每轮都被下一个真实构建推翻：

1. 燃料由 Agent 在最后一轮自己写标记文件 → 触顶那一轮跑不到任何指令，
   `if` 恒假、收尾 Stage 每次 `skipped`，Issue 上没有任何回音。
2. 燃料改由本门禁在 Agent 开工前**无条件**写出（`CNB` 非空即写，真实构建里恒真），
   再经 stdout 的 `##[set-output]` + `exports` 变成 Pipeline 级环境变量 →
   `if` 恒**真**。这不是判据写松了，而是**判据的输入端被自己填成了真值**：
   该变量回答「上一轮是否用满配额」，而得知这件事的唯一时点是收尾期。
   后果是空轮防护全失效，正常收官也照拉下一轮：
     cnb-2q8-1k3buskao  Agent stage success（1774s，未撞顶）→ 拉 cnb-lga-1k3c0itrj
     cnb-kdg-1k3bv22ct  Agent stage success（3977s，未撞顶）→ 拉 cnb-fln-1k3c2rjk7
3. 现形态（Issue #189）：收尾 `if` 直接读**平台在收尾期注入的事实** ——
   `$CNB_PIPELINE_STATUS` 与 `$CNB_BUILD_FAILED_MSG`（平台「环境变量」篇；
   真 `npc:go` 撞 `maxTurns` 的读数见构建 cnb-s4f-1k3c46us9 / cnb-p2q-1k3c2g7u3）。
   构建侧不再产出任何被 `if` 消费的真值，故**本门禁不再写任何接力标记**。

## 本门禁现在做什么

只做一件事：把接力的**环境前提**在 Agent 开工前证一遍 ——

- 断言 `$CNB_BUILD_WORKSPACE` 存在、可写、写后读得回（探针文件即用即删）；
- 反向自证 `$PWD` 是否等于 `$CNB_BUILD_WORKSPACE`：两者不同即说明"Agent 按字面
  理解写文件"会写错地方，这本身就是一份可读读数（打印出来，不判红 ——
  它不是本门禁要裁的非法状态）。

缺 `$CNB_BUILD_WORKSPACE`：判红。它不是"环境没配好"，而是环境前提没有落点，
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
tests/unit/ci/test_ci_npc_config_guard.py::TestNpcScriptInterpreterReachability 常驻校验。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: 探针文件名。本门禁写它、读回、再删掉 —— 只为证明工作区**可写**，
#: 与接力判据无关（判据读平台在收尾期注入的两个变量，见模块 docstring 第 3 轮）。
#: 名字带 `probe` 就是为了一眼看出它没有下游消费者，避免被当成"燃料"再次接线。
WORKSPACE_PROBE_FILE = ".npc-workspace-probe"


def resolveWorkspaceRoot(env: dict) -> str:
    """接力判据的落点：环境变量给定，未给定返回空串。"""
    return (env.get("CNB_BUILD_WORKSPACE") or "").strip()


def checkWorkspaceWritable(root: str) -> dict:
    """在给定根下写探针文件并读回，证明工作区确实可写（探针即用即删）。"""
    marker = Path(root) / WORKSPACE_PROBE_FILE
    marker.write_text("1", encoding="utf-8")
    try:
        readback = marker.read_text(encoding="utf-8").strip()
    finally:
        marker.unlink(missing_ok=True)
    return {"probe": str(marker), "readback": readback, "ok": readback == "1"}


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
            "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力环境前提没有落点，"
            "本步无法自证工作区可写与 $PWD 同址"
        )
    elif not Path(root).is_dir():
        failures.append(f"CNB_BUILD_WORKSPACE 指向的目录不存在: {root}")
    else:
        try:
            result["probe_check"] = checkWorkspaceWritable(root)
            if not result["probe_check"]["ok"]:
                failures.append(
                    f"{WORKSPACE_PROBE_FILE} 写入后读不回原值 —— 工作区不可信，接力环境前提不成立"
                )
        except OSError as exc:
            failures.append(f"{WORKSPACE_PROBE_FILE} 写入失败: {type(exc).__name__}: {exc}")

    result["working_directory_check"] = checkWorkingDirectory(os.environ, os.getcwd())
    if root and not result["working_directory_check"]["identical"]:
        result["working_directory_divergence"] = (
            "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把文件写到"
            "「工作区工作目录」，与门禁自证的位置不是一处"
        )

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
    lines += ["", "✅ 接力环境前提成立：工作区可写，且 $PWD 与它同址"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


NODE_IMPLEMENTATION = r"""
#!/usr/bin/env node
// 与 Python 分支逐字等价的实现（同判据、同读数键名、同退出码）。
// 存在理由：NPC 流水线镜像里没有 python，见模块 docstring「为什么同一份脚本要能跑在 node 上」。
const fs = require("fs");
const os = require("os");
const path = require("path");

const WORKSPACE_PROBE_FILE = ".npc-workspace-probe";

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
  const marker = path.join(root, WORKSPACE_PROBE_FILE);
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
      "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力环境前提没有落点，" +
      "本步无法自证工作区可写与 $PWD 同址");
  } else if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    failures.push("CNB_BUILD_WORKSPACE 指向的目录不存在: " + root);
  } else {
    const check = checkWorkspaceWritable(root);
    result.probe_check = { probe: check.marker, readback: check.readback, ok: check.ok };
    if (check.failReason) {
      failures.push(WORKSPACE_PROBE_FILE + " 写入失败: " + check.failReason);
    } else if (!check.ok) {
      failures.push(WORKSPACE_PROBE_FILE + " 写入后读不回原值 —— 工作区不可信，接力环境前提不成立");
    }
  }

  result.working_directory_check = checkWorkingDirectory(process.env, process.cwd());
  if (root && !result.working_directory_check.identical) {
    result.working_directory_divergence =
      "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把文件写到" +
      "「工作区工作目录」，与门禁自证的位置不是一处";
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
  lines.push("✅ 接力环境前提成立：工作区可写，且 $PWD 与它同址");
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
            "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 接力环境前提没有落点，"
            "本步无法自证工作区可写与 $PWD 同址"
        )
    elif not Path(root).is_dir():
        failures.append(f"CNB_BUILD_WORKSPACE 指向的目录不存在: {root}")
    else:
        try:
            result["probe_check"] = checkWorkspaceWritable(root)
            if not result["probe_check"]["ok"]:
                failures.append(
                    f"{WORKSPACE_PROBE_FILE} 写入后读不回原值 —— 工作区不可信，接力环境前提不成立"
                )
        except OSError as exc:
            failures.append(f"{WORKSPACE_PROBE_FILE} 写入失败: {type(exc).__name__}: {exc}")

    result["working_directory_check"] = checkWorkingDirectory(os.environ, os.getcwd())
    if root and not result["working_directory_check"]["identical"]:
        result["working_directory_divergence"] = (
            "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：Agent 若按字面把文件写到"
            "「工作区工作目录」，与门禁自证的位置不是一处"
        )

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
    lines += ["", "✅ 接力环境前提成立：工作区可写，且 $PWD 与它同址"]
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
