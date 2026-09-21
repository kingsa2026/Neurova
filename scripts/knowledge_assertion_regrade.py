#!/usr/bin/env python3
"""存量断言归正入口：补链位 + 落校验结论（Issue #75 / 审计 2026-09-21 §6.6）。

为什么需要它：`attest()` 已能逐条裁决并回写 `verification_state`，但它只对**当轮
碰过的**活动跑（校验是写入的收尾动作）。上链机制落地之前写下的存量行因此一直停在
`unverified`——读数上它们和"验过没过"分不开。本入口就是那次重放。

判据与动作都在 `neurova/knowledge/foundation/digest_chain.py`
（`relinkUnlinked()` / `attest()`），本文件只做入口与打印。

用法：
    python scripts/knowledge_assertion_regrade.py            # 只预报（默认）
    python scripts/knowledge_assertion_regrade.py --apply     # 落手并落库
    python scripts/knowledge_assertion_regrade.py --db <path> # 指向指定底座库

默认只读：先报"有多少条待补链、当前三态分布"，确认后再加 `--apply`。
落手前自动把整库复制成 `.pre-regrade-<stamp>`（含 `-wal` / `-shm`），可回退。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 围栏是 pytest-only 的；运维动作必须显式摘标记。
os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ.pop("PYTEST_VERSION", None)

from neurova.knowledge.foundation.digest_chain import ActivityDigestChain  # noqa: E402
from neurova.knowledge.foundation.knowledge_facts import (  # noqa: E402
    DEFAULT_FACT_DB,
    KnowledgeFactStore,
)


def _unlinkedCount(store: KnowledgeFactStore) -> int:
    with store._lock:
        row = store._conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_assertions"
            " WHERE (digest = '' OR digest IS NULL) AND activity_id IS NOT NULL"
            "  AND activity_id <> ''").fetchone()
    return int(row["n"])


def _archive(dbPath: str) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = "%s.pre-regrade-%s" % (dbPath, stamp)
    shutil.copy2(dbPath, target)
    for suffix in ("-wal", "-shm"):
        side = dbPath + suffix
        if os.path.exists(side):
            shutil.copy2(side, target + suffix)
    return target


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description="存量断言归正（默认只预报）")
    parser.add_argument("--apply", action="store_true", help="落手并落库")
    parser.add_argument("--db", default=DEFAULT_FACT_DB, help="底座库路径")
    args = parser.parse_args(argv[1:])

    if not Path(args.db).exists():
        print("底座库不存在：%s——没有可归正的权威" % args.db)
        return 1

    archive = _archive(args.db) if args.apply else ""
    store = KnowledgeFactStore(args.db)
    try:
        chain = ActivityDigestChain(store)
        unlinked = _unlinkedCount(store)
        before = store.assertionVerificationCounts()
        linked = chain.relinkUnlinked() if args.apply else 0
        report = chain.attest() if args.apply else {"verification": before}
    finally:
        store.close()

    out = {"db": args.db, "mode": "apply" if args.apply else "dry_run",
           "archive": archive, "unlinked_before": unlinked, "linked": linked,
           "verification_before": before, "verification_after": report["verification"]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\n（预报模式，未改动任何行；确认无误后加 --apply 落手）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
