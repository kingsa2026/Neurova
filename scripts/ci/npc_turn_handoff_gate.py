#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 接力构建环境自证（Issue #145 / #151；判据三轮收口见 Issue #158 / #170 / #189）。

## 它现在只做一件事：在 Agent 开工前证明「这条流水线跑得起来、工作区落点在哪」

NPC 流水线的前置步骤必须能在镜像里真的跑起来，否则整条流水线以
「请求的解释器不存在」收场，而用户看到的是「流水线构建失败」——与任务内容无关。
构建 cnb-du8-1k34cfhg1 的实测原文：

    sh: 1: python: not found
    Finished, code: 127, duration: 0.1s

故本门禁断言两件开工前就能证实的事：

- `$CNB_BUILD_WORKSPACE` 可达（能写、能读回、值相符）——工作区是 Agent 的落点；
- `$PWD` 与 `$CNB_BUILD_WORKSPACE` 是否同一目录（读数，不判红：它只回答
  「按字面理解工作目录会写到哪」，本身不是非法状态）。

## 它不再做的事：产出接力判据

此前本门禁还向 stdout 写一行标记，作为「本轮是接力轮」的凭据。**该机制已被
真实构建证伪并删净**（Issue #158 / #189 两轮）：撞顶那一刻平台不给 Agent 任何
执行机会，而构建侧在 Agent 开工**之前**根本无从知道本轮会不会撞满轮数 ——
于是标记被无条件写成 1，`if` 从"恒假"变成"恒真"。实测四条评论触发的父构建
（maxTurns=200）分别只跑了 97 / 135 / 164 / 76 轮，收尾接力却一律 success；
代价可复算：接力落点 32 次构建 / 22.2 小时墙钟。

判据已搬到**平台在收尾时刻注入的事实变量**上（`$CNB_PIPELINE_STATUS` 与
`$CNB_BUILD_FAILED_MSG`），落点见 `.cnb.yml` 的收尾 `endStages.if`。
判据只有一处，本脚本不再持有第二份，也不向任何通道发射真值 ——
探针文件名带 `probe` 就是为了一眼看出它没有下游消费者。

`$CNB_BUILD_FAILED_MSG` 在平台侧有**两种**中止原文，判据必须都覆盖：
轮数用满给 `Agent aborted: reached maxTurns limit (N)`
（实测 cnb-s4f-1k3c46us9），整轮会话撞 2h 墙钟给
`Agent 已中止：构建环境异常终止，或流水线超过最大运行时长（2h）。`
（实测 cnb-m74-1k3cm87o9）。此前判据只认前者，于是后者整格 `skipped`，
222 轮里改而未提交的成果随容器一起丢。

用法：
    python scripts/ci/npc_turn_handoff_gate.py          # 人类可读
    python scripts/ci/npc_turn_handoff_gate.py --json   # 机器可读

## 为什么同一份脚本要能跑在 node 上

NPC 流水线的镜像（`cnbcool/default-npc:latest`）里**没有 python**，故本脚本自带
**逐字等价**的 node 分支：判据、读数键名、退出码三处都不因解释器而漂移。
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

from pathlib import Path

#: 工作区自证所用的临时文件名（写完即删，不是任何判据的落点）。
#: 它与流水线的其它环节没有约定关系——保留仅为让自证可被人眼核对。
PROBE_MARKER_FILE = ".npc-workspace-probe"

def resolveWorkspaceRoot(env: dict) -> str:
    """工作区根：环境变量给定，未给定返回空串。"""
    return (env.get("CNB_BUILD_WORKSPACE") or "").strip()


def checkWorkspaceWritable(root: str) -> dict:
    """在给定根下写探针文件并读回，证明工作区真的可写。"""
    marker = Path(root) / PROBE_MARKER_FILE
    marker.write_text("1", encoding="utf-8")
    try:
        readback = marker.read_text(encoding="utf-8").strip()
    finally:
        marker.unlink(missing_ok=True)
    return {"marker": str(marker), "readback": readback, "ok": readback == "1"}


def checkWorkingDirectory(env: dict, cwd: str) -> dict:
    """反向自证：`$PWD` 与 `$CNB_BUILD_WORKSPACE` 是否同一个地方。"""
    root = resolveWorkspaceRoot(env)
    return {
        "pwd": cwd,
        "cnb_build_workspace": root,
        "identical": bool(root) and Path(root).resolve() == Path(cwd).resolve(),
    }


