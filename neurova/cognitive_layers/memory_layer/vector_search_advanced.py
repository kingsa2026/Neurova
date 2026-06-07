"""
高级向量检索引擎 - 支持多种后端
- TF-IDF (默认，纯 Python 实现)
- FAISS (高性能向量搜索)
- ChromaDB (本地向量数据库)
"""

from collections import Counter
import json
import logging
import math
import os
from pathlib import Path
import pickle
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False

logger = logging.getLogger(__name__)


# ────── 基类 ──────

class VectorSearchBackend:
    """向量搜索后端抽象基类"""

    def __init__(self, name: str = "base"):
        self.name = name
        self._lock = threading.RLock()

    def add_texts(self, texts: List[str], ids: List[str],
                  metadatas: Optional[List[Dict[str, Any]]] = None) -> int:
        raise NotImplementedError

    def add_text(self, text: str, doc_id: str,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float, Dict[str, Any]]]:
        raise NotImplementedError

    def remove(self, doc_id: str) -> bool:
        raise NotImplementedError

    def clear(self):
        raise NotImplementedError

    def save(self, path: str):
        raise NotImplementedError

    def load(self, path: str):
        raise NotImplementedError

    def get_stats(self) -> Dict[str, Any]:
        return {"backend": self.name, "size": self.size()}

    def get_corpus(self) -> Dict[str, str]:
        raise NotImplementedError

    def get_doc_ids(self) -> List[str]:
        raise NotImplementedError

    def size(self) -> int:
        return 0


# ────── 同义词字典 ──────

class SynonymDictionary:
    """同义词字典，用于查询扩展"""

    _BUILTIN_SYNONYMS: Dict[str, List[str]] = {
        "记忆": ["回忆", "印象", "记性", "memories", "memory"],
        "学习": ["学", "习得", "学习", "learn", "study"],
        "思考": ["想", "琢磨", "考虑", "think", "reason"],
        "知识": ["学识", "学问", "knowledge"],
        "问题": ["难题", "疑问", "question", "issue", "problem"],
        "方法": ["办法", "方式", "途径", "method", "approach"],
        "重要": ["关键", "核心", "essential", "important", "critical"],
        "创建": ["建立", "生成", "create", "build", "generate"],
        "删除": ["移除", "去掉", "delete", "remove"],
        "更新": ["修改", "变更", "update", "modify"],
        "搜索": ["查找", "检索", "寻找", "search", "find", "query"],
    }

    def __init__(self):
        self._synonyms: Dict[str, List[str]] = {}
        self._load_builtin()

    def _load_builtin(self):
        for word, synonyms in self._BUILTIN_SYNONYMS.items():
            self._synonyms[word] = list(synonyms)

    def get_synonyms(self, word: str) -> List[str]:
        return self._synonyms.get(word.lower(), [])

    def add_synonym(self, word: str, synonym: str):
        word_lower = word.lower()
        if word_lower not in self._synonyms:
            self._synonyms[word_lower] = []
        if synonym.lower() not in self._synonyms[word_lower]:
            self._synonyms[word_lower].append(synonym.lower())

    def remove_synonym(self, word: str, synonym: str):
        word_lower = word.lower()
        if word_lower in self._synonyms:
            self._synonyms[word_lower] = [
                s for s in self._synonyms[word_lower] if s != synonym.lower()
            ]

    def set_synonyms(self, word: str, synonyms: List[str]):
        self._synonyms[word.lower()] = [s.lower() for s in synonyms]

    def delete_word(self, word: str):
        self._synonyms.pop(word.lower(), None)

    def load_from_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            self._synonyms.update(data)

    def save_to_file(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._synonyms, f, indent=2, ensure_ascii=False)

    def get_all_words(self) -> List[str]:
        return list(self._synonyms.keys())

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_words": len(self._synonyms),
            "total_synonyms": sum(len(v) for v in self._synonyms.values()),
        }

    def expand_query(self, query: str) -> str:
        """用同义词扩展查询"""
        words = query.split()
        expanded = list(words)
        for word in words:
            synonyms = self.get_synonyms(word)
            expanded.extend(synonyms[:2])  # 最多添加2个同义词
        return " ".join(expanded)


# ────── TF-IDF 后端 ──────

