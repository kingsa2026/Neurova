# -*- coding: utf-8 -*-
"""触发 Windows 自定义界面安装包构建（Issue #332，路线 A）。

流水线定义的**唯一事实源**是 `.cnb.yml` 的 `$:api_trigger_win_installer`。
本脚本不抄第二份 Job 体 —— 它把该子树从 `.cnb.yml` 里**读出来**当 `config`
发出去（`cnb build start-build --data`）。抄一份进脚本 = 立刻过期（教义第 6 条）。

用法（仓库根）：
    python scripts/desktop/trigger_win_installer.py
    python scripts/desktop/trigger_win_installer.py --sync
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
CNB_YML = REPO / ".cnb.yml"
EVENT = "api_trigger_win_installer"
SLUG = os.environ.get("CNB_REPO_SLUG", "kingsa2026/neurova")


def load_event_config() -> dict:
    doc = yaml.safe_load(CNB_YML.read_text(encoding="utf-8"))
    events = doc.get("$", {})
    if EVENT not in events:
        raise RuntimeError(f".cnb.yml 的 `$` 下没有 {EVENT} 事件（流水线未定义）")
    return {"$": {EVENT: events[EVENT]}}


def main() -> int:
    ap = argparse.ArgumentParser(description="触发 Windows 安装包构建")
    ap.add_argument("--repo", default=SLUG, help=f"仓库 slug（默认 {SLUG}）")
    ap.add_argument("--branch", default="main", help="触发分支（默认 main）")
    ap.add_argument("--sync", action="store_true", help="等待构建结束")
    args = ap.parse_args()

    body = json.dumps({
        "config": yaml.safe_dump(load_event_config(), allow_unicode=True, sort_keys=False),
        "event": EVENT,
        "branch": args.branch,
    }, ensure_ascii=False)

    cmd = ["cnb", "build", "start-build", "--repo", args.repo, "--data", body]
    if args.sync:
        cmd += ["--sync", "true"]
    print(f"[trigger] {args.repo} @ {args.branch} 事件 {EVENT}", flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
