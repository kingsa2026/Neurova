"""视频收口的服务端驱动（§6-78 A 条 —— 收敛不该等"有人来 GET"）。

改前的形态：`recovery.py` 的收口循环只写任务账本（`ledger.update(...)`），从不回写
`storyboards`；镜头行被更新的唯一入口是 `GET /api/v1/studio/episodes/{eid}` 里调一次的
`_backfill_video_status`（原 `studio_api.py:245`）。也就是说"这条镜头跑完了"只存在于
账本里，投影面要等有人来看才更新——没人看就永远停在 `running`，而 `running` 又让
`services.generate_shot_videos` 拒绝重跑（同文件 `:389-391`）。

本模块把那份映射从端点里搬到 studio 层，给它两个消费者：

1. HTTP 投影（`GET /episodes/{eid}` 调 `reconcileEpisode`，形态与改前一致）；
2. 服务端周期驱动器 `startReconcileSweep`（挂在 lifespan 上，成对启停）。

映射只留这一份——两处各写一遍迟早漂成"投影说 done、驱动器说 running"。
账本行取不到时**诚实收尾为 failed**：留着 `running` 就是既收不了口也重新提交不了。
"""
from __future__ import annotations

import asyncio
import threading
import typing

from neurova.aigc_studio.store import get_store
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 周期收敛的节拍。它不由账本 TTL 之类派生：这里量的是"用户多久能看到镜头完成"，
#: 而 `recovery.py` 自己那圈是"上游任务多久被问一次"——两件事，两个数。
RECONCILE_INTERVAL_S = 20.0

#: 账本行丢了时写进 `error` 的点名原因（不许留空，空 error + failed 无从归因）
DANGLING_TASK_ERROR = "ledger_task_missing（任务账本行取不到，无法判定终态，请重跑该镜头）"

_lock = threading.RLock()
_sweepTask: typing.Optional["asyncio.Task"] = None
_sweepStop: typing.Optional[asyncio.Event] = None


def reconcileEpisode(store, eid: str) -> typing.List[typing.Dict[str, typing.Any]]:
    """把该分集里"在跑"的镜头按任务账本收敛；返回收敛后的镜头列表。"""
    from neurova.llm.generators import task_ledger as _ledger_mod

    led = _ledger_mod.get_generation_task_ledger()
    shots = store.list_storyboards(eid)
    for sb in shots:
        if sb.get("video_status") != "running" or not sb.get("ledger_task_id"):
            continue
        task = led.get(sb["ledger_task_id"])
        if task is None:
            # 改前是 `continue`：镜头永久停在 running，而重跑闸门又拒绝 running
            store.update_storyboard(sb["id"], {"video_status": "failed",
                                               "error": DANGLING_TASK_ERROR})
            sb["video_status"] = "failed"
            sb["error"] = DANGLING_TASK_ERROR
            continue
        if task.status == _ledger_mod.TASK_SUCCEEDED:
            path = task.local_path or ""
            if not path:
                # 本地化失败但远端 URL 还在：`done` + 空 `video_path` 会让前端既不渲染
                # 也不报错，URL 过期后产物永丢（§6-78 D 条）。诚实标 failed 并带成因。
                reason = str((task.error or "") or "视频已生成但本地化失败，产物未落盘")
                store.update_storyboard(sb["id"], {"video_status": "failed",
                                                   "error": reason[:200]})
                sb["video_status"] = "failed"
                sb["error"] = reason
                continue
            store.update_storyboard(sb["id"], {
                "video_status": "done", "video_path": path,
                "status": "video_ready", "error": ""})
            sb["video_status"] = "done"
            sb["video_path"] = path
        elif task.status == _ledger_mod.TASK_FAILED:
            store.update_storyboard(sb["id"], {
                "video_status": "failed", "error": (task.error or "")[:200]})
            sb["video_status"] = "failed"
    return shots


