#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPC 角色准入（Issue #272）—— 被 @ 的角色名必须在册，不在册就不烧 token。

## 为什么需要它

平台按**角色名**解析人设：名字命中 `.cnb/settings.yml` 的 `npc.roles[].name` 时
拿到本仓的人设与修复教义；**未命中时静默回落** —— 不报错、不告警，
用户以为切了角色，实际拿到的是平台默认 prompt。本仓 90+ 处引用「AGENTS.md 修复教义第 N 条」
的约束随之全部失效，而没有任何一处会响亮。

本仓还额外有一条同型风险：全部在册角色都落到 `.cnb.yml` 的 `$` 兜底挂载点
（角色名顶层 key 在平台 Schema 里是非法配置），所以「名字写错了会不会仍然跑起来」
这件事只能靠本脚本作答。

## 口径：名单只有一处事实源

名单事实源是 `.cnb/settings.yml` 的 `npc.roles`（角色名唯一权威），
本脚本**不抄第二份**：它读同一份配置。`.cnb.yml` 也不再抄一份白名单 ——
此前那种「配置里一处名单、文档里一处名单、脚本里一处名单」的写法，
每次角色增删都要三处对齐，而漏一处不会有任何红。

## 为什么同一份脚本要能跑在 node 上

NPC 流水线的镜像（`cnbcool/default-npc:latest`）里**没有 python**，故本脚本自带
**逐字等价**的 node 分支（同一名单来源、同一判据、同一退出码），
经桥脚本 `scripts/ci/run_gate_under_node.sh` 执行。

用法：
    python scripts/ci/npc_role_admission.py
退出码：0 在册（或在非 NPC 环境里跑，不适用）；1 不在册（响亮失败，且不消耗 token）。
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

#: 角色名单的唯一事实源（相对仓库根）。
SETTINGS_RELATIVE_PATH = ".cnb/settings.yml"

#: 平台注入的角色名变量。
ROLE_ENV_VAR = "CNB_NPC_NAME"

def repositoryRoot() -> Path:
    """仓库根：优先取平台注入的构建工作区，回落到脚本位置回推。

    两个来源都是必要的：
      * `__file__` 回推（`scripts/ci/<file>` → 上溯两级）在**原地执行**时最准，
        但它对「脚本被复制到别处再执行」的形态无声失效 —— node 桥正是这种形态
        （把本文件的 node 实现写到临时目录再跑）；
      * `$CNB_BUILD_WORKSPACE` 是平台注入的工作区落点，两种形态下都成立。
    """
    workspace = (os.environ.get("CNB_BUILD_WORKSPACE") or "").strip()
    if workspace and Path(workspace).is_dir():
        return Path(workspace)
    return Path(__file__).resolve().parents[2]


def parseRoleNames(settings_text: str) -> list:
    """从 `.cnb/settings.yml` 的文本里取出在册角色名。

    只做**缩进级**解析：`npc.roles` 数组里每个 `- name: X` 的顶格深度由
    「该行的缩进恰好等于首个 `- name:` 行的缩进」确定。这样无需 YAML 依赖 ——
    NPC 镜像里没有 python 的第三方库，node 分支也不该被绑上一份 YAML 实现。

    解析不出任何角色名时返回空列表：调用方据此**响亮失败**，
    而不是静默放行（名单读不到时「在不在册」这个问题的答案未知，
    未知不等于通过）。
    """
    names: list = []
    for raw in settings_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if not stripped.startswith("- name:"):
            continue
        indent = len(raw) - len(raw.lstrip())
        name = stripped.split("- name:", 1)[1].strip().strip('"').strip("'")
        if not name:
            continue
        if not names:
            names.append(name)
            recorded_indent = indent
            continue
        if indent == recorded_indent:
            names.append(name)
    return names


