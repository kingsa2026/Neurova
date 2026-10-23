"""知识索引周期维护：TF-IDF 分片增量自愈 + 向量分片 ensure/可选全量重算。

周期循环默认 force=False（应用 pending、清陈旧/删除项、引擎变更时重建）；
全量重算只在管理员显式 `POST /knowledge/audit/reindex {"force": true}` 时做。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MAINTENANCE_ENV = "NEUROVA_KB_INDEX_MAINTENANCE"
INTERVAL_ENV = "NEUROVA_KB_INDEX_MAINTENANCE_INTERVAL"
DEFAULT_INTERVAL_SECONDS = 3600


def maintainKnowledgeIndexes(
    force: bool = False,
    repo: Any = None,
    vector: Any = None,
) -> Dict[str, Any]:
    if repo is None:
        from neurova.knowledge.repository import get_knowledge_repository

        repo = get_knowledge_repository()
    if vector is None:
        from neurova.knowledge.vector_index import get_knowledge_vector_index

        vector = get_knowledge_vector_index()
    return {
        "force": bool(force),
        "repository": repo.maintainIndexes(force=force),
        "vector": vector.maintainAll(repo, force=force),
    }


def _intervalSeconds() -> int:
    try:
        value = int(os.environ.get(INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(60, value)


async def run_knowledge_index_maintenance_loop(
    intervalSeconds: Optional[int] = None,
) -> None:
    interval = max(60, int(intervalSeconds or _intervalSeconds()))
    while True:
        await asyncio.sleep(interval)
        try:
            result = await asyncio.to_thread(maintainKnowledgeIndexes, False)
            logger.info(
                "知识索引周期维护完成：repo=%s vector=%s",
                result["repository"], result["vector"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 周期任务失败下轮再试，不顶住进程
            logger.warning("知识索引周期维护失败（下轮重试）: %s", exc)