async def salvageLocalFromLedger(store, sb: dict) -> str:
    """账本说「视频已生成」而本地没件时，先把那条远端产物拉回本地；成功回本地路径。

    这是 `task_ledger` 里那条 `result_url` 在 Studio 一侧的**唯一读者**（§6-99）。
    改前的形态：`reconcileEpisode` 遇到「`succeeded` 且无 `local_path`」已把镜头诚实
    改判 `failed`（`0dd80fd0`），可账本里那条 URL 从此无人去取——用户点「重试视频」时
    `services.generate_shot_videos` 直接再 `submit_video` 一次，**为一单已经付过钱的产物
    再付一次**；URL 过期后永丢，账面却像什么都没发生过。
    接法选「花钱之前先抢救」而不是「把外链摆到前端」：远端 URL 本就带有效期，
    新建一条对外展示面等于把一个不可靠的读数当成交付物。落盘走仓内唯一的产物落盘点
    `persist_media`（含出网安全闸），不另开下载路径。

    只在「有远端 URL、本地没件、账本已 `succeeded`」这三件齐平时动手；任一件不满足
    或下载失败都回空串，调用侧照常提交——**拉不回不等于这镜不用管**。
    镜头行与账本行同时补 `local_path`：只写一边，下一次收口就按另一边判它"没本地化"。
    """
    from neurova.llm.generators import task_ledger as _ledger_mod
    from neurova.llm.generators.runtime import persist_media

    taskId = str(sb.get("ledger_task_id") or "")
    if not taskId:
        return ""
    led = _ledger_mod.get_generation_task_ledger()
    task = led.get(taskId)
    if task is None or task.status != _ledger_mod.TASK_SUCCEEDED:
        return ""
    url = str(task.result_url or "")
    # 两种形态都要救：`http…` 要过出网闸下载，`data:` 是 provider 直接回内联件
    # （`recovery.py:80` 那一支根本不试本地化，`local_path` 恒空）——`persist_media`
    # 原生吃这两种，只认 http 就把"本地从未落过盘"那一类留在门外。
    if task.local_path or not (url.startswith("http") or url.startswith("data:")):
        return ""
    try:
        path = await persist_media(url, "video", task.task_id, 0)
    except Exception as e:  # noqa: BLE001 - 救不回是常事（URL 过期），交回调用侧走提交
        logger.info("远端产物抢救失败(%s): %s", task.task_id, str(e)[:200])
        return ""
    if not path:
        return ""
    led.update(task.task_id, local_path=path)
    store.update_storyboard(sb["id"], {
        "video_status": "done", "video_path": path,
        "status": "video_ready", "error": ""})
    sb["video_status"] = "done"
    sb["video_path"] = path
    logger.info("镜头 %s 的产物由账本远端件抢救回本地：%s", sb["id"], path)
    return path


def reconcileRunningEpisodes(store=None) -> int:
    """扫全库"有在跑视频"的分集并逐集收敛；返回被处理的镜头数。"""
    store = store or get_store()
    handled = 0
    for eid in store.listEpisodeIdsWithRunningVideos():
        before = [s.get("video_status") for s in store.list_storyboards(eid)]
        reconcileEpisode(store, eid)
        after = [s.get("video_status") for s in store.list_storyboards(eid)]
        handled += sum(1 for b, a in zip(before, after) if b != a)
    return handled


def startReconcileSweep(store=None, intervalSeconds: float = RECONCILE_INTERVAL_S) -> bool:
    """幂等启动。没有运行中的事件循环时**如实回 False**（不假装"已在跑"）。"""
    global _sweepTask, _sweepStop
    with _lock:
        if _sweepTask is not None and not _sweepTask.done():
            return True
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Studio 视频收口未启动：当前没有运行的事件循环")
            return False
        store = store or get_store()
        _sweepStop = asyncio.Event()
        _sweepTask = asyncio.create_task(
            _pacedLoop(_sweepStop, store, intervalSeconds))
        return True


async def _pacedLoop(stop: asyncio.Event, store, intervalSeconds: float) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=intervalSeconds)
        except asyncio.TimeoutError:
            pass
        else:
            return                                   # stop 置位：优雅退出
        try:
            touched = await asyncio.to_thread(reconcileRunningEpisodes, store)
            if touched:
                logger.info("Studio 视频收口: %d 条镜头状态由账本回写", touched)
        except Exception:  # noqa: BLE001 - 驱动器坏了不许拖垮应用
            logger.exception("Studio 视频收口驱动器异常")


def stopReconcileSweep() -> bool:
    """成对关停。不显式收敛的常驻 task 会拖住 `TestClient.__exit__` 的 join。"""
    global _sweepTask, _sweepStop
    with _lock:
        task, stop = _sweepTask, _sweepStop
        _sweepTask, _sweepStop = None, None
    if stop is not None:
        stop.set()
    if task is None:
        return False
    task.cancel()
    return True
