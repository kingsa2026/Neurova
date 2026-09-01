"""
UnifiedVectorStore — 三合一向量索引

一个向量索引服务三个目的:
1. 路由: query_vec vs centroids → Top-K Expert
2. 兜底: query_vec vs memories → Top-K 记忆
3. 可塑性: centroid drift (LTP/LTD 更新质心位置)

支持 Tier 0/1/2/3 后端:
- Tier 0: TF-IDF (零依赖)
- Tier 1: ONNXEmbedding (~130MB, ONNX Runtime)
- Tier 2: fastembed (~50MB)
- Tier 3: FAISS + sentence-transformers (~2GB)
"""

from neurova.core.logger import get_logger
import hashlib
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


def vector_norm(a: List[float]) -> float:
    """计算向量范数"""
    return math.sqrt(sum(x * x for x in a))


def vector_dot(a: List[float], b: List[float]) -> float:
    """计算向量点积"""
    return sum(x * y for x, y in zip(a, b))


def vector_normalize(a: List[float]) -> List[float]:
    """归一化向量"""
    norm = vector_norm(a)
    if norm == 0:
        return a
    return [x / norm for x in a]


class UnifiedVectorStore:
    """三合一向量索引"""

    def __init__(self, backend: str = "auto"):
        """
        初始化向量存储

        Args:
            backend: 后端类型 ("tfidf", "fastembed", "faiss", "auto")
        """
        self.backend = self._select_backend(backend)
        self.index = None
        self.centroids: Dict[str, List[float]] = {}  # expert_id → vector
        self.memory_vectors: List[List[float]] = []  # 记忆向量列表
        self.memory_ids: List[str] = []  # 与 memory_vectors 对应的记忆 ID
        self.memory_metadata: List[Dict] = []  # 记忆元数据
        self._centroid_last_access: Dict[str, float] = {}  # 质心最后访问时间

        # numpy 加速矩阵（backend 维度固定时构建；tfidf 维度漂移时为 None 回退 list）
        self._np_matrix = None

        # TF-IDF 相关
        self._tfidf_vocabulary: Dict[str, int] = {}
        self._idf_values: Dict[str, float] = {}
        self._document_vectors: List[Dict[int, float]] = []

        # Neurova Hebb 向量索引
        self._neurova_hebb_vectors: List[List[float]] = []
        self._neurova_hebb_ids: List[str] = []
        self._neurova_hebb_metadata: List[Dict] = []

        # 初始化编码器
        self._encoder = self._create_encoder()

        logger.info("UnifiedVectorStore 初始化完成，后端: %s", self.backend)

    async def initialize_encoder(self) -> bool:
        """
        异步初始化编码器（用于 ONNX 后端的懒加载）

        Returns:
            初始化是否成功
        """
        if self.backend == "onnx" and self._encoder and not self._encoder.is_initialized:
            try:
                return await self._encoder.initialize()
            except Exception as e:
                logger.warning("ONNX 编码器异步初始化失败: %s", e)
                return False
        return True

    def _select_backend(self, backend: str) -> str:
        """根据环境自动选择后端（按真实可用性探测：faiss→fastembed→onnx→tfidf）"""
        if backend != "auto":
            return backend

        try:
            import faiss  # noqa: F401

            return "faiss"
        except ImportError:
            pass

        try:
            import fastembed  # noqa: F401

            return "fastembed"
        except ImportError:
            pass

        # Tier 1: ONNX Embedding (默认推荐，本地模型 models/embedding/bge-small-zh-v1.5)
        try:
            from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine  # noqa: F401

            return "onnx"
        except ImportError:
            pass

        return "tfidf"

    def _create_encoder(self):
        """创建编码器"""
        if self.backend == "faiss":
            try:
                from sentence_transformers import SentenceTransformer

                model_name = "BAAI/bge-small-zh-v1.5"

                # 先检查本地缓存，避免网络不通时阻塞启动
                # HuggingFace 缓存路径: ~/.cache/huggingface/hub/models--{org}--{model}/
                cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
                cache_model_dir = cache_dir / f"models--{model_name.replace('/', '--')}"
                if not cache_model_dir.exists():
                    logger.warning(
                        "FAISS 编码器模型未缓存: %s，跳过加载，降级到 TF-IDF。"
                        "如需使用 FAISS，请先离线下载模型或配置代理后运行一次。",
                        model_name,
                    )
                    return None

                logger.info("正在加载 FAISS 编码器模型: %s (本地缓存)", model_name)
                encoder = SentenceTransformer(model_name, cache_folder=str(cache_dir))
                logger.info("FAISS 编码器模型加载成功: %s", model_name)
                return encoder
            except Exception as e:
                logger.warning("FAISS 编码器创建失败: %s，降级到 TF-IDF", e)
                return None

        elif self.backend == "fastembed":
            try:
                from fastembed import TextEmbedding

                return TextEmbedding("BAAI/bge-small-zh-v1.5")
            except Exception as e:
                logger.warning("fastembed 编码器创建失败: %s，降级到 TF-IDF", e)
                return None

        elif self.backend == "onnx":
            try:
                from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine

                engine = ONNXEmbeddingEngine(auto_download=True)
                return engine
            except Exception as e:
                logger.warning("ONNX 编码器创建失败: %s，降级到 TF-IDF", e)
                return None

        return None  # TF-IDF 不需要预训练编码器

    def encode(self, text: str) -> List[float]:
        """
        将文本编码为向量

        Args:
            text: 输入文本

        Returns:
            归一化向量
        """
        if self.backend in ("faiss", "fastembed", "onnx") and self._encoder:
            # 使用预训练模型
            if self.backend == "faiss":
                vec = self._encoder.encode(text, normalize_embeddings=True)
            elif self.backend == "onnx":
                # 懒初始化 ONNX 引擎
                if not self._encoder.is_initialized:
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop and loop.is_running():
                        # 已有运行的事件循环，无法同步初始化
                        logger.warning("ONNX 编码器未初始化，降级到 TF-IDF")
                        return self._tfidf_encode(text)
                    else:
                        asyncio.run(self._encoder.initialize())
                        if not self._encoder.is_initialized:
                            logger.warning("ONNX 编码器初始化失败，降级到 TF-IDF")
                            return self._tfidf_encode(text)

                return self._encoder.encode(text)
            else:
                vec = list(self._encoder.embed([text]))[0]
            return list(vec)

        # TF-IDF 编码
        return self._tfidf_encode(text)

    def _tfidf_encode(self, text: str) -> List[float]:
        """TF-IDF 编码，词汇表为空时使用 hash 编码兜底"""
        # 简单分词
        tokens = self._tokenize(text)
        dim = max(len(self._tfidf_vocabulary), 100)
        if not tokens:
            return [0.0] * dim

        # 词汇表为空时，使用 hash 编码（用于质心初始化等场景）
        if not self._idf_values:
            result = [0.0] * dim
            for token in tokens:
                # [确定性] 必须用稳定哈希：Python 内建 hash() 受 PYTHONHASHSEED
                # 随机化影响，跨进程同一 token 落点不同，导致无关文本的余弦
                # 相似度变成随机噪声（曾引发语义调取门槛随机失效）
                idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dim
                result[idx] += 1.0
            norm = vector_norm(result)
            if norm > 0:
                result = [x / norm for x in result]
            return result

        # 计算 TF
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        max_tf = max(tf.values()) if tf else 1

        # 计算向量
        vec = {}
        for token, count in tf.items():
            if token in self._idf_values:
                tf_norm = 0.5 + 0.5 * (count / max_tf)
                vec[token] = tf_norm * self._idf_values[token]

        # 转为固定维度向量
        result = [0.0] * dim
        for token, value in vec.items():
            if token in self._tfidf_vocabulary:
                idx = self._tfidf_vocabulary[token]
                if idx < dim:
                    result[idx] = value

        # 归一化
        norm = vector_norm(result)
        if norm > 0:
            result = [x / norm for x in result]

        return result

    def _tokenize(self, text: str) -> List[str]:
        """简单分词"""
        import re

        # 英文单词
        english_words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        # 中文字符
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        return english_words + chinese_chars

    def _update_idf(self, documents: List[str]):
        """更新 IDF 值"""
        import math

        n_docs = len(documents)
        if n_docs == 0:
            return

        # 统计文档频率
        df = {}
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                df[token] = df.get(token, 0) + 1

        # 计算 IDF
        self._idf_values = {}
        for token, freq in df.items():
            self._idf_values[token] = math.log((n_docs + 1) / (freq + 1)) + 1

        # 更新词汇表
        for token in self._idf_values:
            if token not in self._tfidf_vocabulary:
                self._tfidf_vocabulary[token] = len(self._tfidf_vocabulary)

    def initialize_centroids(self, experts: Dict[str, Dict[str, Any]]):
        """
        用每个 Expert 的标签文本初始化质心 — 神经元集群的整合信号

        初始化每个专家神经元的代表性向量，模拟神经元集群的整合信号。

        神经隐喻:
        - 专家定义: 像神经元集群的功能特化
        - 标签文本: 像神经元集群的输入模式
        - 质心向量: 像神经元集群的整合信号，代表概念原型
        - 归一化: 像神经元的发放率标准化

        Args:
            experts: Expert 定义字典（神经元集群的功能特化）
        """
        for expert_id, expert_def in experts.items():
            desc = self._expert_to_text(expert_def)
            centroid = self.encode(desc)

            # 归一化
            norm = vector_norm(centroid)
            if norm > 0:
                centroid = vector_normalize(centroid)

            self.centroids[expert_id] = centroid
            self._centroid_last_access[expert_id] = datetime.now().timestamp()

        logger.info("初始化 %s 个质心", len(experts))

    def _expert_to_text(self, expert_def: Dict[str, Any]) -> str:
        """将 Expert 定义转为可编码的文本"""
        parts = []
        if "category" in expert_def:
            parts.append(f"类别: {expert_def['category']}")
        if "centroid_text" in expert_def:
            parts.append(expert_def["centroid_text"])
        if "lifecycle_stage" in expert_def:
            parts.append(f"阶段: {expert_def['lifecycle_stage']}")
        return " | ".join(parts) if parts else "通用记忆"

    def index_memories(self, memories: List[Dict[str, Any]], incremental: bool = False):
        """
        索引记忆列表

        Args:
            memories: 记忆字典列表，必须包含 'id' 和 'content'
            incremental: True 时追加到已有索引（后台渐进索引用），
                         默认 False 保持原语义（清空重建）
        """
        # 增量去重：同 id 不重复索引
        existing_ids = set(self.memory_ids)

        if incremental:
            # 资源修复: 原实现每次调用都对全批文档重新分词统计 IDF,
            # _semantic_recall 每轮召回都传入全量记忆列表 → 纯 Python
            # 全库分词一次。现在只对新文档更新 IDF(编码前的词表/IDF 一致)。
            new_docs = [
                m.get("content", "") for m in memories if m.get("id", "") not in existing_ids
            ]
            if new_docs:
                self._update_idf(new_docs)
        else:
            self._update_idf([m.get("content", "") for m in memories])
            self.memory_vectors = []
            self.memory_ids = []
            self.memory_metadata = []
            self._np_matrix = None

        added = 0
        for mem in memories:
            mem_id = mem.get("id", "")
            if mem_id and mem_id in existing_ids:
                continue

            content = mem.get("content", "")
            vec = self.encode(content)

            # 归一化
            norm = vector_norm(vec)
            if norm > 0:
                vec = vector_normalize(vec)

            self.memory_vectors.append(vec)
            self.memory_ids.append(mem_id)
            self.memory_metadata.append(mem)
            if mem_id:
                existing_ids.add(mem_id)
            added += 1

        # 无所加时跳过整矩阵重建(20k 条向量 copy 无谓开销)
        if added > 0 or self._np_matrix is None:
            self._refresh_numpy_matrix()

        logger.info("索引 %s 条记忆（新增 %s，总索引 %s）", len(memories), added, len(self.memory_ids))

    def _refresh_numpy_matrix(self) -> None:
        """重建 numpy 加速矩阵；向量维度不齐（tfidf 词表漂移）时置 None 回退暴力搜索"""
        try:
            import numpy as np
        except ImportError:
            self._np_matrix = None
            return

        if not self.memory_vectors:
            self._np_matrix = None
            return

        dim = len(self.memory_vectors[0])
        if any(len(v) != dim for v in self.memory_vectors):
            logger.warning("向量维度不齐，numpy 加速不可用，回退暴力搜索")
            self._np_matrix = None
            return

        self._np_matrix = np.asarray(self.memory_vectors, dtype=np.float32)

    def get_expert_centroids(self) -> Dict[str, List[float]]:
        """获取所有 Expert 质心"""
        return self.centroids.copy()

    def get_centroid(self, expert_id: str) -> Optional[List[float]]:
        """获取单个 Expert 质心"""
        return self.centroids.get(expert_id)

    def update_centroid(self, expert_id: str, new_centroid: List[float]):
        """更新质心"""
        # 归一化
        norm = vector_norm(new_centroid)
        if norm > 0:
            new_centroid = vector_normalize(new_centroid)
        self.centroids[expert_id] = new_centroid

    def touch_centroid(self, expert_id: str):
        """更新质心最后访问时间"""
        self._centroid_last_access[expert_id] = datetime.now().timestamp()

    def get_centroid_last_access(self, expert_id: str) -> float:
        """获取质心最后访问时间"""
        return self._centroid_last_access.get(expert_id, 0)

    def get_all_centroids(self) -> List[Tuple[str, List[float]]]:
        """获取所有质心及其 ID"""
        return [(k, v) for k, v in self.centroids.items()]

    def search(self, query: str, limit: int = 10, filter_dict: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        搜索记忆

        Args:
            query: 查询文本
            limit: 返回数量限制
            filter_dict: 过滤条件

        Returns:
            排序后的记忆列表
        """
        if not self.memory_vectors:
            return []

        query_vec = self.encode(query)
        norm = vector_norm(query_vec)
        if norm > 0:
            query_vec = vector_normalize(query_vec)

        # numpy 快路径（维度齐 + 无过滤时）：矩阵点积替代逐条暴力扫描
        if self._np_matrix is not None and not filter_dict:
            try:
                import numpy as np

                q = np.asarray(query_vec, dtype=np.float32)
                if q.shape[0] != self._np_matrix.shape[1]:
                    self._np_matrix = None  # 查询向量维度漂移，重建
                else:
                    sims = self._np_matrix @ q
                    order = np.argsort(-sims)[:limit]
                    results = []
                    for idx in order:
                        score = float(sims[idx])
                        if score < 0:
                            continue
                        mem = self.memory_metadata[int(idx)].copy()
                        mem["score"] = score
                        results.append(mem)
                    return results
            except Exception as e:
                logger.warning("numpy 搜索失败，回退暴力扫描: %s", e)

        # 计算相似度
        scores = []
        for i, mem_vec in enumerate(self.memory_vectors):
            # 过滤
            if filter_dict:
                mem = self.memory_metadata[i]
                if not self._matches_filter(mem, filter_dict):
                    scores.append((i, -1.0))
                    continue

            # 余弦相似度
            sim = vector_dot(query_vec, mem_vec)
            scores.append((i, sim))

        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 返回结果
        results = []
        for idx, score in scores[:limit]:
            if score < 0:
                continue
            mem = self.memory_metadata[idx].copy()
            mem["score"] = score
            results.append(mem)

        return results

    def search_in_expert(self, query: str, expert_def: Dict, limit: int = 10) -> List[Dict[str, Any]]:
        """
        在特定 Expert 内搜索

        Args:
            query: 查询文本
            expert_def: Expert 定义
            limit: 返回数量限制

        Returns:
            排序后的记忆列表
        """
        return self.search(query, limit=limit, filter_dict=expert_def)

    # ── Neurova Hebb 向量索引 ──

    def add_neurova_hebb(self, neurova_hebb_id: str, embedding: List[float], metadata: Dict[str, Any]) -> None:
        """
        添加 Neurova Hebb 到向量索引。

        Args:
            neurova_hebb_id: Neurova Hebb 唯一标识
            embedding: 嵌入向量
            metadata: 附加元数据
        """
        norm = vector_norm(embedding)
        if norm > 0:
            embedding = vector_normalize(embedding)
        self._neurova_hebb_vectors.append(embedding)
        self._neurova_hebb_ids.append(neurova_hebb_id)
        self._neurova_hebb_metadata.append(metadata)

    def search_neurova_hebbs(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        """
        搜索最相似的 Neurova Hebb。

        Args:
            query_embedding: 查询向量
            top_k: 返回数量

        Returns:
            [(neurova_hebb_id, score), ...] 按相似度降序
        """
        if not self._neurova_hebb_vectors:
            return []

        norm = vector_norm(query_embedding)
        if norm > 0:
            query_embedding = vector_normalize(query_embedding)

        scores = []
        for i, vec in enumerate(self._neurova_hebb_vectors):
            sim = vector_dot(query_embedding, vec)
            scores.append((i, sim))

        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in scores[:top_k]:
            results.append((self._neurova_hebb_ids[idx], score))
        return results

    def remove_neurova_hebb(self, neurova_hebb_id: str) -> bool:
        """删除指定 Neurova Hebb，返回是否找到并删除。"""
        try:
            idx = self._neurova_hebb_ids.index(neurova_hebb_id)
            self._neurova_hebb_ids.pop(idx)
            self._neurova_hebb_vectors.pop(idx)
            self._neurova_hebb_metadata.pop(idx)
            return True
        except ValueError:
            return False

    def neurova_hebb_count(self) -> int:
        """返回 Neurova Hebb 索引中的条目数。"""
        return len(self._neurova_hebb_ids)

    def _matches_filter(self, memory: Dict, filter_dict: Dict) -> bool:
        """检查记忆是否匹配过滤条件"""
        for key, value in filter_dict.items():
            if key == "centroid_text":
                continue  # 跳过文本描述

            mem_value = memory.get(key)

            # 处理布尔值
            if isinstance(value, bool):
                if int(mem_value or 0) != int(value):
                    return False
            # 处理元组范围
            elif isinstance(value, tuple) and len(value) == 2:
                try:
                    mem_num = float(mem_value or 0)
                    if not (value[0] <= mem_num <= value[1]):
                        return False
                except (ValueError, TypeError):
                    return False
            # 精确匹配
            elif str(mem_value) != str(value):
                return False

        return True


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    norm_a = vector_norm(a)
    norm_b = vector_norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return vector_dot(a, b) / (norm_a * norm_b)
