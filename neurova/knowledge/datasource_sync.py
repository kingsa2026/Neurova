"""远程数据源增量同步。

报告落点（§7 #9/#10）。把
"每次实时搜索、只回标题"的检索代理型远程库，升级为**可同步落库**：飞书
知识空间文档正文经 docx raw_content 拉取后落进本地知识仓库
（knowledge_id = feishu_<obj_token> 稳定映射），检索走本地分片索引。


1. 游标 = 完整可续传快照 {obj_token: edit_sig}（不是 delta），持久化在
   远程配置的 settings._sync.cursor——重启/下轮同步直接续跑；
2. **拉取失败不推进游标**：单文档正文获取失败时保留旧 sig（新文档则本轮
   不写入游标）→ 下轮必然重试，不会因瞬时故障把节点永久跳过；
3. **清单残缺抑制删除检测**：list_space_nodes 返回 partial=True 时绝不
   执行"游标有、清单无 → 删"的收敛（防把没列全误判成已删除）；
4. 并发互斥（#10）：同一 config 的同步一次只允许一路（非阻塞锁，第二路
   立即 SyncBusyError）——对齐 HasRunningSync；Neurova 单进程用 threading
 即可

错误方向纪律：同步失败/残缺只影响"这一轮没同步完"，绝不静默破坏
已有本地数据（不删、不清游标、不落半截）。
"""

from __future__ import annotations

import datetime
import threading
import time
import asyncio
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 当前仅 docx/doc 有 raw_content 正文端点；sheet/bitable 等跳过（不建条目、
# 也不进游标——下轮仍按新对象处理，接入表格解析后自然收敛）
SUPPORTED_DOC_TYPES = {"docx", "doc"}

# config_id → 同步互斥锁
_ACTIVE_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class SyncBusyError(RuntimeError):
    """同一数据源已有同步在执行（并发互斥，立即失败不排队）。"""


@contextmanager
def config_sync_lock(config_id: str):
    """非阻塞占用该 config 的同步通道；被占 → SyncBusyError（不排队堆任务）。"""
    with _LOCKS_GUARD:
        lock = _ACTIVE_LOCKS.setdefault(str(config_id), threading.Lock())
    if not lock.acquire(blocking=False):
        raise SyncBusyError("数据源 %s 的同步已在进行中" % config_id)
    try:
        yield
    finally:
        lock.release()


def _plan_upserts(
    nodes: List[Dict[str, Any]], cursor: Dict[str, str]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, str], List[str]]:
    """纯函数游标计划（可测）。返回 (listed_docs, skipped_sig, initial_new_cursor, skipped_types)。

    - listed_docs：需要（重）拉正文的 docx/doc 节点（id → 节点）；
    - skipped_sig：sig 未变的已知文档 id → sig（直接结转游标）；
    - initial_new_cursor：失败不推进的基线（含 skipped_sig）；
    - unsupported 计数由调用方统计。
    """
    listed: Dict[str, Dict[str, Any]] = {}
    skipped: Dict[str, str] = {}
    unsupported: List[str] = []
    for n in nodes:
        nid = str(n.get("id") or "")
        if not nid:
            continue
        if str(n.get("obj_type") or "") not in SUPPORTED_DOC_TYPES:
            unsupported.append(nid)
            continue
        if cursor.get(nid) == n.get("sig"):
            skipped[nid] = str(n.get("sig") or "")
        else:
            listed[nid] = n
    return listed, skipped, dict(skipped), unsupported


