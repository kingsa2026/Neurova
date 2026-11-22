# -*- coding: utf-8 -*-
"""生成任务收口轮询 + 重启恢复。

账本 ``unfinished()``（submitted/running 且有 remote_task_id）原本零调用方——
「重启后可恢复轮询」的承诺未接线（前端关页/服务重启后，远程视频任务无人认领，
产物 URL 过期即永丢）。本模块补上：

- ``settle_video_record``：单次轮询 + 成功即下载本地化 + 账本落态，REST
  ``/video/status`` 端点与后台恢复循环共用同一实现（口径单源）；
- ``recovery_tick``：扫账本逐条收口（provider 凭据缺失的旧任务诚实标失败，
  错误原文入账本，不静默滞留）；
- ``start/stop_generation_recovery``：随服务启动的 asyncio 轻量循环，
  间隔 ``NEUROVA_GENERATION_RECOVERY_SEC``（默认 60s）。
 不引入租约/看门狗（Neurova 单进程 uvicorn
  设计，此处过度工程，登记缓后）。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger
from neurova.llm.generators import protocols as protocols
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.llm.generators.runtime import (
    DEFAULT_WAN_BASE,
    GenerationCredsError,
    local_url_for,
    persist_media,
    resolve_generation_creds,
)
from neurova.llm.generators.task_ledger import (
    TASK_FAILED,
    TASK_RUNNING,
    TASK_SUCCEEDED,
    GenerationTaskLedger,
    TaskRecord,
    get_generation_task_ledger,
)

logger = get_logger(__name__)


async def settle_video_record(record: TaskRecord, ledger: Optional[GenerationTaskLedger] = None) -> Dict[str, Any]:
    """轮询一条视频任务一次并写账本。返回 {status, url?, error?}。"""
    return await _settle_media_record(
        record, ledger,
        poll=lambda creds: protocols.poll_video(creds, record.remote_task_id, record.poll_url),
        url_key="video_url", media_kind="video", default_base=DEFAULT_WAN_BASE)


async def settle_music_record(record: TaskRecord, ledger: Optional[GenerationTaskLedger] = None) -> Dict[str, Any]:
    """轮询一条音乐任务一次并写账本（M1；与视频收口同一实现口径）。"""
    return await _settle_media_record(
        record, ledger,
        poll=lambda creds: protocols.poll_music(creds, record.remote_task_id, record.poll_url),
        url_key="audio_url", media_kind="audio",
        default_base=protocols.DEFAULT_FAL_QUEUE_BASE)


async def _settle_media_record(
    record: TaskRecord,
    ledger: Optional[GenerationTaskLedger],
    poll,
    url_key: str,
    media_kind: str,
    default_base: str,
) -> Dict[str, Any]:
    """异步生成任务（视频/音乐）单次轮询收口的共用实现。

    差异只在三处：轮询函数、产物 URL 字段名、缺省 base——收口语义
    （凭据重取 / 落盘本地化 / 账本终态 / 用量入账）只有一份。
    """
    ledger = ledger or get_generation_task_ledger()
    creds = ProtocolCredentials(api_key="", base_url=record.base_url,
                                model=record.model, protocol=record.protocol)
    # 凭据：账本不落 api_key（敏感），轮询前按 provider_id 重新解析
    if record.provider_id:
        try:
            creds = resolve_generation_creds(
                record.protocol, record.model, record.provider_id, None, None,
                default_base=record.base_url or default_base,
            )
        except GenerationCredsError:
            pass
    try:
        result = await poll(creds)
    except Exception as e:  # noqa: BLE001
        result = {"status": TASK_FAILED, "error": str(e)[:300]}

    status = str(result.get("status") or TASK_RUNNING)
    if status == TASK_SUCCEEDED:
        media_url = result.get(url_key) or ""
        if media_url.startswith(("http", "data:")):
            try:
                path = await persist_media(media_url, media_kind, record.task_id, 0)
                ledger.update(record.task_id, status=TASK_SUCCEEDED, result_url=media_url,
                              local_path=path)
                _record_generation_usage(record, "success")
                delivered = local_url_for(path)
                await _archiveSettledToPool(record, delivered)
                return {"status": TASK_SUCCEEDED, "url": delivered}
            except Exception as e:  # noqa: BLE001 — 下载失败仍回成功+远端 URL（可能已过期）
                ledger.update(record.task_id, status=TASK_SUCCEEDED, result_url=media_url)
                _record_generation_usage(record, "success")
                await _archiveSettledToPool(record, media_url)
                return {"status": TASK_SUCCEEDED, "url": media_url,
                        "warning": f"本地化失败: {str(e)[:200]}"}
        ledger.update(record.task_id, status=TASK_SUCCEEDED, result_url=media_url)
        _record_generation_usage(record, "success")
        await _archiveSettledToPool(record, media_url)
        return {"status": TASK_SUCCEEDED, "url": media_url}
    if status == TASK_FAILED:
        err = str(result.get("error") or "")[:300]
        ledger.update(record.task_id, status=TASK_FAILED, error=err)
        _record_generation_usage(record, "failed")
        return {"status": TASK_FAILED, "error": err}
    ledger.update(record.task_id, status=TASK_RUNNING)
    return {"status": TASK_RUNNING}


def _record_generation_usage(record: TaskRecord, status: str) -> None:
    """L4：生成任务终态入账 AIGC 用量（kind 取账本行；写失败静默）。"""
    try:
        from neurova.core.aigc_usage import get_aigc_usage

        duration_ms = max(0.0, (time.time() - (record.submitted_at or time.time())) * 1000)
        get_aigc_usage().record(
            kind=record.kind or "video", user_id=record.owner_user_id or "",
            provider=record.provider_id, model=record.model,
            protocol=record.protocol, status=status,
            items=1 if status == "success" else 0, duration_ms=duration_ms)
    except Exception:  # noqa: BLE001 — 统计永不影响收口
        pass


async def _archiveSettledToPool(record: TaskRecord, url: str) -> None:
    """M9：收口成功的产物入活水池（会话归属随账本行携带；失败不阻断收口）。"""
    from neurova.llm.generators.pool_ingest import archiveGenerationToPool

    await archiveGenerationToPool(
        kind=record.kind or "video", prompt=record.prompt,
        urls=[url] if url else [],
        task_id=record.task_id, protocol=record.protocol, model=record.model,
        user_id=record.owner_user_id, agent_id=record.agent_id,
        session_id=record.session_id, turn=record.turn,
        tenant_id=str(getattr(record, "tenant_id", "") or ""))


def _recovery_interval() -> float:
    try:
        return max(10.0, float(os.environ.get("NEUROVA_GENERATION_RECOVERY_SEC", "60")))
    except ValueError:
        return 60.0


async def recovery_tick(ledger: Optional[GenerationTaskLedger] = None) -> int:
    """扫账本未决任务逐条收口，返回处理条数。单条异常不中断整轮。"""
    ledger = ledger or get_generation_task_ledger()
    processed = 0
    for rec in ledger.unfinished():
        try:
            if rec.kind == "music":
                await settle_music_record(rec, ledger=ledger)
            else:
                await settle_video_record(rec, ledger=ledger)
            processed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("生成任务恢复收口失败(%s): %s", rec.task_id, e)
    return processed


_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


async def _recovery_loop() -> None:
    assert _stop_event is not None
    interval = _recovery_interval()
    while not _stop_event.is_set():
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=interval)
            return  # 显式停止
        except asyncio.TimeoutError:
            pass
        try:
            n = await recovery_tick()
            if n:
                logger.info("生成任务恢复轮询：本轮收口 %d 条", n)
        except Exception as e:  # noqa: BLE001
            logger.warning("生成任务恢复轮询异常: %s", e)


def start_generation_recovery() -> Optional[asyncio.Task]:
    """随服务启动恢复循环（幂等）。"""
    global _task, _stop_event
    if _task is not None and not _task.done():
        return _task
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_recovery_loop(), name="generation-recovery")
    logger.info("生成任务恢复轮询已启动（间隔 %ss）", _recovery_interval())
    return _task


async def stop_generation_recovery() -> None:
    """停止并回收恢复循环（shutdown 钩子）。"""
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    task = _task
    _task = None
    _stop_event = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
