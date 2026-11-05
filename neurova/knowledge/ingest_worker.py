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

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.knowledge.repository import get_knowledge_repository

logger = get_logger(__name__)

#: 异步摄取抽取补偿的门控（SAG 对比候选 C2）：此前异步路径恒 skipped_async；
#: 默认 off＝旧行为（结果仍如实标 skipped），开闸后 ack 补跑抽取。
ENV_EXTRACT_ASYNC = "NEUROVA_KB_EXTRACT_ASYNC"


def extract_after_ingest(event: Dict[str, Any], item_ids: List[str]) -> str:
    """异步摄取完成后的图谱抽取补偿（SAG 对比候选 C2，2026-11-05）。

    此前异步路径恒 `skipped_async`（_try_extract_to_graph 依赖 Request/app
    state）——实际上 `_default_llm_call` 经 `get_app_state()` 生产可解析，
    request=None 即可走同一条管线。NEUROVA_KB_EXTRACT_ASYNC 门控（默认
    off＝旧行为）；条目从权威仓库取回（find_item），失败 fail-soft 返回
    状态串，绝不影响摄取 ack。
    """
    raw = str(os.environ.get(ENV_EXTRACT_ASYNC) or "").strip().lower()
    if raw not in ("1", "true", "on", "yes"):
        return "skipped_disabled"
    ids = [str(i) for i in (item_ids or []) if i]
    if not ids:
        return "skipped_empty"
    try:
        from neurova.api.endpoints.knowledge_common import _try_extract_to_graph

        items: List[Dict[str, Any]] = []
        for kid in ids:
            found = get_knowledge_repository().find_item(kid)
            if found:
                items.append(dict(found[1]))
        if not items:
            return "skipped_missing_items"
        _try_extract_to_graph(
            items, None,
            agent_id=str(event.get("agent_id") or "default"),
            tenant_id=str(event.get("tenant_id") or "default"),
        )
        return "extracted"
    except Exception as exc:  # noqa: BLE001 - 补偿失败不影响摄取主流程
        logger.warning("异步图谱抽取补偿失败（摄取已完成）: %s", exc)
        return "extract_error"


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
        # P1#12：span 时间线起点。claim 后任务转 processing，先记 parse=running；
        # 取消守卫：若已被 cancel_task 标 cancelled，跳过执行（ack/nack 侧也会拦截）。
        tid = ev["task_id"]
        if queue.is_cancelled(tid):
            continue
        queue.record_span(tid, "parse", "running")
        try:
            from neurova.api.endpoints.knowledge import _fetch_url, _import_file_data

            result = await asyncio.to_thread(
                process_ingress_event, ev,
                importer=_import_file_data, fetch_fn=_fetch_url,
            )
        except Exception as e:  # noqa: BLE001 - 依赖装配异常按可重试处理
            result = {"ok": False, "error": str(e), "status": "wiring_error", "retry": True}
        if result.get("ok"):
            queue.record_span(tid, "index", "running")
            await asyncio.to_thread(queue.ack, tid, result.get("item_ids") or [])
            # ack 后 is_cancelled 仍可能为真（在飞时用户取消）——span 如实反映
            cancelled = queue.is_cancelled(tid)
            queue.record_span(tid, "parse", "done" if not cancelled else "cancelled")
            queue.record_span(tid, "index", "done" if not cancelled else "cancelled")
            # C2 补偿：异步路径的图谱抽取（此前恒 skipped_async）。
            # NEUROVA_KB_EXTRACT_ASYNC 门控默认 off；span 如实记录补偿态。
            state = await asyncio.to_thread(
                extract_after_ingest, ev, result.get("item_ids") or []
            )
            queue.record_span(
                tid, "extract",
                "done" if state == "extracted" else "failed",
                error=None if state == "extracted" else state,
            )
        elif result.get("retry", True):
            await asyncio.to_thread(queue.nack, tid, str(result.get("error") or result["status"]))
            queue.record_span(tid, "parse", "failed", error=str(result.get("error") or result["status"]))
        else:
            await asyncio.to_thread(queue.dead, tid, str(result.get("error") or result["status"]))
            queue.record_span(tid, "parse", "failed", error=str(result.get("error") or result["status"]))
