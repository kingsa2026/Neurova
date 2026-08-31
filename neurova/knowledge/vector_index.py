"""
知识库持久化向量索引（遗留修复 ②：向量索引无持久化 / VectorIndexManager 闲置）

设计：
- 每用户一个索引文件（knowledge_vectors_{user_id}.json）：可见性由文件边界保证，
  索引内容 = 该用户 visible_items 的向量 + 指纹（updated_at+长度）
- ensure_indexed 增量同步：新增/变更才计算 embedding，删除条目即剔除向量，
  重启从磁盘恢复（未变条目零重算）
- search(query, user)：query 单次 embedding，索引内余弦相似度，返回带
  title/content/score 的命中；仅返回该用户可见条目（按构造保证）
- embedding 引擎可注入（测试零依赖）；默认引擎惰性取 neurova.embedding，
  不可用优雅降级（ensure/search 返回空，不抛出）
- 引擎指纹写入文件头，模型变更自动重建
"""

from __future__ import annotations

import datetime
import json
import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_STORAGE_DIR = "./data/knowledge"
_SENTINEL_DEFAULT = "__default__"


def _default_engine():
    """默认 embedding 引擎（ONNX，bge-small-zh-v1.5）；不可用返回 None。"""
    try:
        from neurova.embedding import get_embedding_engine

        return get_embedding_engine()
    except Exception as e:  # noqa: BLE001
        logger.warning("知识向量索引：embedding 引擎不可用，降级禁用: %s", e)
        return None


def _engine_id(engine) -> str:
    return type(engine).__name__ if engine is not None else "disabled"


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _fingerprint(entry: Dict[str, Any]) -> str:
    return "%s:%d" % (entry.get("updated_at", 0), len(entry.get("content", "") or ""))


