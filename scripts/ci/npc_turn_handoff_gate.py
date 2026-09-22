#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 轮数触顶接力门禁（Issue #145）。

## 为什么需要这道门禁

`npc:go` 撞到 `maxTurns` 时，平台只是把 Agent 中止、把流水线判为失败，
**不会**读这个中止事件、更不会重开一轮预算（构建 cnb-2e8-1k341d9s1 实测：
3191326ms 后 Stage 以 `Agent aborted: reached maxTurns limit (200)` 收场，
而同一份配置里的接力 Stage 被 skipper 跳过，Issue 上没有任何回音）。
所以「撞顶之后把活交给下一轮」必须在配置里显式写出来。

配置里已经写了这笔接力（`.cnb.yml` 的 `endStages` + `cnb:apply`），
但接力的**燃料**是 Agent 在最后一轮自己写出的标记文件。标记写不出来，
`cnb:apply` 的 `if` 恒假，接力就是一条死配置 —— 而这类"看着配了、
其实永不触发"的形态平台不会报任何错。

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

    if args.json:
        print(json.dumps({"result": result, "failures": failures}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 72)
    print("NPC 轮数触顶接力门禁")
    print("=" * 72)
    for key, value in result.items():
        print(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    if failures:
        print("\n" + "=" * 72)
        print(f"❌ 接力判据不可达（{len(failures)} 项）：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n✅ 接力判据可达：收尾阶段能读到标记文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