def evaluate(env: dict, root: Path) -> tuple[bool, str]:
    """判据本体：产出 (是否通过, 说明)。python 与 node 两个入口共用同一口径。"""
    role = (env.get(ROLE_ENV_VAR) or "").strip()
    if not role:
        # 非 NPC 触发（或平台未注入角色名）时本判据不适用：点名跳过，不算失败。
        return True, (
            f"{ROLE_ENV_VAR} 未注入 —— 本条判据不适用（非角色触发的构建），点名跳过。"
        )

    config = root / SETTINGS_RELATIVE_PATH
    try:
        settings_text = config.read_text(encoding="utf-8")
    except OSError as exc:
        return False, (
            f"读不到角色名单事实源 {SETTINGS_RELATIVE_PATH}（{type(exc).__name__}: {exc}）——"
            "名单读不到时「是否在册」没有答案，按响亮失败处理。"
        )

    names = parseRoleNames(settings_text)
    if not names:
        return False, (
            f"{SETTINGS_RELATIVE_PATH} 里解析不到任何 `npc.roles` 角色名 ——"
            "名单为空时任何角色都不可能「在册」，按响亮失败处理。"
        )
    if role in names:
        return True, f"角色准入：{role} 在册（共 {len(names)} 个在册角色）。"
    return False, (
        f"角色准入失败：{role} 不在册，本轮不执行任何 AI 任务、也不消耗 token。\n"
        f"在册角色（事实源 {SETTINGS_RELATIVE_PATH} 的 npc.roles）：{' / '.join(names)}"
    )


#: node 分支的实现：与 Python 分支**逐字等价**（同一名单来源、同一判据、同一退出码）。
#: 它是本文件的第二运行时入口，不是第二份口径。
NODE_IMPLEMENTATION = r"""
const fs = require("fs");
const path = require("path");

const SETTINGS_RELATIVE_PATH = ".cnb/settings.yml";
const ROLE_ENV_VAR = "CNB_NPC_NAME";

function repositoryRoot() {
  // 桥脚本把本实现写到临时 `.js` 再执行，临时文件的目录**不是**仓库里的那一层，
  // 照 `__dirname/../..` 回推会落到文件系统根上。故优先用构建的工作区（平台注入），
  // 回落到进程工作目录 —— 桥与流水线都从仓库根调用本门禁。
  const workspace = String(process.env.CNB_BUILD_WORKSPACE || "").trim();
  if (workspace) return workspace;
  return process.cwd();
}

function parseRoleNames(settingsText) {
  const names = [];
  let recordedIndent = null;
  for (const raw of settingsText.split("\n")) {
    const stripped = raw.trim();
    if (stripped.startsWith("#")) continue;
    if (!stripped.startsWith("- name:")) continue;
    const indent = raw.length - raw.trimStart().length;
    let name = stripped.slice("- name:".length).trim();
    name = name.replace(/^["']|["']$/g, "");
    if (!name) continue;
    if (recordedIndent === null) {
      recordedIndent = indent;
      names.push(name);
      continue;
    }
    if (indent === recordedIndent) names.push(name);
  }
  return names;
}

function evaluate(env, root) {
  const role = String(env[ROLE_ENV_VAR] || "").trim();
  if (!role) {
    return [true, ROLE_ENV_VAR + " 未注入 —— 本条判据不适用（非角色触发的构建），点名跳过。"];
  }
  const config = path.join(root, SETTINGS_RELATIVE_PATH);
  let settingsText;
  try {
    settingsText = fs.readFileSync(config, "utf8");
  } catch (err) {
    return [false, "读不到角色名单事实源 " + SETTINGS_RELATIVE_PATH + "（" + err.code
      + "）——名单读不到时「是否在册」没有答案，按响亮失败处理。"];
  }
  const names = parseRoleNames(settingsText);
  if (!names.length) {
    return [false, SETTINGS_RELATIVE_PATH
      + " 里解析不到任何 `npc.roles` 角色名 ——名单为空时任何角色都不可能「在册」，按响亮失败处理。"];
  }
  if (names.includes(role)) {
    return [true, "角色准入：" + role + " 在册（共 " + names.length + " 个在册角色）。"];
  }
  return [false, "角色准入失败：" + role + " 不在册，本轮不执行任何 AI 任务、也不消耗 token。\n"
    + "在册角色（事实源 " + SETTINGS_RELATIVE_PATH + " 的 npc.roles）：" + names.join(" / ")];
}

const [ok, message] = evaluate(process.env, repositoryRoot());
process.stdout.write(message + "\n");
process.exit(ok ? 0 : 1);
"""


def main() -> int:
    ok, message = evaluate(dict(os.environ), repositoryRoot())
    print(message)
    return 0 if ok else 1


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
    sys.exit(main())
