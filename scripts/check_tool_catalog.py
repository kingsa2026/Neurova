# -*- coding: utf-8 -*-
"""工具目录快照 verify-diff 门（实施计划项 3，第一步）。

纪律同项 5：门不信任「记得改了」——它从 builtin_tools 声明位**重新推导**
工具目录（`neurova.tools.catalog.build_snapshot`），与
`contracts/tool_catalog.json` 逐字节比对；不一致即红，并点名差异路径。
新增/下线工具、改描述/参数/权限投影而不同步快照，此门必红。

用法：
    python scripts/check_tool_catalog.py                     # 比对仓库快照
    python scripts/check_tool_catalog.py --snapshot <path>   # 比对指定快照
    python scripts/check_tool_catalog.py --update            # 重新生成仓库快照

退出码：0 = 一致（或已更新）；1 = 漂移/快照缺失/推导失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.tools.catalog import build_snapshot, dump_snapshot  # noqa: E402
from scripts.check_openapi_snapshot import diffPaths  # noqa: E402  复用项 5 的 diff 判据（单一实现）

DEFAULT_SNAPSHOT_PATH = PROJECT_ROOT / "contracts" / "tool_catalog.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="工具目录快照 verify-diff 门（实施计划项 3）")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH), help="快照文件路径")
    parser.add_argument("--update", action="store_true", help="重新推导并写回快照（代替比对）")
    parser.add_argument("--max-print", type=int, default=50, help="最多打印的差异条数")
    args = parser.parse_args(argv)

    snapshotPath = Path(args.snapshot)

    try:
        current = build_snapshot()
    except Exception as exc:  # noqa: BLE001 - 推导失败必须红，不许静默
        print(f"[check_tool_catalog] 工具目录推导失败：{type(exc).__name__}: {exc}")
        return 1

    if args.update:
        snapshotPath.parent.mkdir(parents=True, exist_ok=True)
        snapshotPath.write_text(dump_snapshot(current), encoding="utf-8")
        print(f"[check_tool_catalog] 快照已更新：{snapshotPath}（{current['tool_count']} 个工具）")
        return 0

    if not snapshotPath.is_file():
        print(f"[check_tool_catalog] 快照不存在：{snapshotPath}")
        print("修法：python scripts/check_tool_catalog.py --update 生成并提交 contracts/tool_catalog.json")
        return 1

    try:
        stored = json.loads(snapshotPath.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 快照损坏必须红，不许静默
        print(f"[check_tool_catalog] 快照不是合法 JSON：{exc}")
        return 1

    diffs = diffPaths(current, stored)
    if not diffs:
        print(f"[check_tool_catalog] 快照与现网工具目录一致（{current['tool_count']} 个工具）")
        return 0

    shown = diffs[: max(args.max_print, 0)] if args.max_print > 0 else diffs
    print(
        f"[check_tool_catalog] 工具目录与快照不一致：共 {len(diffs)} 处差异"
        f"（先列 {len(shown)} 条）——快照没跟上代码："
    )
    for diff in shown:
        print("  " + diff)
    print("修法：python scripts/check_tool_catalog.py --update 重新导出，并把快照随本次改动一起提交")
    return 1


if __name__ == "__main__":
    sys.exit(main())
