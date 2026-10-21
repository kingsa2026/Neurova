#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""旧 agent 扁平落点 → `data/<agent_id>/` 统一布局的运维迁移脚本。

默认 dry-run（只出计划，不落盘）；确认后加 `--apply` 执行。
启动时也会自动执行同一迁移器（幂等），本脚本用于升级前预览与人工处置冲突。

用法：
    .venv/Scripts/python.exe scripts/agent_layout_migration.py
    .venv/Scripts/python.exe scripts/agent_layout_migration.py --apply
    .venv/Scripts/python.exe scripts/agent_layout_migration.py --legacy-workspace-root E:/old/agent_workspaces --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.core.agent_layout_migration import migrate_legacy_agent_layout  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 agent 旧布局到 data/<agent_id>/ 统一布局")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行搬迁；缺省只 dry-run 输出计划",
    )
    parser.add_argument(
        "--legacy-workspace-root",
        default=None,
        help="旧工作区根（缺省为仓库 agent_workspaces/；隔离部署可显式指定）",
    )
    parser.add_argument(
        "--sessions-root",
        default=None,
        help="旧会话根（缺省 data/sessions/ 或 NEUROVA_SESSIONS_DIR）",
    )
    args = parser.parse_args()

    report = migrate_legacy_agent_layout(
        legacy_workspace_root=args.legacy_workspace_root,
        sessions_root=args.sessions_root,
        dry_run=not args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
