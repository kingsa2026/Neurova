"""
知识库持久化向量索引（遗留修复 ②：向量索引无持久化；原异步 VectorIndexManager 已按 §6-376 显式放弃）

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

from neurova.core import vector_math
import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.knowledge.foundation.storage_fence import (
    PRODUCTION_STORAGE_DIR,
    assertNotUnderProductionStorage,
)
from neurova.knowledge.vector_ann import (
    annMinRecords,
    prepareVectors,
    resolveAnnBackend,
)

logger = get_logger(__name__)

# 生产目录只有 storage_fence 一处定义；向量缓存与条目库同目录，测试同样不许写真文件。
DEFAULT_STORAGE_DIR = PRODUCTION_STORAGE_DIR
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
    """索引身份：类名 + 模型身份（若引擎暴露）。

    只取类名会让“同一个 ONNXEmbeddingEngine 换 model_name”看起来没变，
    旧向量空间被继续复用。模型名/版本在构造时就稳定，纳入身份；
    dimension 不纳入——它要等首个 encode 后才初始化，放进来会让同一引擎
    在首次使用前后得到两个身份，触发不必要的全量重建。
    """
    if engine is None:
        return "disabled"
    parts = [type(engine).__name__]
    identity: List[str] = []
    for attr in ("model_name", "_model_name", "model_id", "_model_id",
                 "model_version", "_model_version"):
        value = getattr(engine, attr, None)
        if value and str(value) not in identity:
            identity.append(str(value))
    parts.extend(identity)
    return "|".join(parts)



def _fingerprint(entry: Dict[str, Any]) -> str:
    return "%s:%d" % (entry.get("updated_at", 0), len(entry.get("content", "") or ""))


class KnowledgeVectorIndex:
    """按用户分文件的持久化向量索引（visible_items 视图镜像）。"""

    def __init__(
        self,
        storage_dir: str,
        engine: Any = _SENTINEL_DEFAULT,
        annBackend: Any = _SENTINEL_DEFAULT,
        annMinRecordCount: Optional[int] = None,
    ) -> None:
        assertNotUnderProductionStorage(storage_dir, "知识向量缓存")
        self.storage_dir = str(storage_dir)
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._engine = engine  # 哨兵=惰性默认；None=禁用；其他=注入实例
        self._cache: Dict[str, Dict[str, Dict[str, Any]]] = {}  # uid -> kid -> 记录
        self._computed = 0  # 实例累计新算向量数（测试观测）
        self._last_uid: Optional[str] = None
        # ANN 是可选加速：哨兵=按环境探测；None=显式禁用；其他=注入后端。
        self._annBackend = annBackend
        self._annResolved = annBackend is not _SENTINEL_DEFAULT
        self._annReason = "disabled" if annBackend is None else ""
        self._annMinRecords = annMinRecords(annMinRecordCount)
        self._annIndexes: Dict[str, Any] = {}
        self._annVersions: Dict[str, int] = {}
        self._annFailures: Dict[str, int] = {}
        self._annLastError = ""
        # 记录版本只在写路径递增：ANN 缓存命中判断 O(1)，不再每次检索
        # 扫全量记录做指纹（大语料下那会把 ANN 的收益吃掉）。
        self._recordVersions: Dict[str, int] = {}

    # ── 引擎 ─────────────────────────────────────────────────

    def _get_engine(self):
        if self._engine is _SENTINEL_DEFAULT:
            eng = _default_engine()
            if eng is None:
                return None  # 保持哨兵，下次调用重试
            self._engine = eng
        return self._engine

    def _getAnn(self):
        if self._annResolved:
            return self._annBackend
        with self._lock:
            if not self._annResolved:
                backend, reason = resolveAnnBackend()
                self._annBackend = backend
                self._annReason = reason
                self._annResolved = True
        return self._annBackend

    def _searchAnn(
        self,
        uid: str,
        records: Dict[str, Dict[str, Any]],
        queryVector: List[float],
        topK: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """ANN 命中列表；None＝本路不可用/失败，调用方回退全量余弦。"""
        backend = self._getAnn()
        if backend is None or len(records) < self._annMinRecords:
            return None
        version = self._recordVersions.get(uid, 0)
        handle = None
        with self._lock:
            if self._annFailures.get(uid) == version:
                return None
            if self._annVersions.get(uid) == version:
                handle = self._annIndexes.get(uid)
        if handle is None:
            vectors = prepareVectors(records)
            if vectors is None:
                return None
            try:
                handle = backend.build(vectors)
            except Exception as exc:  # noqa: BLE001 - ANN 构建失败只降级，不打断检索
                self._annFailures[uid] = version
                self._annLastError = "build:%s" % exc
                logger.warning("知识向量 ANN 构建失败，回退全量余弦: %s", exc)
                return None
            with self._lock:
                self._annIndexes[uid] = handle
                self._annVersions[uid] = version
                self._annFailures.pop(uid, None)
        try:
            rawHits = backend.search(handle, queryVector, max(1, int(topK)))
        except Exception as exc:  # noqa: BLE001 - 查询失败同上
            self._annFailures[uid] = version
            self._annLastError = "search:%s" % exc
            logger.warning("知识向量 ANN 查询失败，回退全量余弦: %s", exc)
            return None

        with self._lock:
            self._annFailures.pop(uid, None)
            self._annLastError = ""
        hits: List[Dict[str, Any]] = []
        for kid, score in rawHits:
            record = records.get(str(kid))
            if record is None or float(score) <= 0.0:
                continue
            hits.append({
                "id": str(kid),
                "title": record.get("title", ""),
                "content": record.get("content", ""),
                "score": round(float(score), 4),
            })
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[: max(1, int(topK))]

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
            engine_reset = bool(file_engine and file_engine != current_engine_id)
            if engine_reset:
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
            removed_count = 0
            for kid in list(records.keys()):
                if kid not in desired:
                    del records[kid]
                    removed_count += 1

            if to_compute:
                texts = []
                for _kid, entry in to_compute:
                    title = str(entry.get("title", ""))
                    content = str(entry.get("content", ""))
                    texts.append((title + "\n" + content) if title else content)
                try:
                    if hasattr(engine, "encode_batch"):
                        batch = engine.encode_batch(texts)
                        # 真引擎（ONNXEmbeddingEngine）契约：encode_batch →
                        # EmbeddingResult（.vectors 才是向量列表）；注入引擎
                        # 可直接返回 list。两者之外退回逐条 encode。
                        vectors = getattr(batch, "vectors", batch)
                        if not isinstance(vectors, list):
                            vectors = [engine.encode(t) for t in texts]
                    else:
                        vectors = [engine.encode(t) for t in texts]
                except Exception as e:  # noqa: BLE001
                    logger.warning("向量索引：embedding 批量计算失败: %s", e)
                    return {"computed": 0, "entry_count": len(records)}

                for (kid, entry), vec in zip(to_compute, vectors):
                    if vector_math.isZeroVector(vec):
                        # 引擎兜底零向量＝"这一路没算出来"，不是"这条与谁都无关"。
                        # 落库即让该条对检索永久隐身（余弦恒 0），且下一轮指纹相同
                        # 不会重算——缺陷在读数里完全不可见。不落记录，下轮重试。
                        continue
                    records[kid] = {
                        "vector": [float(x) for x in (vec or [])],
                        "fingerprint": _fingerprint(entry),
                        "title": str(entry.get("title", "")),
                        "content": str(entry.get("content", ""))[:2000],
                    }
                self._computed += len(to_compute)

            uid = str((user or {}).get("user_id") or "default")
            if to_compute or removed_count or engine_reset:
                self._recordVersions[uid] = self._recordVersions.get(uid, 0) + 1
            self._save_user(user, records, current_engine_id)
            self._cache[uid] = records
            self._last_uid = uid
            return {"computed": len(to_compute), "entry_count": len(records)}

    def dropEntry(self, knowledgeId: str) -> Dict[str, int]:
        """从所有用户分片里取掉该条目的向量与正文副本。

        `ensure_indexed` 会在下一次检索时按可见集合自愈式剔除（见其"剔除已删除条目"
        一段），但那要等到有人查询才发生——违规内容清理不能把删除寄托在下一次检索上：
        在那之前，分片文件里的 `content` 副本一直是可读的。所以擦除当场改写分片。

        Returns:
            {"files": 改写的分片数, "records": 取掉的副本数}
        """
        removed = files = 0
        with self._lock:
            for path in sorted(self._dir.glob("knowledge_vectors_*.json")):
                uid = path.stem.split("_")[-1]
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001 - 分片坏了不该顶住擦除
                    logger.warning("向量分片擦除时读取失败 %s: %s", path, e)
                    continue
                records = data.get("vectors") if isinstance(data, dict) else None
                if not isinstance(records, dict) or knowledgeId not in records:
                    continue
                records.pop(knowledgeId, None)
                self._cache[uid] = records
                self._recordVersions[uid] = self._recordVersions.get(uid, 0) + 1
                self._annIndexes.pop(uid, None)
                self._annVersions.pop(uid, None)
                self._annFailures.pop(uid, None)
                self._save_user({"user_id": uid}, records, str(data.get("engine", "")))
                files += 1
                removed += 1
        return {"files": files, "records": removed}

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
        if vector_math.isZeroVector(qv):
            return []

        annHits = self._searchAnn(
            str((user or {}).get("user_id") or "default"),
            dict(items),
            qv,
            top_k,
        )
        if annHits is not None:
            return annHits

        scored: List[Tuple[str, float, Dict[str, Any]]] = []
        for kid, rec in items:
            score = vector_math.cosineSimilarity(qv, rec.get("vector") or [])
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

    def indexedUserIds(self) -> List[str]:
        """已有向量分片的用户 id（从磁盘文件反推，不靠内存缓存）。"""
        with self._lock:
            uids = []
            for path in sorted(self._dir.glob("knowledge_vectors_*.json")):
                uid = path.stem[len("knowledge_vectors_"):]
                if uid:
                    uids.append(uid)
            return sorted(set(uids))

    def maintainAll(self, repo: Any, force: bool = False) -> Dict[str, Any]:
        """对所有已有分片的用户做增量自愈；force=True 时先清分片再重算。"""
        users = self.indexedUserIds()
        computed = entries = 0
        errors: List[Dict[str, str]] = []
        for uid in users:
            try:
                if force and self._get_engine() is not None:
                    with self._lock:
                        self._cache.pop(uid, None)
                        self._recordVersions[uid] = self._recordVersions.get(uid, 0) + 1
                        self._annIndexes.pop(uid, None)
                        self._annVersions.pop(uid, None)
                        self._annFailures.pop(uid, None)
                    self._file_for({"user_id": uid}).unlink(missing_ok=True)
                stats = self.ensure_indexed(repo, {"user_id": uid})
                computed += int(stats.get("computed", 0))
                entries += int(stats.get("entry_count", 0))
            except Exception as exc:  # noqa: BLE001 - 单用户坏分片不顶住整轮维护
                errors.append({"user_id": uid, "error": str(exc)})
        return {
            "force": bool(force),
            "users": len(users),
            "computed": computed,
            "entries": entries,
            "errors": errors,
        }

    def health(self) -> Dict[str, Any]:
        """只读索引健康度：分片文件数、向量总数、引擎分布、坏文件。"""
        with self._lock:
            files = sorted(self._dir.glob("knowledge_vectors_*.json"))
            records = 0
            engines: Dict[str, int] = {}
            errors: List[Dict[str, str]] = []
            for path in files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    vectors = data.get("vectors") if isinstance(data, dict) else {}
                    records += len(vectors) if isinstance(vectors, dict) else 0
                    engine = str(data.get("engine", "") or "unknown") if isinstance(data, dict) else "unknown"
                    engines[engine] = engines.get(engine, 0) + 1
                except Exception as exc:  # noqa: BLE001 - 坏分片要报，不顶住健康读数
                    errors.append({"file": path.name, "error": str(exc)})
            annBackend = self._getAnn()
            return {
                "files": len(files),
                "records": records,
                "engines": engines,
                "cached_users": len(self._cache),
                "computed": self._computed,
                "errors": errors,
                "ann": {
                    "enabled": annBackend is not None,
                    "backend": getattr(annBackend, "name", None) if annBackend else None,
                    "reason": self._annReason or None,
                    "min_records": self._annMinRecords,
                    "indexed_users": len(self._annIndexes),
                    "failed_users": len(self._annFailures),
                    "last_error": self._annLastError or None,
                },
            }


_singleton: Optional[KnowledgeVectorIndex] = None
_singleton_lock = threading.Lock()


def get_knowledge_vector_index() -> KnowledgeVectorIndex:
    """全局单例（默认目录 + 惰性默认引擎）。"""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = KnowledgeVectorIndex(DEFAULT_STORAGE_DIR)
    return _singleton