def evaluate(env: dict, cwd: str) -> tuple[dict, list]:
    """判据本体：产出 (读数, 失败项)，供 python 与 node 两个入口共用同一口径。"""
    root = resolveWorkspaceRoot(env)
    failures: list = []
    result: dict = {"env_cnb_build_workspace": root or None}

    if not root:
        failures.append(
            "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 工作区没有落点，"
            "Agent 与各 Stage 都无从确认自己在哪写文件"
        )
    elif not Path(root).is_dir():
        failures.append(f"CNB_BUILD_WORKSPACE 指向的目录不存在: {root}")
    else:
        try:
            result["marker_check"] = checkWorkspaceWritable(root)
            if not result["marker_check"]["ok"]:
                failures.append(
                    f"{PROBE_MARKER_FILE} 写入后读不回原值 —— 工作区不可靠，"
                    "Agent 的改动可能落不下来"
                )
        except OSError as exc:
            failures.append(f"{PROBE_MARKER_FILE} 写入失败: {type(exc).__name__}: {exc}")

    result["working_directory_check"] = checkWorkingDirectory(env, cwd)
    if root and not result["working_directory_check"]["identical"]:
        result["working_directory_divergence"] = (
            "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：按字面理解「工作目录」"
            "会写到另一个地方，这是一份可读的读数"
        )
    return result, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="NPC 流水线开工前可达性自证")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    result, failures = evaluate(os.environ, os.getcwd())

    if args.json:
        print(json.dumps({"result": result, "failures": failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    lines = ["=" * 72, "NPC 流水线开工前可达性自证", "=" * 72]
    lines += [f"  {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in result.items()]
    if failures:
        lines += ["", "=" * 72, f"❌ 开工前自证不通过（{len(failures)} 项）："]
        lines += [f"  - {item}" for item in failures]
        sys.stdout.write("\n".join(lines) + "\n")
        return 1
    lines += ["", "✅ 开工前自证通过：工作区可写、解释器可用"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


NODE_IMPLEMENTATION = r"""
#!/usr/bin/env node
// 与 Python 分支逐字等价的实现（同判据、同读数键名、同退出码）。
// 存在理由：NPC 流水线镜像里没有 python，见模块 docstring
// 「为什么同一份脚本要能跑在 node 上」。
const fs = require("fs");
const path = require("path");

const PROBE_MARKER_FILE = ".npc-workspace-probe";

// 与 Python 的 json.dumps 对齐：缩进 2 空格、**不**转义非 ASCII、
// 字符串外的空格与 Python 的 separators 一致（", " / ": "）。
function pythonJsonScalar(value) {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function pythonJson(value, indent = 0) {
  if (indent < 0) {
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
  if (typeof value === "string") return JSON.stringify(value);
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
  const marker = path.join(root, PROBE_MARKER_FILE);
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

function evaluate(env, cwd) {
  const root = resolveWorkspaceRoot(env);
  const failures = [];
  const result = { env_cnb_build_workspace: root || null };

  if (!root) {
    failures.push(
      "环境变量 CNB_BUILD_WORKSPACE 缺失 —— 工作区没有落点，" +
      "Agent 与各 Stage 都无从确认自己在哪写文件");
  } else if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    failures.push("CNB_BUILD_WORKSPACE 指向的目录不存在: " + root);
  } else {
    const check = checkWorkspaceWritable(root);
    result.marker_check = { marker: check.marker, readback: check.readback, ok: check.ok };
    if (check.failReason) {
      failures.push(PROBE_MARKER_FILE + " 写入失败: " + check.failReason);
    } else if (!check.ok) {
      failures.push(
        PROBE_MARKER_FILE + " 写入后读不回原值 —— 工作区不可靠，" +
        "Agent 的改动可能落不下来");
    }
  }

  result.working_directory_check = checkWorkingDirectory(env, cwd);
  if (root && !result.working_directory_check.identical) {
    result.working_directory_divergence =
      "PWD 与 CNB_BUILD_WORKSPACE 不是同一目录：按字面理解「工作目录」" +
      "会写到另一个地方，这是一份可读的读数";
  }
  return { result, failures };
}

function main(argv) {
  const asJson = argv.includes("--json");
  const { result, failures } = evaluate(process.env, process.cwd());

  if (asJson) {
    console.log(pythonJson({ result, failures }, 0));
    return failures.length ? 1 : 0;
  }

  const lines = ["=".repeat(72), "NPC 流水线开工前可达性自证", "=".repeat(72)];
  for (const [key, value] of Object.entries(result)) {
    lines.push("  " + key + ": " + pythonJson(value, -1));
  }
  if (failures.length) {
    lines.push("");
    lines.push("=".repeat(72));
    lines.push("❌ 开工前自证不通过（" + failures.length + " 项）：");
    for (const item of failures) {
      lines.push("  - " + item);
    }
    process.stdout.write(lines.join("\n") + "\n");
    return 1;
  }
  lines.push("");
  lines.push("✅ 开工前自证通过：工作区可写、解释器可用");
  process.stdout.write(lines.join("\n") + "\n");
  return 0;
}

process.exit(main(process.argv.slice(2)));
"""


if __name__ == "__main__":
    # 只在作为进程运行时重配控制台：本文件会被 `test_deploy_config_guard.py` 之类
    # 用 importlib 在 pytest 进程内加载，模块级 reconfigure 等于改宿主进程的捕获流。
    # 中文 Windows 的 cp936 编不出 ⚠️/🛑/→，`print` 会抛 UnicodeEncodeError 把门禁自己打死
    # （Linux CI 看不见这条）。同仓先例 scripts/ci_static_gate.py 是模块级——它不被 import。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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
