"""
语义搜索工具

提供基于嵌入模型的语义相似度计算，支持：
- 文本嵌入生成
- 余弦相似度计算
- 批量相似度计算
- 缓存优化
"""

from neurova.core import vector_math
import hashlib
from neurova.core.logger import get_logger
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


class SemanticSearch:
    """
    语义搜索工具
    
    支持两种模式：
    1. 嵌入模式：使用嵌入模型计算语义相似度
    2. 规则模式：基于关键词和TF-IDF的简单相似度（无需模型）
    """
    
    def __init__(self, embedding_model=None, use_embedding: bool = True):
        """
        初始化语义搜索
        
        Args:
            embedding_model: 嵌入模型（可选）
            use_embedding: 是否使用嵌入模型
        """
        self._embedding_model = embedding_model
        self._use_embedding = use_embedding and embedding_model is not None
        self._cache: Dict[str, List[float]] = {}
        self._keyword_index: Dict[str, List[str]] = {}
        # M-07: 保护 _keyword_index 的并发读写。原 build/upsert/remove/search 全方法
        # 无锁；remove_memory_index 边迭代边 del，并发 upsert/remove/search 时会触发
        # RuntimeError: dictionary changed size during iteration。RLock 可重入，
        # upsert 内调用 remove 不会自死锁。
        self._index_lock = threading.RLock()
        
        logger.info("SemanticSearch 初始化: embedding=%s", self._use_embedding)
    
    def compute_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的语义相似度
        
        Args:
            text1: 文本1
            text2: 文本2
            
        Returns:
            相似度 0.0-1.0
        """
        if not text1 or not text2:
            return 0.0
        
        if self._use_embedding and self._embedding_model:
            return self._compute_embedding_similarity(text1, text2)
        else:
            return self._compute_keyword_similarity(text1, text2)
    
    def _compute_embedding_similarity(self, text1: str, text2: str) -> float:
        """使用嵌入模型计算相似度"""
        try:
            emb1 = self._get_embedding(text1)
            emb2 = self._get_embedding(text2)
            return vector_math.cosineSimilarity(emb1, emb2)
        except Exception as e:
            logger.warning("嵌入相似度计算失败: %s", e)
            return self._compute_keyword_similarity(text1, text2)
    
    def _compute_keyword_similarity(self, text1: str, text2: str) -> float:
        """基于关键词的相似度计算（TF-IDF简化版）"""
        # 提取关键词
        keywords1 = self._extract_keywords(text1)
        keywords2 = self._extract_keywords(text2)
        
        if not keywords1 or not keywords2:
            return 0.0
        
        # 计算Jaccard相似度
        set1 = set(keywords1)
        set2 = set(keywords2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        jaccard = intersection / union if union > 0 else 0.0
        
        # 加权：考虑关键词长度和位置
        weighted_score = self._compute_weighted_similarity(text1, text2, keywords1, keywords2)
        
        # 综合分数
        return 0.6 * jaccard + 0.4 * weighted_score
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（支持中英文）"""
        # 移除标点符号
        text = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', text.lower())
        
        keywords = []
        
        # 英文分词（按空格）
        english_words = text.split()
        keywords.extend([w for w in english_words if len(w) > 1 and w.isascii()])
        
        # 中文分词（多策略）
        # 策略1: 按常见分隔符分割
        cn_segments = re.split(r'[,，。！？\s]+', text)
        for seg in cn_segments:
            # 提取2-4个汉字的词
            cn_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', seg)
            keywords.extend(cn_words)
        
        # 策略2: 提取所有中文词（2-4个汉字）
        all_cn_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        keywords.extend(all_cn_words)
        
        # 策略3: 尝试按常见后缀分割（挂了、故障、错误等）
        suffixes = ['挂了', '故障', '错误', '失败', '成功', '超时', '慢了', '满了']
        for suffix in suffixes:
            pattern = r'([\u4e00-\u9fa5]{2,4})' + re.escape(suffix)
            matches = re.findall(pattern, text)
            for match in matches:
                keywords.append(match)
                keywords.append(suffix)
        
        # 去重
        keywords = list(set(keywords))
        
        # 过滤停用词和过短的词
        stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '吗', '呢', '啊', '哦'}
        keywords = [w for w in keywords if w not in stop_words and len(w) >= 2]
        
        return keywords
    
    def _compute_weighted_similarity(self, text1: str, text2: str, keywords1: List[str], keywords2: List[str]) -> float:
        """计算加权相似度"""
        # 简单实现：考虑关键词在文本中的位置
        score = 0.0
        
        for kw in keywords1[:10]:  # 只考虑前10个关键词
            if kw in text2:
                # 关键词在文本中出现，加权
                score += 0.1
        
        return min(1.0, score)
    
    def _get_embedding(self, text: str) -> List[float]:
        """获取文本嵌入"""
        # 检查缓存
        cache_key = hashlib.md5(text.encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 使用嵌入模型
        if self._embedding_model:
            try:
                embedding = self._embedding_model.encode(text)
                self._cache[cache_key] = embedding
                return embedding
            except Exception as e:
                logger.warning("嵌入生成失败: %s", e)
        
        # 降级到关键词嵌入
        return self._text_to_embedding(text)
    
    def _text_to_embedding(self, text: str) -> List[float]:
        """将文本转换为简单嵌入（降级方案）"""
        # 使用字符频率作为简单嵌入
        keywords = self._extract_keywords(text)
        
        # 创建一个简单的256维向量
        embedding = [0.0] * 256
        
        for i, kw in enumerate(keywords[:256]):
            # 使用关键词的哈希值作为向量维度
            hash_val = hash(kw) % 256
            embedding[hash_val] = 1.0
        
        # 归一化：零模长那支原样返回（与 core/vector_math 的口径同一条）
        embedding = vector_math.vectorNormalize(embedding)
        
        return embedding
    
    def build_keyword_index(self, memories: List[Dict[str, Any]], cuesByMemory: Optional[Dict[str, List[str]]] = None):
        """构建关键词索引。

        `cuesByMemory`（TM-2a）：整片 `memory_id → [联想线索文本]`。**全量重建必须带它**——
        不带就是「增量认线索、全量丢线索」的第二条陈旧路径（`upsert_memory_index` 逐条
        维护时线索在，一次 clear+重建就静默没了）。两处重建调用点都由判据
        `test_ruleAssociationCues.py::test_全量重建必须带线索图` 钉住。
        """
        with self._index_lock:
            self._keyword_index.clear()
            
            for mem in memories:
                content = mem.get("content", "")
                memory_id = mem.get("id", "")
                
                texts = [content] + [str(cue) for cue in (cuesByMemory or {}).get(memory_id, []) if cue]
                for text in texts:
                    for kw in self._extract_keywords(text):
                        if kw not in self._keyword_index:
                            self._keyword_index[kw] = []
                        if memory_id not in self._keyword_index[kw]:
                            self._keyword_index[kw].append(memory_id)
            
            logger.info("构建关键词索引: %d 个关键词", len(self._keyword_index))
    
    def upsert_memory_index(self, mem: Dict[str, Any], cues: List[str] = ()) -> None:
        """增量维护单条记忆的关键词倒排（审计 P1-D6）。

        原契约只有 build_keyword_index（clear+全量重建）——manager 每次
        recall 全量重建（O(N)@锁内），neurova_recall 又"只建一次永不更新"，
        两者共享单例互相踩踏：要么索引陈旧要么每查询重建。现提供增量入口，
        记忆增删时逐条 upsert/remove，检索路径零重建。

        `cues`（TM-2a）：联想线索文本。线索词面**并进同一个 memory_id 桶**，
        不另起第二份索引、不改排序口径——它只是让同一条记忆多几个可被查询命中的词。
        抽取必须走同一把 `_extract_keywords` 刀：写侧按一套词切、读侧按另一套词查，
        就是第二条「建了却检索不到」的断链。
        """
        memory_id = mem.get("id", "")
        if not memory_id:
            return
        # 幂等：先摘除旧词条再插新（content 变更场景）；整段持锁，
        # remove_memory_index 内部同样取 RLock（可重入）不会自死锁
        with self._index_lock:
            self.remove_memory_index(memory_id)
            texts = [mem.get("content", "")] + [str(cue) for cue in (cues or []) if cue]
            for text in texts:
                for kw in self._extract_keywords(text):
                    bucket = self._keyword_index.setdefault(kw, [])
                    if memory_id not in bucket:
                        bucket.append(memory_id)

    def remove_memory_index(self, memory_id: str) -> None:
        """从倒排索引摘除一条记忆（增量删除）。"""
        if not memory_id:
            return
        with self._index_lock:
            empty_keys = []
            for kw, ids in self._keyword_index.items():
                if memory_id in ids:
                    ids.remove(memory_id)
                    if not ids:
                        empty_keys.append(kw)
            for kw in empty_keys:
                del self._keyword_index[kw]

    def search_by_keywords(self, query: str, limit: int = 10) -> List[str]:
        """基于关键词索引搜索"""
        keywords = self._extract_keywords(query)
        
        # 统计每个记忆的匹配关键词数
        memory_scores: Dict[str, int] = {}
        
        with self._index_lock:
            for kw in keywords:
                if kw in self._keyword_index:
                    for memory_id in self._keyword_index[kw]:
                        memory_scores[memory_id] = memory_scores.get(memory_id, 0) + 1
        
        # 按匹配数排序
        sorted_memories = sorted(memory_scores.items(), key=lambda x: x[1], reverse=True)
        
        return [memory_id for memory_id, _ in sorted_memories[:limit]]


# 全局实例
_semantic_search: Optional[SemanticSearch] = None
_semantic_search_lock = threading.Lock()


def get_semantic_search(embedding_model=None, use_embedding: bool = True) -> SemanticSearch:
    """获取语义搜索实例（单例）

    Bug 12 修复：首次创建时若 embedding_model 为 None，尝试从全局 embedding 工厂懒加载；
    后续调用忽略参数（保持单例稳定）。如需重置，调用 _reset_semantic_search()。

    Args:
        embedding_model: 嵌入模型（可选，None 时尝试从全局工厂加载）
        use_embedding: 是否使用嵌入模型

    Returns:
        SemanticSearch 实例
    """
    global _semantic_search
    if _semantic_search is None:
        # P3-e：DCL——构造含 ONNX 引擎懒加载（重副作用），并发首访不可双创建
        with _semantic_search_lock:
            if _semantic_search is None:
                # 若调用方未提供 embedding_model，尝试从全局工厂懒加载
                if embedding_model is None and use_embedding:
                    try:
                        from neurova.embedding import get_embedding_engine

                        embedding_model = get_embedding_engine()
                    except Exception as e:
                        logger.warning("全局 embedding 引擎不可用，降级为关键词模式: %s", e)
                        embedding_model = None
                _semantic_search = SemanticSearch(
                    embedding_model=embedding_model,
                    use_embedding=use_embedding,
                )
    return _semantic_search


def _reset_semantic_search():
    """测试用：重置单例

    生产代码不应调用此函数。
    """
    global _semantic_search
    with _semantic_search_lock:
        _semantic_search = None


def reset_semantic_search():
    """公有重置入口（P3-e）：与 _reset_semantic_search 等价，供测试隔离与运维重建。"""
    _reset_semantic_search()
