# -*- coding: utf-8 -*-
"""v2→v3 agent 布局一次性切换（后端停止后执行）。

用法：
    python scripts/migrate_agent_layout_v3.py             # 全量
    python scripts/migrate_agent_layout_v3.py --owner u1  # 仅该属主
    python scripts/migrate_agent_layout_v3.py --dry-run   # 干跑

把 data/<agent_id>/ 平铺目录搬进 data/agent/<属主桶>/<agent_id>/（属主取
agent_config.json 的 owner_user_id，空 → share 桶），写 agent_id→桶 索引，
全量完成后写哨兵 data/agent/.v3migration.done。只搬不删。

必须在后端**停止**后运行：运行中的后端持有各 agent 的 sqlite/工作区句柄，
目录搬移会被操作系统拒绝（Windows WinError 32/5）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from neurova.core.agent_layout_migration import (  # noqa: E402
    agent_owner_of,
    migrate_agent_layout_v3,
)
from neurova.core.agent_workspaces import discover_agent_ids  # noqa: E402


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="v2→v3 agent 布局切换（后端停止后执行）")
    parser.add_argument("--owner", default="", help="仅迁移该属主的 agent（缺省全量）")
    parser.add_argument("--dry-run", action="store_true", help="只出计划不搬移")
    args = parser.parse_args(argv)

    agent_ids = None
    if args.owner:
        agent_ids = [a for a in discover_agent_ids() if agent_owner_of(a) == args.owner]
        if not agent_ids:
            print(f"属主 {args.owner} 名下没有待迁移 agent")
            return 0

    report = migrate_agent_layout_v3(agent_ids=agent_ids, dry_run=args.dry_run)
    counts = report.get("counts", {})
    print("moved=%(moved)s pending=%(pending)s conflicts=%(conflicts)s "
          "errors=%(errors)s skipped=%(skipped)s" % {k: counts.get(k, 0) for k in
          ("moved", "pending", "conflicts", "errors", "skipped")})
    for err in report.get("errors", []):
        print("error:", err)
    for item in report.get("pending", []):
        print("pending:", item.get("agent_id"), "-", item.get("reason"))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
