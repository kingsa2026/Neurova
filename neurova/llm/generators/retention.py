# -*- coding: utf-8 -*-
"""C3：data/generations 产物保留清理（账本驱动，保守开关）。

规则（台账 C3，只提升不下降）：
- `NEUROVA_GENERATION_RETENTION_DAYS` 默认 **0=关闭**——开启权在用户；
- 仅删「账本终态（done/failed）+ 超期 + local_path 位于产物目录内」的文件；
  **账本行永不删**（历史面板据 local_path 存在性显示已过期态）；
- Studio 库（storyboards/characters/assets/episodes/merges）在引用的路径一律
  保护；Studio 库读取失败 → 整轮放弃（宁可不清，不冒删用在产物之险）；
- 纯账本驱动：产物目录里无账本记录的文件不碰；
- 启动后台任务执行（与 ffmpeg bootstrap 同款不阻塞；同步文件 IO 走
  to_thread，不占事件循环——2026-09-09 全库审计主线教训）。
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional, Set

from neurova.core.logger import get_logger

from .task_ledger import GenerationTaskLedger, TaskRecord, get_generation_task_ledger

logger = get_logger(__name__)

ENV_DAYS = "NEUROVA_GENERATION_RETENTION_DAYS"
_TERMINAL = ("done", "failed")

# Studio 库中代表"产物被引用"的 (表, 列) 组合
_REF_COLUMNS = [
    ("storyboards", "first_frame_path"), ("storyboards", "end_frame_path"),
    ("storyboards", "video_path"), ("storyboards", "audio_path"),
    ("characters", "image_path"), ("assets", "ref_path"),
    ("episodes", "video_path"), ("episodes", "subtitle_path"),
    ("merges", "output_path"),
]


def retention_days() -> int:
    try:
        return max(0, int(os.environ.get(ENV_DAYS, "0") or "0"))
    except ValueError:
        return 0


def collect_referenced_paths(db_path: Optional[str] = None) -> Optional[Set[str]]:
    """Studio 全库产物引用集合；读取失败返回 None（触发整轮放弃）。"""
    from neurova.aigc_studio.store import DEFAULT_DB_PATH

    path = db_path or str(DEFAULT_DB_PATH)
    if not Path(path).is_file():
        # 从未建过 Studio 库 = 无引用；但区分"不存在"与"损坏"：
        # 文件不存在可安全视为无引用
        return set()
    refs: Set[str] = set()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for table, col in _REF_COLUMNS:
                try:
                    for (v,) in conn.execute(
                            f"SELECT {col} FROM {table} WHERE {col} != ''"):
                        if v:
                            refs.add(str(v))
                except sqlite3.OperationalError:
                    # 列缺失（老库未迁移）→ 该表引用不可信，整轮放弃
                    return None
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return refs


def purge_expired_files(
    ledger: GenerationTaskLedger,
    referenced: Optional[Set[str]],
    days: int,
    out_dir: Path,
    now: Optional[float] = None,
) -> Dict[str, object]:
    """执行一轮清理（纯函数式参数便于测试注入）。"""
    stats: Dict[str, object] = {"scanned": 0, "deleted": 0,
                                "skipped_protected": 0, "skipped_outside": 0}
    if days <= 0:
        stats["disabled"] = True
        return stats
    if referenced is None:
        stats["aborted"] = True
        logger.warning("Studio 引用不可读，本轮产物清理放弃（保守不删）")
        return stats
    cutoff = (now or time.time()) - days * 86400.0
    out_resolved = Path(out_dir).resolve()
    for rec in ledger.list():
        if rec.status not in _TERMINAL or not rec.local_path:
            continue
        stats["scanned"] = int(stats["scanned"]) + 1
        if rec.updated_at >= cutoff:
            continue
        p = Path(rec.local_path)
        try:
            rp = p.resolve()
        except OSError:
            continue
        # 安全守卫：仅产物目录内的文件可删；目录外一律拒删（账本行保留）
        if not str(rp).startswith(str(out_resolved)):
            stats["skipped_outside"] = int(stats["skipped_outside"]) + 1
            continue
        if str(p) in referenced or str(rp) in referenced:
            stats["skipped_protected"] = int(stats["skipped_protected"]) + 1
            continue
        try:
            if rp.is_file():
                rp.unlink()
                stats["deleted"] = int(stats["deleted"]) + 1
        except OSError as e:  # 占用/权限：跳过留痕，账本与文件状态自洽
            logger.debug("产物删除跳过(%s): %s", rp, e)
    return stats


def _purge_once() -> Dict[str, object]:
    from .runtime import GENERATION_OUTPUT_DIR

    days = retention_days()
    stats = purge_expired_files(
        get_generation_task_ledger(), collect_referenced_paths(),
        days, GENERATION_OUTPUT_DIR)
    if stats.get("deleted"):
        logger.info("产物保留清理（%s 天）：删 %s/%s（保护引用 %s）",
                    days, stats["deleted"], stats["scanned"],
                    stats["skipped_protected"])
    return stats


def start_retention_bootstrap() -> Optional[asyncio.Task]:
    """启动后台清理（每进程一轮；开关关闭返回 None）。"""
    days = retention_days()
    if days <= 0:
        return None

    async def _bg() -> None:
        try:
            # 延后一拍让恢复轮询先回填 running 任务，避免误删未收口产物
            await asyncio.sleep(5)
            await asyncio.to_thread(_purge_once)
        except Exception as e:  # noqa: BLE001 — 清理失败不炸服务
            logger.warning("产物保留清理后台任务异常（忽略）: %s", e)

    task = asyncio.create_task(_bg(), name="generation-retention")
    logger.info("产物保留清理已排队（后台，保留 %s 天）", days)
    return task
