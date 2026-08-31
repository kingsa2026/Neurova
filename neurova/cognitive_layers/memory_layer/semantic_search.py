"""
语义搜索工具

提供基于嵌入模型的语义相似度计算，支持：
- 文本嵌入生成
- 余弦相似度计算
- 批量相似度计算
- 缓存优化
"""

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
            return self._cosine_similarity(emb1, emb2)
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
        
        # 归一化
        norm = sum(x * x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]
        
        return embedding
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def build_keyword_index(self, memories: List[Dict[str, Any]]):
        """构建关键词索引"""
        self._keyword_index.clear()
        
        for mem in memories:
            content = mem.get("content", "")
            memory_id = mem.get("id", "")
            
            keywords = self._extract_keywords(content)
            for kw in keywords:
                if kw not in self._keyword_index:
                    self._keyword_index[kw] = []
                self._keyword_index[kw].append(memory_id)
        
        logger.info("构建关键词索引: %d 个关键词", len(self._keyword_index))
    
    def search_by_keywords(self, query: str, limit: int = 10) -> List[str]:
        """基于关键词索引搜索"""
        keywords = self._extract_keywords(query)
        
        # 统计每个记忆的匹配关键词数
        memory_scores: Dict[str, int] = {}
        
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
