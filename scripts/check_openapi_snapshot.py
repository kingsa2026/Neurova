# -*- coding: utf-8 -*-
"""契约快照 verify-diff 门：重新导出 API 形状并与快照 diff（实施计划项 5）。

对齐 Linger 的 verify 纪律：门不信任任何「记得改了」——它**重新导出**当前
API 形状，与 `contracts/openapi.snapshot.json` 逐字节比对；不一致即红，
并点名差异路径。任何 API 形状变更若不同步快照，此门必红。

用法：
    python scripts/check_openapi_snapshot.py                 # 比对仓库快照
    python scripts/check_openapi_snapshot.py --snapshot <p>  # 比对指定快照

退出码：0 = 一致；1 = 漂移/快照缺失/导出失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.export_openapi as export_openapi  # noqa: E402

DEFAULT_SNAPSHOT_PATH = export_openapi.DEFAULT_SNAPSHOT_PATH

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def loadSnapshot(path: Path) -> dict:
    """读取快照文件（JSON）。损坏即红——门不吞格式错误。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diffPaths(expected, actual, prefix: str = "") -> list:
    """结构化 diff，返回稳定排序的差异路径清单。

    `expected` 是重新导出的现网形状，`actual` 是仓库里的快照；
    差异路径形如 `openapi.paths./api/v1/agents.get.operationId: 'a' -> 'b'`。
    """
    if type(expected) is not type(actual):
        return [f"{prefix}: 类型 {type(expected).__name__} -> {type(actual).__name__}"]
    if isinstance(expected, dict):
        diffs = []
        for key in sorted(set(expected) | set(actual), key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in actual:
                diffs.append(f"{child}: 快照缺失（现网新增）")
            elif key not in expected:
                diffs.append(f"{child}: 现网已删除")
            else:
                diffs.extend(diffPaths(expected[key], actual[key], child))
        return diffs
    if isinstance(expected, list):
        diffs = []
        if len(expected) != len(actual):
            diffs.append(f"{prefix}: 长度 {len(expected)} -> {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            diffs.extend(diffPaths(left, right, f"{prefix}[{index}]"))
        return diffs
    if expected != actual:
        return [f"{prefix}: {expected!r} -> {actual!r}"]
    return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="契约快照 verify-diff 门（实施计划项 5）")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT_PATH), help="快照文件路径")
    parser.add_argument("--max-print", type=int, default=50, help="最多打印的差异条数")
    args = parser.parse_args(argv)

    snapshotPath = Path(args.snapshot)
    if not snapshotPath.is_file():
        print(f"[check_openapi_snapshot] 快照不存在：{snapshotPath}")
        print("修法：python scripts/export_openapi.py 生成并提交 contracts/openapi.snapshot.json")
        return 1

    try:
        stored = loadSnapshot(snapshotPath)
    except Exception as exc:  # noqa: BLE001 - 快照损坏必须红，不许静默
        print(f"[check_openapi_snapshot] 快照不是合法 JSON：{exc}")
        return 1

    try:
        current = export_openapi.buildSnapshot()
    except Exception as exc:  # noqa: BLE001 - 装配失败必须红，不许静默
        print(f"[check_openapi_snapshot] 现网 API 形状导出失败：{type(exc).__name__}: {exc}")
        return 1

    diffs = diffPaths(current, stored)
    if not diffs:
        print(f"[check_openapi_snapshot] 快照与现网 API 形状一致（mode={current.get('mode')}）")
        return 0

    shown = diffs[: max(args.max_print, 0)] if args.max_print > 0 else diffs
    print(
        f"[check_openapi_snapshot] API 形状与快照不一致：共 {len(diffs)} 处差异"
        f"（先列 {len(shown)} 条）——快照没跟上代码："
    )
    for diff in shown:
        print("  " + diff)
    print("修法：python scripts/export_openapi.py 重新导出，并把快照随本次改动一起提交")
    return 1


if __name__ == "__main__":
    sys.exit(main())
