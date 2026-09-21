#!/usr/bin/env python3
"""历史记忆污染清空的运维入口（Issue #75 / 审计 2026-09-21 §7）。

用法：
    python scripts/memory_pollution_purge.py                # 只预报（默认）
    python scripts/memory_pollution_purge.py --apply         # 落手（先归档再删）
    python scripts/memory_pollution_purge.py --json          # 机器可读报告

默认只读。落手会把整库（含 `-wal` / `-shm`）归档成 `<name>.pre-purge-<stamp>`
再删——把归档副本改回原名即可回退。判据与动作都在
`neurova/cognitive_layers/memory_layer/pollution_purge.py`，本文件只做入口与打印。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 围栏是 pytest-only 的；本脚本是运维动作，必须显式摘标记（与
# scripts/diagnostics/_kb_backfill_rerun.py 同一处置）。
import os  # noqa: E402

os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ.pop("PYTEST_VERSION", None)

from neurova.cognitive_layers.memory_layer.pollution_purge import (  # noqa: E402
    MemoryPollutionPurge,
)


def _printPlan(report: dict) -> None:
    print("扫描根：%s" % ", ".join(report["roots"]))
    print("合法根（其中数据一律保留）：%s" % ", ".join(report["legal_roots"]))
    if not report.get("strays"):
        print("未发现历史污染。")
    for item in report.get("strays", []):
        rows = item["rows"]
        print("\n- %s" % item["path"])
        print("  原因：%s" % item["reason"])
        print("  行数：总 %d / 残留 %d / 保留 %d" % (rows["total"], rows["matched"], rows["kept"]))
        if rows["by_pattern"]:
            print("  按命名：%s" % ", ".join(
                "%s=%d" % (k, v) for k, v in sorted(rows["by_pattern"].items())))
        if rows["sample_ids"]:
            print("  样例 agent_id：%s" % ", ".join(rows["sample_ids"][:5]))
    for path in report.get("empty_shell_dirs", []):
        print("\n- 空壳目录：%s" % path)
    print("\n合计残留行 %d，占 %d 字节" % (report["residue_rows"], report["bytes"]))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="历史记忆污染清空（默认只预报）")
    parser.add_argument("--apply", action="store_true", help="落手删除（先归档，可回退）")
    parser.add_argument("--json", action="store_true", help="输出机器可读报告")
    args = parser.parse_args(argv[1:])

    purge = MemoryPollutionPurge()
    if args.json:
        report = purge.apply(dryRun=not args.apply)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.apply:
        report = purge.apply(dryRun=False)
        print("扫描根：%s" % ", ".join(report["roots"]))
        for action in report["actions"]:
            print("[%s] %s → 归档 %s" % (action["action"], action["path"],
                                        action.get("archive", "-")))
        for path in report["removed_empty_shell_dirs"]:
            print("[空壳目录] %s 已移除" % path)
        print("合计移除残留行 %d，删除文件 %d 个"
              % (report["residue_rows_removed"], report["files_removed"]))
        return 0
    _printPlan(purge.apply(dryRun=True))
    print("\n（预报模式，未改动任何文件；确认无误后加 --apply 落手）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