class KnowledgeVectorIndex:
    """按用户分文件的持久化向量索引（visible_items 视图镜像）。"""

    def __init__(self, storage_dir: str, engine: Any = _SENTINEL_DEFAULT) -> None:
        self.storage_dir = str(storage_dir)
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._engine = engine  # 哨兵=惰性默认；None=禁用；其他=注入实例
        self._cache: Dict[str, Dict[str, Dict[str, Any]]] = {}  # uid -> kid -> 记录
        self._computed = 0  # 实例累计新算向量数（测试观测）
        self._last_uid: Optional[str] = None

    # ── 引擎 ─────────────────────────────────────────────────

    def _get_engine(self):
        if self._engine is _SENTINEL_DEFAULT:
            eng = _default_engine()
            if eng is None:
                return None  # 保持哨兵，下次调用重试
            self._engine = eng
        return self._engine

    # ── 持久化 ────────────────────────────────────────────────

    def _file_for(self, user: Optional[Dict[str, Any]]) -> Path:
        uid = str((user or {}).get("user_id") or "default")
        return self._dir / ("knowledge_vectors_%s.json" % uid)

    def _load_user(self, user: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        uid = str((user or {}).get("user_id") or "default")
        if uid in self._cache:
            return self._cache[uid]
        path = self._file_for(user)
        records: Dict[str, Dict[str, Any]] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("vectors"), dict):
                    records = data["vectors"]
            except Exception as e:  # noqa: BLE001
                logger.warning("向量索引加载失败 %s: %s", path, e)
        self._cache[uid] = records
        return records

    def _save_user(self, user: Optional[Dict[str, Any]], records: Dict[str, Dict[str, Any]], engine_id: str) -> None:
        path = self._file_for(user)
        try:
            path.write_text(
                json.dumps(
                    {"version": 1, "engine": engine_id, "vectors": records},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("向量索引保存失败 %s: %s", path, e)

    # ── 同步与检索 ────────────────────────────────────────────

    def ensure_indexed(
        self, repo: Any, user: Optional[Dict[str, Any]]
    ) -> Dict[str, int]:
        """把当前用户可见条目增量写入该用户的索引文件。

        Returns:
            {"computed": 本次新算向量数, "entry_count": 索引内条目数}
        """
        engine = self._get_engine()
        if engine is None:
            return {"computed": 0, "entry_count": 0}
        if not hasattr(repo, "visible_items"):
            return {"computed": 0, "entry_count": 0}

        entries = repo.visible_items(user)
        with self._lock:
            records = self._load_user(user)
            file_engine = ""
            path = self._file_for(user)
            if path.exists():
                try:
                    file_engine = str(json.loads(path.read_text(encoding="utf-8")).get("engine", ""))
                except Exception:  # noqa: BLE001
                    file_engine = ""
            current_engine_id = _engine_id(engine)
            if file_engine and file_engine != current_engine_id:
                records = {}  # 模型变更 → 重建

            desired: Dict[str, Dict[str, Any]] = {
                str(e.get("knowledge_id", "")): e for e in entries if e.get("knowledge_id")
            }

            to_compute: List[Tuple[str, Dict[str, Any]]] = []
            for kid, entry in desired.items():
                fp = _fingerprint(entry)
                rec = records.get(kid)
                if rec is None or rec.get("fingerprint") != fp:
                    to_compute.append((kid, entry))
            # 剔除已删除条目（当前可见集合之外的既有记录）
            for kid in list(records.keys()):
                if kid not in desired:
                    del records[kid]

            if to_compute:
                texts = []
                for _kid, entry in to_compute:
                    title = str(entry.get("title", ""))
                    content = str(entry.get("content", ""))
                    texts.append((title + "\n" + content) if title else content)
                try:
                    if hasattr(engine, "encode_batch"):
                        vectors = engine.encode_batch(texts)
                    else:
                        vectors = [engine.encode(t) for t in texts]
                except Exception as e:  # noqa: BLE001
                    logger.warning("向量索引：embedding 批量计算失败: %s", e)
                    return {"computed": 0, "entry_count": len(records)}

                for (kid, entry), vec in zip(to_compute, vectors):
                    records[kid] = {
                        "vector": [float(x) for x in (vec or [])],
                        "fingerprint": _fingerprint(entry),
                        "title": str(entry.get("title", "")),
                        "content": str(entry.get("content", ""))[:2000],
                    }
                self._computed += len(to_compute)

            self._save_user(user, records, current_engine_id)
            uid = str((user or {}).get("user_id") or "default")
            self._cache[uid] = records
            self._last_uid = uid
            return {"computed": len(to_compute), "entry_count": len(records)}

    def search(
        self,
        query: str,
        user: Optional[Dict[str, Any]],
        top_k: int = 10,
        repo: Any = None,
    ) -> List[Dict[str, Any]]:
        """在当前用户的向量索引内做余弦相似度检索。"""
        engine = self._get_engine()
        if engine is None or not query:
            return []
        if repo is not None:
            self.ensure_indexed(repo, user)

        with self._lock:
            records = self._load_user(user)
            items = [(kid, dict(rec)) for kid, rec in records.items()]

        try:
            qv = engine.encode(query)
        except Exception as e:  # noqa: BLE001
            logger.warning("向量索引：query 编码失败: %s", e)
            return []
        if not qv:
            return []

        scored: List[Tuple[str, float, Dict[str, Any]]] = []
        for kid, rec in items:
            score = _cosine(qv, rec.get("vector") or [])
            if score > 0.0:
                scored.append((kid, score, rec))
        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "id": kid,
                "title": rec.get("title", ""),
                "content": rec.get("content", ""),
                "score": round(float(score), 4),
            }
            for kid, score, rec in scored[: max(1, int(top_k))]
        ]

    def stats(self) -> Dict[str, int]:
        """最近一次 ensure 的观测值（entry_count / computed，测试观测用）。"""
        with self._lock:
            records = self._cache.get(self._last_uid, {}) if self._last_uid else {}
        return {"entry_count": len(records), "computed": self._computed}


_singleton: Optional[KnowledgeVectorIndex] = None
_singleton_lock = threading.Lock()


def get_knowledge_vector_index() -> KnowledgeVectorIndex:
    """全局单例（默认目录 + 惰性默认引擎）。"""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = KnowledgeVectorIndex(DEFAULT_STORAGE_DIR)
    return _singleton