class TFIDFBackend(VectorSearchBackend):
    """纯 Python TF-IDF 后端"""

    def __init__(self, use_synonyms: bool = True):
        super().__init__("tfidf")
        self._corpus: Dict[str, str] = {}  # doc_id -> text
        self._metadatas: Dict[str, Dict[str, Any]] = {}
        self._idf: Dict[str, float] = {}
        self._tf_idf: Dict[str, Dict[str, float]] = {}
        self._vocabulary: Dict[str, int] = {}
        self._synonym_dict = SynonymDictionary() if use_synonyms else None
        self._fitted = False

    def _tokenize(self, text: str) -> List[str]:
        """简单分词"""
        import re
        text = text.lower()
        # 中文按字符分，英文按空格分
        tokens = []
        # 英文单词
        tokens.extend(re.findall(r"[a-z]+", text))
        # 中文字符（单字 + 连续字符）
        chinese = re.findall(r"[\u4e00-\u9fff]+", text)
        tokens.extend(chinese)
        # 中文单字也加入
        for seg in chinese:
            if len(seg) > 1:
                tokens.extend(list(seg))
        return tokens

    def _expand_query(self, query: str) -> str:
        if self._synonym_dict:
            return self._synonym_dict.expand_query(query)
        return query

    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        counter = Counter(tokens)
        total = len(tokens) if tokens else 1
        return {t: c / total for t, c in counter.items()}

    def _compute_idf(self):
        n_docs = len(self._corpus)
        if n_docs == 0:
            self._idf = {}
            return
        doc_freq: Dict[str, int] = {}
        for text in self._corpus.values():
            tokens = set(self._tokenize(text))
            for t in tokens:
                doc_freq[t] = doc_freq.get(t, 0) + 1
        self._idf = {t: math.log((n_docs + 1) / (df + 1)) + 1 for t, df in doc_freq.items()}

    def add_texts(self, texts: List[str], ids: List[str],
                  metadatas: Optional[List[Dict[str, Any]]] = None) -> int:
        with self._lock:
            count = 0
            for i, (text, doc_id) in enumerate(zip(texts, ids)):
                self._corpus[doc_id] = text
                if metadatas and i < len(metadatas):
                    self._metadatas[doc_id] = metadatas[i]
                count += 1
            self._fitted = False
            return count

    def add_text(self, text: str, doc_id: str,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        with self._lock:
            self._corpus[doc_id] = text
            if metadata:
                self._metadatas[doc_id] = metadata
            self._fitted = False
            return True

    def rebuild_index(self):
        """重建 TF-IDF 索引"""
        with self._lock:
            self._compute_idf()
            self._tf_idf = {}
            for doc_id, text in self._corpus.items():
                tokens = self._tokenize(text)
                tf = self._compute_tf(tokens)
                self._tf_idf[doc_id] = {
                    t: tf_val * self._idf.get(t, 1.0) for t, tf_val in tf.items()
                }
            self._fitted = True

    def _cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        common = set(vec1.keys()) & set(vec2.keys())
        dot = sum(vec1[k] * vec2[k] for k in common)
        norm1 = math.sqrt(sum(v * v for v in vec1.values())) or 1e-10
        norm2 = math.sqrt(sum(v * v for v in vec2.values())) or 1e-10
        return dot / (norm1 * norm2)

    def search(self, query: str, top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float, Dict[str, Any]]]:
        with self._lock:
            if not self._fitted:
                self.rebuild_index()
            if not self._tf_idf:
                return []

            expanded = self._expand_query(query)
            tokens = self._tokenize(expanded)
            tf = self._compute_tf(tokens)
            query_vec = {t: tf_val * self._idf.get(t, 1.0) for t, tf_val in tf.items()}

            scores = []
            for doc_id, doc_vec in self._tf_idf.items():
                # 过滤
                if filters:
                    meta = self._metadatas.get(doc_id, {})
                    if not all(meta.get(k) == v for k, v in filters.items()):
                        continue
                sim = self._cosine_similarity(query_vec, doc_vec)
                scores.append((doc_id, sim, self._metadatas.get(doc_id, {})))

            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id in self._corpus:
                del self._corpus[doc_id]
                self._metadatas.pop(doc_id, None)
                self._tf_idf.pop(doc_id, None)
                return True
            return False

    def get_corpus(self) -> Dict[str, str]:
        return dict(self._corpus)

    def get_doc_ids(self) -> List[str]:
        return list(self._corpus.keys())

    def clear(self):
        with self._lock:
            self._corpus.clear()
            self._metadatas.clear()
            self._tf_idf.clear()
            self._vocabulary.clear()
            self._fitted = False

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "corpus": self._corpus,
            "metadatas": self._metadatas,
            "idf": self._idf,
            "tf_idf": self._tf_idf,
            "fitted": self._fitted,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, path: str):
        with open(path, "rb") as f:
            data = pickle.load(f)
        with self._lock:
            self._corpus = data.get("corpus", {})
            self._metadatas = data.get("metadatas", {})
            self._idf = data.get("idf", {})
            self._tf_idf = data.get("tf_idf", {})
            self._fitted = data.get("fitted", False)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "size": self.size(),
            "fitted": self._fitted,
            "vocabulary_size": len(self._idf),
            "has_synonyms": self._synonym_dict is not None,
        }

    def size(self) -> int:
        return len(self._corpus)


