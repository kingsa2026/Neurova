#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本目录的守卫钩子装进 git hooks 目录。

**不设 core.hooksPath**：仓里 `.git/hooks/pre-push` 已被 git-lfs 占用，改 hooksPath
会把它一并屏蔽（教义第 5 条：动一处挂点前先看清上面的既有住客）。本安装器只复制
`commit-msg` / `pre-commit` 两个文件；碰到同名异容的既有钩子时**报错让位**，
绝不静默覆盖别人的钩子。

用法：
    python scripts/githooks/install.py                  # 装进当前仓的 .git/hooks
    python scripts/githooks/install.py --hooks-dir DIR  # 指定目录（测试与 CI 用）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 本脚本是入口档（仅 `python scripts/githooks/install.py` 直跑，不被 import）：
# 中文 print 在 cp936 宿主上会把退出码打成本档的 1，出口先钉 utf-8（§6-496）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

#: 本工具管理的钩子名单。只装这两个，其余一律不碰。
MANAGED_HOOKS = ("commit-msg", "pre-commit")
#: 归属标记：两个壳的注释里都有这句（指向判据唯一出处）。dst 带它＝本工具的旧版，
#: 允许就地覆盖更新；不带＝别人的钩子，动它之前必须人工拍板。
_OWNERSHIP_MARK = "判据唯一出处"


def install(hooksDir: Path) -> list:
    """安装/更新本工具的钩子，返回本次实际写入的名字（幂等：已同版则跳过）。"""
    srcDir = Path(__file__).resolve().parent
    installed = []
    for name in MANAGED_HOOKS:
        src = srcDir / name
        dst = hooksDir / name
        if dst.exists():
            srcText = src.read_text(encoding="utf-8", errors="replace")
            dstText = dst.read_text(encoding="utf-8", errors="replace")
            if dstText == srcText:
                continue  # 已是本工具当前版，幂等跳过
            if _OWNERSHIP_MARK not in dstText:
                raise RuntimeError(
                    f"{dst} 已存在且不是本工具的旧版（可能是别的工具装的）。"
                    "请人工确认后处理，本安装器不覆盖别人的钩子。")
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o755)
        installed.append(name)
    return installed


def main(argv=None) -> int:
    defaultRepo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="安装修复教义守卫钩子")
    parser.add_argument("--hooks-dir", default=None, help="目标 hooks 目录；缺省用当前仓的 .git/hooks")
    args = parser.parse_args(argv)
    if args.hooks_dir:
        hooksDir = Path(args.hooks_dir)
    else:
        repo = defaultRepo
        proc = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
        if proc.returncode != 0:
            print(f"定位 hooks 目录失败：{proc.stderr.strip()}", file=sys.stderr)
            return 1
        hooksDir = (repo / proc.stdout.strip()).resolve()
    hooksDir.mkdir(parents=True, exist_ok=True)
    installed = install(hooksDir)
    print(f"[钩子安装] {'新增 ' + ', '.join(installed) if installed else '均已是当前版（无变化）'} → {hooksDir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
