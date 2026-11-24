# -*- coding: utf-8 -*-
"""D5-R6：存量记忆温度一次性初始化为 60°（后端停止后执行）。

用法：
    python scripts/reset_memory_temperature_60.py             # 全量重置
    python scripts/reset_memory_temperature_60.py --dry-run   # 只读预览

把所有 agent（v3 分桶布局 + v2 平铺遗留）的 memories 表温度统一重置为
BIRTH_TEMPERATURE（60）：旧数据大面积恒 100（出生默认 + ≥80 冻结门），
温度无区分度；重置后由真实使用（比例回温）与衰减重新塑形。只 UPDATE
temperature 一列，updated_at/last_accessed_at/access_count 一概不动。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from neurova.cognitive_layers.memory_layer.models import BIRTH_TEMPERATURE  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402

DB_NAME = "neurova_memories_persist.db"


def _discover_persist_dbs(data_root: Path) -> list:
    """发现全部记忆持久库：v3 分桶布局 + v2 平铺遗留（互不重叠）。"""
    dbs = set()
    for pattern in (
        str(Path("agent") / "*" / "*" / "memory" / DB_NAME),
        str(Path("*") / "memory" / DB_NAME),
    ):
        for p in data_root.glob(pattern):
            if p.is_file():
                dbs.add(p.resolve())
    return sorted(dbs)


def _has_memories_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'memories'"
    ).fetchone()
    return bool(row and row[0])


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="存量记忆温度一次性初始化为 60°（必须在后端停止后执行）"
    )
    parser.add_argument(
        "--data-root", default="", help="数据根目录（默认取 NEUROVA_DATA_DIR / 仓库 data）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args(argv)

    root = Path(args.data_root).resolve() if args.data_root else Path(get_data_root())
    dbs = _discover_persist_dbs(root)
    if not dbs:
        print(f"未发现任何 {DB_NAME}（root={root}）")
        return 0

    total = 0
    for db in dbs:
        conn = sqlite3.connect(str(db))
        try:
            if not _has_memories_table(conn):
                print(f"跳过（无 memories 表）: {db}")
                continue
            n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if args.dry_run:
                print(f"[dry-run] {db}: {n} 行将重置为 {BIRTH_TEMPERATURE}")
                total += n
                continue
            conn.execute("UPDATE memories SET temperature = ?", (BIRTH_TEMPERATURE,))
            conn.commit()
            print(f"{db}: 已重置 {n} 行 → {BIRTH_TEMPERATURE}")
            total += n
        except sqlite3.OperationalError as e:
            print(f"错误 {db}: {e}（库被占用？请先停止后端再执行）")
            return 1
        finally:
            conn.close()
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}合计 {total} 行 @ {BIRTH_TEMPERATURE}°，库 {len(dbs)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