async def run_feishu_sync(
    adapter: Any,
    repo: Any,
    storage: Any,
    config_id: str,
    user_id: str,
    agent_id: str = "default",
    space_id: Optional[str] = None,
) -> Dict[str, Any]:
    """一轮飞书空间增量同步。返回统计 {upserted, skipped, skipped_type, failed, deleted, partial}。

    adapter 需具备 list_space_nodes/fetch_doc_content（FeishuKBAdapter）；
    storage 需 get_config_by_id/update_config（KnowledgeStorage）。
    """
    with config_sync_lock(config_id):
        cfg = storage.get_config_by_id(config_id) or {}
        settings = dict(cfg.get("settings") or {})
        sid = str(space_id or settings.get("space_id") or getattr(adapter, "space_id", "") or "")
        if not sid:
            raise ValueError("飞书同步需要 space_id（配置 settings.space_id）")

        cursor: Dict[str, str] = dict((settings.get("_sync") or {}).get("cursor") or {})
        listing = await adapter.list_space_nodes(sid)
        nodes = listing.get("nodes") or []
        partial = bool(listing.get("partial"))

        listed_docs, skipped_sig, new_cursor, unsupported = _plan_upserts(nodes, cursor)
        stats = {
            "upserted": 0,
            "skipped": len(skipped_sig),
            "skipped_type": len(unsupported),
            "failed": 0,
            "deleted": 0,
            "partial": partial,
        }

        for nid, node in listed_docs.items():
            try:
                content = await adapter.fetch_doc_content(nid)
            except Exception as e:  # noqa: BLE001
                logger.info("飞书同步拉取异常（不推进游标）: %s %s", nid, e)
                content = None
            if not content:
                # 失败不推进游标：旧值保留（新对象不写入）→ 下轮必重试
                if nid in cursor:
                    new_cursor[nid] = cursor[nid]
                stats["failed"] += 1
                continue
            kid = "feishu_%s" % nid
            found = repo.find_item(kid)
            if found is None:
                repo.create_knowledge(
                    agent_id=agent_id,
                    title=str(node.get("title") or nid),
                    content=content,
                    category="feishu",
                    source="feishu",
                    confidence=0.8,
                    knowledge_id=kid,
                    owner_user_id=str(user_id or "default"),
                    detect_conflict=False,
                )
            else:
                repo.update_knowledge(
                    found[0], kid, {"title": str(node.get("title") or nid), "content": content}
                )
            new_cursor[nid] = str(node.get("sig") or "")
            stats["upserted"] += 1

        if not partial:
            for gone in [k for k in cursor if k not in listed_docs and k not in skipped_sig]:
                kid = "feishu_%s" % gone
                found = repo.find_item(kid)
                if found is not None:
                    repo.delete_knowledge(found[0], kid, deleted_by="feishu_sync")
                stats["deleted"] += 1
        elif cursor and listed_docs is not None:
            logger.info("飞书同步清单残缺（partial），本轮跳过删除检测: config=%s", config_id)

        settings["_sync"] = {
            "cursor": new_cursor,
            "last_sync": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "last_sync_ts": time.time(),
            "last_partial": partial,
        }
        storage.update_config(config_id, settings=settings)
        logger.info("飞书同步完成: config=%s %s", config_id, stats)
        return stats


# ── P1#11③ 后台定时同步循环──────

from neurova.knowledge.storage import get_knowledge_storage  # noqa: E402


def _default_repo():
    from neurova.knowledge.repository import get_knowledge_repository

    return get_knowledge_repository()


def compute_due_configs(configs, now_ts: float) -> List[Dict[str, Any]]:
    """到期配置清单（纯函数，可测）：is_active 飞书配置且
    settings.sync_interval_minutes>0 且距 last_sync_ts 超过间隔。"""
    due: List[Dict[str, Any]] = []
    for cfg in configs or []:
        if str(cfg.get("source_type", "")) != "feishu" or not cfg.get("is_active"):
            continue
        st = cfg.get("settings") or {}
        try:
            interval = float(st.get("sync_interval_minutes") or 0)
        except (TypeError, ValueError):
            continue
        if interval <= 0:
            continue
        last = float((st.get("_sync") or {}).get("last_sync_ts") or 0.0)
        if now_ts - last >= interval * 60.0:
            due.append(cfg)
    return due


def _build_feishu_adapter(cfg: Dict[str, Any], storage) -> Any:
    from neurova.knowledge.adapters import FeishuKBAdapter

    settings = {k: v for k, v in (cfg.get("settings") or {}).items() if k != "_sync"}
    try:
        secret = storage.decrypt_api_key(str(cfg.get("id", "")))
    except Exception:  # noqa: BLE001
        secret = None
    if secret:
        settings.setdefault("app_secret", secret)
    return FeishuKBAdapter(settings)


async def tick_feishu_sync(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """一轮跨用户扫描：到期配置逐个同步（单配置故障不拖垮整轮）。"""
    storage = get_knowledge_storage()
    try:
        configs = storage.get_all_configs()
    except Exception as e:  # noqa: BLE001
        logger.warning("KB 定时同步读配置失败: %s", e)
        return []
    now_ts = now if now is not None else time.time()
    out: List[Dict[str, Any]] = []
    for cfg in compute_due_configs(configs, now_ts):
        cid = str(cfg.get("id", ""))
        uid = str(cfg.get("user_id") or "")
        try:
            adapter = _build_feishu_adapter(cfg, storage)
            stats = await run_feishu_sync(
                adapter, _default_repo(), storage, config_id=cid, user_id=uid
            )
            out.append({"config_id": cid, **stats})
        except SyncBusyError:
            continue  # 手动同步在跑——让路
        except Exception as e:  # noqa: BLE001
            logger.info("KB 定时同步单配置失败（下轮到点自然重试）: %s %s", cid, e)
    return out


async def run_feishu_sync_loop(poll_interval: float = 120.0) -> None:
    """app 启动装配的后台循环（fail-open，不阻断启动；间隔由各配置
    sync_interval_minutes 自定，未配置的永不触发）。"""
    logger.info("KB 定时同步循环已启动（poll=%ss）", poll_interval)
    while True:
        try:
            await tick_feishu_sync()
        except Exception:  # noqa: BLE001 - 循环不死
            logger.warning("KB 定时同步轮询异常（忽略续跑）", exc_info=True)
        await asyncio.sleep(poll_interval)
