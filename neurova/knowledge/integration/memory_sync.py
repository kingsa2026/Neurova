"""Memory ↔ knowledge base synchronization service.

Bidirectional sync between the memory subsystem and the knowledge base,
with persisted link records and similarity detection.
"""

import asyncio
import datetime
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _run_async(coro: Any) -> Any:
    """在同步上下文中运行异步协程

    尝试获取当前事件循环；若无则创建新循环执行。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已在事件循环中（如 Jupyter），用新线程
        from neurova.core.thread_pool import get_thread_pool

        pool = get_thread_pool()
        return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class MemorySync:
    """Bi-directional sync between memory and knowledge base."""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._links_path = self._dir / "links.json"
        self._sync_path = self._dir / "sync.json"
        self._links: Dict[str, Dict[str, Any]] = {}
        self._sync_log: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

        # 依赖组件（延迟注入）
        self._memory_system: Any = None  # MemCore 实例
        self._knowledge_base: Any = None  # FlowKBAdapter 实例

        self._load()

    def configure(
        self,
        memory_system: Any = None,
        knowledge_base: Any = None,
    ) -> None:
        """注入依赖组件

        Args:
            memory_system: MemCore 实例，提供 retrieve_memories / save_conversation_memory
            knowledge_base: FlowKBAdapter 实例，提供 search / add_document
        """
        if memory_system is not None:
            self._memory_system = memory_system
        if knowledge_base is not None:
            self._knowledge_base = knowledge_base
        logger.info(
            "MemorySync configured: memory=%s, knowledge=%s",
            self._memory_system is not None,
            self._knowledge_base is not None,
        )

    def _load(self) -> None:
        if self._links_path.exists():
            try:
                data = json.loads(self._links_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._links.update(data)
            except Exception as exc:
                logger.warning("Failed to load links: %s", exc)
        if self._sync_path.exists():
            try:
                data = json.loads(self._sync_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._sync_log.extend(data)
            except Exception as exc:
                logger.warning("Failed to load sync log: %s", exc)

    def _save(self) -> None:
        self._links_path.write_text(
            json.dumps(self._links, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._sync_path.write_text(
            json.dumps(self._sync_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def sync_memory_to_knowledge(self, memory: Any = None) -> Dict[str, Any]:
        """将记忆同步到知识库

        流程:
        1. 从记忆对象提取内容
        2. 在知识库中搜索相似内容
        3. 已有匹配 → 创建 link
        4. 无匹配 → 将记忆内容添加为知识库文档 + 创建 link

        Args:
            memory: 记忆对象，需提供 id 和 content 属性；或 dict 含 id/content

        Returns:
            包含 synced_count, links_created, status 的结果字典
        """
        with self._lock:
            # 1. 提取记忆信息
            memory_id = None
            memory_content = ""
            if memory is not None:
                memory_id = getattr(memory, "id", None) or (memory.get("id") if isinstance(memory, dict) else None)
                memory_content = getattr(memory, "content", "") or (
                    memory.get("content", "") if isinstance(memory, dict) else ""
                )

            entry = {
                "direction": "memory_to_knowledge",
                "status": "ok",
                "memory_id": memory_id,
                "synced_count": 0,
                "links_created": 0,
                "created_at": _now_iso(),
            }

            if not memory_content:
                entry["status"] = "skipped_no_content"
                self._sync_log.append(entry)
                self._save()
                return entry

            # 2. 搜索知识库匹配
            matched_knowledge_ids: List[str] = []
            if self._knowledge_base is not None:
                try:
                    results = _run_async(
                        self._knowledge_base.search(
                            query=memory_content[:200],
                            limit=5,
                        )
                    )
                    for result in results:
                        k_id = getattr(result, "document_id", None) or (
                            result.get("document_id") if isinstance(result, dict) else None
                        )
                        score = getattr(result, "score", 0) or (
                            result.get("score", 0) if isinstance(result, dict) else 0
                        )
                        if k_id and score >= 0.6:
                            matched_knowledge_ids.append(k_id)
                except Exception as exc:
                    logger.warning("Knowledge search during sync failed: %s", exc)

            # 3. 无匹配 → 添加为新知识文档
            if not matched_knowledge_ids and self._knowledge_base is not None:
                try:
                    title = self._extract_title(memory_content)
                    doc = _run_async(
                        self._knowledge_base.add_document(
                            title=title or f"memory_{memory_id or 'unknown'}",
                            content=memory_content,
                        )
                    )
                    if doc:
                        new_k_id = getattr(doc, "document_id", None) or (
                            doc.get("document_id") if isinstance(doc, dict) else None
                        )
                        if new_k_id:
                            matched_knowledge_ids.append(new_k_id)
                except Exception as exc:
                    logger.warning("Failed to add memory as knowledge document: %s", exc)

            # 4. 创建 link 记录
            links_created = 0
            if memory_id and matched_knowledge_ids:
                for k_id in matched_knowledge_ids:
                    # 避免重复 link
                    existing = self.get_memory_links(memory_id)
                    already_linked = any(lk.get("knowledge_id") == k_id for lk in existing)
                    if not already_linked:
                        self._add_memory_knowledge_link(
                            memory_id=memory_id,
                            knowledge_id=k_id,
                            link_type="synced",
                        )
                        links_created += 1

            entry["synced_count"] = len(matched_knowledge_ids)
            entry["links_created"] = links_created
            self._sync_log.append(entry)
            self._save()

            logger.info(
                "sync_memory_to_knowledge: memory_id=%s, matched=%d, links=%d",
                memory_id,
                len(matched_knowledge_ids),
                links_created,
            )
            return entry

    def sync_knowledge_to_memory(self, knowledge: Any = None) -> Dict[str, Any]:
        """将知识库条目同步到记忆系统

        流程:
        1. 从知识对象提取内容
        2. 检查是否已有相似记忆（通过 link 记录 + LCS 相似度）
        3. 无相似记忆 → 存入记忆系统
        4. 创建 link 记录

        Args:
            knowledge: 知识对象，需提供 document_id/title/content 属性；或 dict

        Returns:
            包含 synced_count, links_created, status 的结果字典
        """
        with self._lock:
            # 1. 提取知识信息
            k_id = None
            k_title = ""
            k_content = ""
            if knowledge is not None:
                k_id = getattr(knowledge, "document_id", None) or (
                    knowledge.get("document_id") if isinstance(knowledge, dict) else None
                )
                k_title = getattr(knowledge, "title", "") or (
                    knowledge.get("title", "") if isinstance(knowledge, dict) else ""
                )
                k_content = getattr(knowledge, "content", "") or (
                    knowledge.get("content", "") if isinstance(knowledge, dict) else ""
                )

            entry = {
                "direction": "knowledge_to_memory",
                "status": "ok",
                "knowledge_id": k_id,
                "synced_count": 0,
                "links_created": 0,
                "created_at": _now_iso(),
            }

            content = k_content or k_title
            if not content:
                entry["status"] = "skipped_no_content"
                self._sync_log.append(entry)
                self._save()
                return entry

            # 2. 检查是否已有相似记忆
            already_synced = False
            if k_id:
                existing_links = self.get_knowledge_links(k_id)
                if existing_links:
                    already_synced = True

            if not already_synced and self._memory_system is not None:
                # 搜索记忆系统确认是否有相似内容
                try:
                    memories = self._memory_system.retrieve_memories(
                        query=content[:200],
                        limit=3,
                    )
                    for mem in memories:
                        mem_content = mem.get("content", "") if isinstance(mem, dict) else getattr(mem, "content", "")
                        if mem_content and self._is_similar(content, mem_content, threshold=0.5):
                            # 已有相似记忆，创建 link 即可
                            mem_id = mem.get("id") if isinstance(mem, dict) else getattr(mem, "id", None)
                            if mem_id and k_id:
                                existing = self.get_knowledge_links(k_id)
                                already_linked = any(lk.get("memory_id") == mem_id for lk in existing)
                                if not already_linked:
                                    self._add_memory_knowledge_link(
                                        memory_id=mem_id,
                                        knowledge_id=k_id,
                                        link_type="synced",
                                    )
                                    entry["links_created"] += 1
                                already_synced = True
                            break
                except Exception as exc:
                    logger.debug("Memory search during sync failed: %s", exc)

            # 3. 无相似记忆 → 存入记忆系统
            if not already_synced and self._memory_system is not None:
                try:
                    memory_text = f"[知识同步] {k_title}: {content}" if k_title else f"[知识同步] {content}"
                    self._memory_system.save_conversation_memory(
                        user_input=f"knowledge_sync:{(k_title or content)[:50]}",
                        agent_response=memory_text,
                        metadata={
                            "source": "memory_sync_knowledge_to_memory",
                            "knowledge_id": k_id,
                        },
                    )
                    entry["synced_count"] = 1

                    # 尝试找到刚存入的记忆来创建 link
                    if k_id:
                        try:
                            memories = self._memory_system.retrieve_memories(
                                query=content[:200],
                                limit=1,
                            )
                            if memories:
                                mem = memories[0]
                                mem_id = mem.get("id") if isinstance(mem, dict) else getattr(mem, "id", None)
                                if mem_id:
                                    self._add_memory_knowledge_link(
                                        memory_id=mem_id,
                                        knowledge_id=k_id,
                                        link_type="synced",
                                    )
                                    entry["links_created"] += 1
                        except Exception:
                            pass
                except Exception as exc:
                    logger.warning("Failed to save knowledge as memory: %s", exc)
                    entry["status"] = "error"

            self._sync_log.append(entry)
            self._save()

            logger.info(
                "sync_knowledge_to_memory: knowledge_id=%s, synced=%d, links=%d",
                k_id,
                entry["synced_count"],
                entry["links_created"],
            )
            return entry

    def sync_batch(self, direction: str = "both", limit: int = 50) -> Dict[str, Any]:
        """批量同步

        Args:
            direction: "memory_to_knowledge", "knowledge_to_memory", 或 "both"
            limit: 每个方向的最大同步条数

        Returns:
            批量同步结果摘要
        """
        results = {"memory_to_knowledge": 0, "knowledge_to_memory": 0, "total_links": 0}

        if direction in ("memory_to_knowledge", "both") and self._memory_system:
            try:
                memories = self._memory_system.retrieve_memories(query="全部记忆", limit=limit)
                for mem in memories:
                    r = self.sync_memory_to_knowledge(mem)
                    results["memory_to_knowledge"] += r.get("synced_count", 0)
                    results["total_links"] += r.get("links_created", 0)
            except Exception as exc:
                logger.warning("Batch sync memory→knowledge failed: %s", exc)

        if direction in ("knowledge_to_memory", "both") and self._knowledge_base:
            try:
                docs = _run_async(self._knowledge_base.list_documents(limit=limit))
                for doc in docs:
                    r = self.sync_knowledge_to_memory(doc)
                    results["knowledge_to_memory"] += r.get("synced_count", 0)
                    results["total_links"] += r.get("links_created", 0)
            except Exception as exc:
                logger.warning("Batch sync knowledge→memory failed: %s", exc)

        logger.info("sync_batch: %s", results)
        return results

    def _add_memory_knowledge_link(self, memory_id: str, knowledge_id: str, link_type: str = "related") -> str:
        with self._lock:
            lid = _new_id("lnk_")
            self._links[lid] = {
                "id": lid,
                "memory_id": memory_id,
                "knowledge_id": knowledge_id,
                "link_type": link_type,
                "created_at": _now_iso(),
            }
            self._save()
            return lid

    def get_memory_links(self, memory_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(link) for link in self._links.values() if link.get("memory_id") == memory_id]

    def get_knowledge_links(self, knowledge_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(link) for link in self._links.values() if link.get("knowledge_id") == knowledge_id]

    def remove_link(self, link_id: str) -> bool:
        with self._lock:
            existed = self._links.pop(link_id, None) is not None
            if existed:
                self._save()
            return existed

    def get_sync_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_links = len(self._links)
            by_type: Dict[str, int] = {}
            for link in self._links.values():
                t = link.get("link_type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1
            by_direction: Dict[str, int] = {}
            for entry in self._sync_log:
                d = entry.get("direction", "unknown")
                by_direction[d] = by_direction.get(d, 0) + 1
            return {
                "total_links": total_links,
                "total_sync_runs": len(self._sync_log),
                "by_link_type": by_type,
                "by_direction": by_direction,
                "last_sync_at": self._sync_log[-1]["created_at"] if self._sync_log else None,
            }

    def _lcs_length(self, a: str, b: str) -> int:
        if not isinstance(a, str) or not isinstance(b, str):
            return 0
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return 0
        prev = [0] * (n + 1)
        curr = [0] * (n + 1)
        for i in range(1, m + 1):
            ai = a[i - 1]
            for j in range(1, n + 1):
                if ai == b[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = prev[j] if prev[j] >= curr[j - 1] else curr[j - 1]
            prev, curr = curr, prev
        return prev[n]

    def _is_similar(self, a: str, b: str, threshold: float = 0.5) -> bool:
        if not a or not b:
            return False
        lcs = self._lcs_length(a, b)
        denom = max(len(a), len(b))
        if denom == 0:
            return False
        return (lcs / denom) >= threshold

    def _find_similar_memory(self, text: str) -> Optional[str]:
        with self._lock:
            best_id: Optional[str] = None
            best_score = 0
            for link in self._links.values():
                candidate = str(link.get("memory_id", ""))
                if not candidate:
                    continue
                score = self._lcs_length(text, candidate)
                if score > best_score:
                    best_score = score
                    best_id = candidate
            return best_id

    def _extract_title(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            return ""
        for sep in (". ", ".\n", "? ", "!\n", "!\n", "?\n", "\n"):
            idx = text.find(sep)
            if idx > 0:
                return text[:idx].strip()
        max_len = 60
        if len(text) <= max_len:
            return text
        truncated = text[:max_len].rsplit(" ", 1)[0].strip()
        return truncated or text[:max_len]


_singleton: Optional[MemorySync] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/memory_sync"


def get_memory_sync_service() -> MemorySync:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = MemorySync(_DEFAULT_DIR)
    return _singleton