# ────── FAISS 后端 ──────

class FaissBackend(VectorSearchBackend):
    """FAISS 向量搜索后端"""

    def __init__(self, dimension: int = 384, use_gpu: bool = False):
        super().__init__("faiss")
        if not HAS_FAISS:
            raise ImportError("faiss 库未安装")
        self._dimension = dimension
        self._use_gpu = use_gpu
        self._index: Optional[Any] = None
        self._doc_ids: List[str] = []
        self._metadatas: Dict[str, Dict[str, Any]] = {}
        self._model: Optional[Any] = None
        self._init_index()
        self._init_model()

    def _init_index(self):
        if HAS_FAISS:
            self._index = faiss.IndexFlatIP(self._dimension)
            if self._use_gpu and hasattr(faiss, "StandardGpuResources"):
                try:
                    res = faiss.StandardGpuResources()
                    self._index = faiss.index_cpu_to_gpu(res, 0, self._index)
                except Exception:
                    pass

    def _init_model(self):
        if HAS_SENTENCE_TRANSFORMERS:
            try:
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception as e:
                logger.warning(f"Failed to load sentence transformer: {e}")

    def _get_embeddings(self, texts: List[str]) -> Any:
        if self._model and HAS_NUMPY:
            return self._model.encode(texts, normalize_embeddings=True)
        raise RuntimeError("No embedding model available")

    def add_texts(self, texts: List[str], ids: List[str],
                  metadatas: Optional[List[Dict[str, Any]]] = None) -> int:
        with self._lock:
            embeddings = self._get_embeddings(texts)
            self._index.add(embeddings)
            for i, doc_id in enumerate(ids):
                self._doc_ids.append(doc_id)
                if metadatas and i < len(metadatas):
                    self._metadatas[doc_id] = metadatas[i]
            return len(texts)

    def add_text(self, text: str, doc_id: str,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        return self.add_texts([text], [doc_id], [metadata] if metadata else None) > 0

    def search(self, query: str, top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float, Dict[str, Any]]]:
        with self._lock:
            if self._index.ntotal == 0:
                return []
            q_emb = self._get_embeddings([query])
            k = min(top_k, self._index.ntotal)
            scores, indices = self._index.search(q_emb, k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._doc_ids):
                    continue
                doc_id = self._doc_ids[idx]
                meta = self._metadatas.get(doc_id, {})
                if filters and not all(meta.get(k) == v for k, v in filters.items()):
                    continue
                results.append((doc_id, float(score), meta))
            return results

    def remove(self, doc_id: str) -> bool:
        logger.warning("FAISS backend does not support individual removal; use rebuild")
        return False

    def clear(self):
        with self._lock:
            self._init_index()
            self._doc_ids.clear()
            self._metadatas.clear()

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        faiss.write_index(self._index, os.path.join(path, "faiss.index"))
        with open(os.path.join(path, "doc_ids.json"), "w") as f:
            json.dump(self._doc_ids, f)
        with open(os.path.join(path, "metadatas.json"), "w") as f:
            json.dump(self._metadatas, f, ensure_ascii=False)

    def load(self, path: str):
        self._index = faiss.read_index(os.path.join(path, "faiss.index"))
        with open(os.path.join(path, "doc_ids.json"), "r") as f:
            self._doc_ids = json.load(f)
        with open(os.path.join(path, "metadatas.json"), "r") as f:
            self._metadatas = json.load(f)

    def size(self) -> int:
        return self._index.ntotal if self._index else 0


# ────── ChromaDB 后端 ──────

