# -*- coding: utf-8 -*-
"""知识摄取异步 worker handler（P1 #9）。

处理一个已 claim 的 ingress 事件：upload 读暂存文件 / url 经注入的 fetch
拉字节 → 复用端点抽取函数 `_import_file_data`（同一事实代码，异步只是换
执行时机与线程）→ ack 记录 item_ids / nack 重试。

依赖注入式（fetch_fn/importer 参数）：可测；图谱抽取异步路径不执行
（Request/app-state 依赖），结果如实标 skipped_async——需要图谱联动走
sync=true。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def process_ingress_event(
    event: Dict[str, Any],
    *,
    importer: Callable[[bytes, str, str, Dict[str, Any]], Tuple[List[Dict[str, Any]], str]],
    fetch_fn: Optional[Callable[[str], bytes]] = None,
) -> Dict[str, Any]:
    """执行一个摄取事件。返回 {ok, item_ids?, status, graph, error?}。"""
    source = event.get("source")
    agent_id = event.get("agent_id") or "default"
    user = {"user_id": event.get("user_id") or "", "role": "user"}
    try:
        if source == "upload":
            path = Path(event.get("storage_path") or "")
            if not path.exists():
                return {"ok": False, "error": "暂存文件缺失（可能被清理），请重新上传", "status": "file_missing"}
            data = path.read_bytes()
            items, extract_status = importer(data, event.get("filename") or "imported", agent_id, user)
        elif source == "url":
            if fetch_fn is None:
                return {"ok": False, "error": "URL 抓取通道未注入", "status": "no_fetch"}
            data = fetch_fn(event.get("url") or "")
            items, extract_status = importer(data, event.get("filename") or "web", agent_id, user)
        else:
            return {"ok": False, "error": f"未知来源: {source}", "status": "bad_source"}
    except Exception as e:  # noqa: BLE001 - 交 nack 重试/死信
        logger.warning("知识摄取任务失败 task=%s: %s", event.get("task_id"), e)
        return {"ok": False, "error": str(e), "status": "handler_error"}

    if not items:
        # 抽取失败（.ppt 旧格式/纯图片页等）：确定性失败不重试
        return {"ok": False, "error": f"extract_failed:{extract_status}", "status": "extract_failed", "retry": False}
    return {
        "ok": True,
        "item_ids": [str(i.get("knowledge_id") or "") for i in items],
        "status": "done",
        "graph": "skipped_async",
    }


async def run_ingress_drain(poll_interval: float = 1.0) -> None:
    """知识摄取队列排水循环（app lifespan 背景任务，P1-#9）。

    claim → to_thread 执行 handler（解析是秒级重活，不得占事件循环）→
    ack / nack（可重试）/ dead（确定性失败）。端点函数惰性 import 防循环依赖。
    """
    import asyncio

    from neurova.knowledge.ingest_queue import get_ingress_queue

    queue = get_ingress_queue()
    queue.reconcile_at_startup()
    while True:
        try:
            ev = await asyncio.to_thread(queue.claim, "drain")
        except Exception:  # noqa: BLE001 - 队列故障退避重试，循环不死
            logger.warning("ingress claim 异常（退避）", exc_info=True)
            await asyncio.sleep(max(1.0, poll_interval))
            continue
        if ev is None:
            await asyncio.sleep(poll_interval)
            continue
        try:
            from neurova.api.endpoints.knowledge import _fetch_url, _import_file_data

            result = await asyncio.to_thread(
                process_ingress_event, ev,
                importer=_import_file_data, fetch_fn=_fetch_url,
            )
        except Exception as e:  # noqa: BLE001 - 依赖装配异常按可重试处理
            result = {"ok": False, "error": str(e), "status": "wiring_error", "retry": True}
        if result.get("ok"):
            await asyncio.to_thread(queue.ack, ev["task_id"], result.get("item_ids") or [])
        elif result.get("retry", True):
            await asyncio.to_thread(queue.nack, ev["task_id"], str(result.get("error") or result["status"]))
        else:
            await asyncio.to_thread(queue.dead, ev["task_id"], str(result.get("error") or result["status"]))