class ChromaDBBackend(VectorSearchBackend):
    """ChromaDB 向量搜索后端"""

    def __init__(self, collection_name: str = "neurova_memories",
                 persist_directory: Optional[str] = None):
        super().__init__("chromadb")
        if not HAS_CHROMADB:
            raise ImportError("chromadb 库未安装")
        self._collection_name = collection_name
        if persist_directory:
            self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(collection_name)

    def add_texts(self, texts: List[str], ids: List[str],
                  metadatas: Optional[List[Dict[str, Any]]] = None) -> int:
        self._collection.add(documents=texts, ids=ids, metadatas=metadatas)
        return len(texts)

    def add_text(self, text: str, doc_id: str,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        self._collection.add(documents=[text], ids=[doc_id],
                            metadatas=[metadata] if metadata else None)
        return True

    def search(self, query: str, top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float, Dict[str, Any]]]:
        results = self._collection.query(
            query_texts=[query], n_results=top_k, where=filters
        )
        output = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                dist = results["distances"][0][i] if results["distances"] else 0
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                score = 1.0 / (1.0 + dist)  # 转为相似度
                output.append((doc_id, score, meta))
        return output

    def remove(self, doc_id: str) -> bool:
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False

    def clear(self):
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(self._collection_name)

    def save(self, path: str):
        pass  # ChromaDB 持久化由客户端管理

    def load(self, path: str):
        pass

    def get_stats(self) -> Dict[str, Any]:
        return {
            "backend": self.name,
            "size": self._collection.count(),
            "collection": self._collection_name,
        }

    def size(self) -> int:
        return self._collection.count()


# ────── 统一接口 ──────

class AdvancedVectorSearch:
    """高级向量搜索统一接口"""

    def __init__(self, backend: str = "auto", **kwargs):
        self._backend_name = backend
        self._backend: VectorSearchBackend = self._create_backend(backend, **kwargs)
        logger.info(f"AdvancedVectorSearch created with backend={self._backend.name}")

    def _create_backend(self, backend: str, **kwargs) -> VectorSearchBackend:
        backend = backend.lower()
        if backend == "chromadb" and HAS_CHROMADB:
            return ChromaDBBackend(**kwargs)
        if backend == "faiss" and HAS_FAISS and HAS_SENTENCE_TRANSFORMERS:
            return FaissBackend(**kwargs)
        if backend == "tfidf":
            return TFIDFBackend(**kwargs)
        # auto: 尝试最佳可用
        if backend == "auto":
            if HAS_CHROMADB:
                return ChromaDBBackend(**kwargs)
            if HAS_FAISS and HAS_SENTENCE_TRANSFORMERS:
                return FaissBackend(**kwargs)
            return TFIDFBackend(**kwargs)
        # fallback
        logger.warning(f"Backend '{backend}' not available, falling back to TF-IDF")
        return TFIDFBackend(**kwargs)

    def add_texts(self, texts: List[str], ids: List[str],
                  metadatas: Optional[List[Dict[str, Any]]] = None) -> int:
        return self._backend.add_texts(texts, ids, metadatas)

    def add_text(self, text: str, doc_id: str,
                 metadata: Optional[Dict[str, Any]] = None) -> bool:
        return self._backend.add_text(text, doc_id, metadata)

    def add(self, text: str, doc_id: str,
            metadata: Optional[Dict[str, Any]] = None) -> bool:
        return self.add_text(text, doc_id, metadata)

    def search(self, query: str, top_k: int = 10,
               filters: Optional[Dict[str, Any]] = None) -> List[Tuple[str, float, Dict[str, Any]]]:
        return self._backend.search(query, top_k, filters)

    def remove(self, doc_id: str) -> bool:
        return self._backend.remove(doc_id)

    def remove_text(self, doc_id: str) -> bool:
        return self.remove(doc_id)

    def clear(self):
        self._backend.clear()

    def save(self, path: str):
        self._backend.save(path)

    def load(self, path: str):
        self._backend.load(path)

    def get_stats(self) -> Dict[str, Any]:
        return self._backend.get_stats()

    def size(self) -> int:
        return self._backend.size()

    def corpus_size(self) -> int:
        return self.size()

    def is_fitted(self) -> bool:
        if isinstance(self._backend, TFIDFBackend):
            return self._backend._fitted
        return True

    def rebuild_index(self):
        if isinstance(self._backend, TFIDFBackend):
            self._backend.rebuild_index()


# ────── 工具函数 ──────

def get_available_backends() -> List[str]:
    """获取可用的后端列表"""
    backends = ["tfidf"]
    if HAS_FAISS:
        backends.append("faiss")
    if HAS_CHROMADB:
        backends.append("chromadb")
    return backends


def create_vector_search(backend: str = "auto", **kwargs) -> AdvancedVectorSearch:
    """工厂函数创建向量搜索实例"""
    return AdvancedVectorSearch(backend=backend, **kwargs)