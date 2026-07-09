"""
Muscle Memory - 真正的肌肉记忆系统（条件反射级）

替代原有基于检索的 ToolMemory，实现：
1. L1 肌肉记忆（条件反射级，毫秒级响应）
2. L2 热路径缓存（高频使用，秒级响应）
3. L3 工具记忆（原始记录，需要检索）

匹配规则：关键词指纹 + 向量指纹 混合匹配
固化策略：激进固化（连续成功2次即固化到L1）
遗忘机制：30天未使用自动降级L2→L3
"""

import hashlib
import json
from neurova.core.logger import get_logger
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


class MemoryLevel(Enum):
    """记忆层级"""

    L1 = "l1"  # 条件反射级（毫秒响应）
    L2 = "l2"  # 热路径缓存（秒级响应）
    L3 = "l3"  # 工具记忆（需要检索）


@dataclass
class MuscleMemoryItem:
    """肌肉记忆条目"""

    id: str
    tool_name: str
    query_fingerprint: str  # 查询关键词指纹
    vector_fingerprint: str = ""  # 向量指纹（可选）
    parameters: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    level: MemoryLevel = MemoryLevel.L3
    success_count: int = 0
    failure_count: int = 0
    consecutive_successes: int = 0
    last_used: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "query_fingerprint": self.query_fingerprint,
            "vector_fingerprint": self.vector_fingerprint,
            "parameters": self.parameters,
            "result_summary": self.result_summary,
            "level": self.level.value,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_successes": self.consecutive_successes,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MuscleMemoryItem":
        return cls(
            id=data["id"],
            tool_name=data["tool_name"],
            query_fingerprint=data["query_fingerprint"],
            vector_fingerprint=data.get("vector_fingerprint", ""),
            parameters=data.get("parameters", {}),
            result_summary=data.get("result_summary", ""),
            level=MemoryLevel(data.get("level", "l3")),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            consecutive_successes=data.get("consecutive_successes", 0),
            last_used=data.get("last_used", time.time()),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


# 遗忘阈值（秒）
_FORGET_THRESHOLDS = {
    MemoryLevel.L1: 30 * 86400,  # L1: 30天未使用降级到L2
    MemoryLevel.L2: 30 * 86400,  # L2: 30天未使用降级到L3
    MemoryLevel.L3: 90 * 86400,  # L3: 90天未使用删除
}

# 固化阈值：连续成功次数
_PROMOTE_THRESHOLD = 2


class MuscleMemory:
    """
    肌肉记忆系统

    三层记忆架构，实现条件反射级的工具使用记忆。
    """

    def __init__(self, storage_path: Optional[str] = None, storage_dir: Optional[str] = None, **kwargs):
        """
        初始化肌肉记忆系统

        Args:
            storage_path: 持久化存储路径
            storage_dir: storage_path 的别名（向后兼容）
        """
        self._storage_path = storage_path or storage_dir
        self._lock = threading.RLock()

        # 三层存储
        self._l1: Dict[str, MuscleMemoryItem] = {}
        self._l2: Dict[str, MuscleMemoryItem] = {}
        self._l3: Dict[str, MuscleMemoryItem] = {}

        # 关键词索引: keyword -> set(item_id)
        self._keyword_index: Dict[str, set] = {}

        # 工具名称索引: tool_name -> set(item_id)
        self._tool_index: Dict[str, set] = {}

        # 加载持久化数据
        if self._storage_path:
            self._load_all()

    def match(
        self,
        tool_name: str,
        query: str,
        top_k: int = 3,
    ) -> List[Tuple[MuscleMemoryItem, float]]:
        """
        匹配记忆条目

        Args:
            tool_name: 工具名称
            query: 查询文本
            top_k: 返回数量

        Returns:
            [(item, confidence)] 列表，按置信度降序
        """
        fingerprint = self._extract_keywords(query)
        vector_fp = self._text_to_embedding_hash(query)

        with self._lock:
            results = []

            # L1: 精确匹配（毫秒级）
            l1_matches = self._match_l1(tool_name, fingerprint, vector_fp)
            results.extend(l1_matches)

            # L2: 模糊匹配
            l2_matches = self._match_l2(tool_name, fingerprint, vector_fp)
            results.extend(l2_matches)

            # L3: 广泛检索
            l3_matches = self._match_l3(tool_name, fingerprint, vector_fp)
            results.extend(l3_matches)

            # 去重并按置信度排序
            seen = set()
            unique_results = []
            for item, conf in results:
                if item.id not in seen:
                    seen.add(item.id)
                    unique_results.append((item, conf))

            unique_results.sort(key=lambda x: x[1], reverse=True)
            return unique_results[:top_k]

    def match_by_query(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Tuple[MuscleMemoryItem, float]]:
        """
        按查询文本匹配（不指定工具名，跨工具搜索）

        用于 ToolMemoryIntegration.check_tool_memory() 中的肌肉记忆路径。

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            [(item, confidence)] 列表，按置信度降序
        """
        fingerprint = self._extract_keywords(query)
        vector_fp = self._text_to_embedding_hash(query)

        with self._lock:
            results = []

            # 搜索所有层级（不按工具名过滤）
            for store, min_conf in [
                (self._l1, 0.5),
                (self._l2, 0.3),
                (self._l3, 0.2),
            ]:
                for item_id, item in store.items():
                    conf = self._compute_confidence(item, fingerprint, vector_fp)
                    if conf > min_conf:
                        results.append((item, conf))

            # 去重并按置信度排序
            seen = set()
            unique_results = []
            for item, conf in results:
                if item.id not in seen:
                    seen.add(item.id)
                    unique_results.append((item, conf))

            unique_results.sort(key=lambda x: x[1], reverse=True)
            return unique_results[:top_k]

    def _match_l1(self, tool_name: str, fingerprint: str, vector_fp: str) -> List[Tuple[MuscleMemoryItem, float]]:
        """L1 精确匹配"""
        with self._lock:
            results = []
            for item_id, item in self._l1.items():
                if item.tool_name != tool_name:
                    continue
                conf = self._compute_confidence(item, fingerprint, vector_fp)
                if conf > 0.7:
                    results.append((item, conf))
            return results

    def _match_l2(self, tool_name: str, fingerprint: str, vector_fp: str) -> List[Tuple[MuscleMemoryItem, float]]:
        """L2 模糊匹配"""
        with self._lock:
            results = []
            for item_id, item in self._l2.items():
                if item.tool_name != tool_name:
                    continue
                conf = self._compute_confidence(item, fingerprint, vector_fp)
                if conf > 0.5:
                    results.append((item, conf))
            return results

    def _match_l3(self, tool_name: str, fingerprint: str, vector_fp: str) -> List[Tuple[MuscleMemoryItem, float]]:
        """L3 广泛检索"""
        with self._lock:
            results = []
            tool_items = self._tool_index.get(tool_name, set())
            # 利用 _keyword_index 缩小候选集（关键词命中且与工具索引有交集时优先使用）
            keyword_hits: set = set()
            for kw in fingerprint.split(","):
                if kw:
                    keyword_hits |= self._keyword_index.get(kw, set())
            candidates = (keyword_hits & tool_items) if (keyword_hits & tool_items) else tool_items
            for item_id in candidates:
                item = self._l3.get(item_id)
                if item is None:
                    continue
                conf = self._compute_confidence(item, fingerprint, vector_fp)
                if conf > 0.3:
                    results.append((item, conf))
            return results

    def _compute_confidence(
        self,
        item: MuscleMemoryItem,
        fingerprint: str,
        vector_fp: str,
    ) -> float:
        """计算匹配置信度"""
        # 空指纹不产生虚假匹配
        if not fingerprint and not item.query_fingerprint:
            return 0.0

        score = 0.0

        # 关键词指纹匹配
        if item.query_fingerprint == fingerprint:
            score += 0.6
        else:
            # 部分匹配（过滤空字符串避免 "".split(",") 产生 [""]）
            item_kws = {k for k in item.query_fingerprint.split(",") if k}
            query_kws = {k for k in fingerprint.split(",") if k}
            if not item_kws or not query_kws:
                return 0.0
            overlap = len(item_kws & query_kws)
            total = max(len(item_kws), len(query_kws))
            if total > 0:
                score += 0.4 * (overlap / total)

        # 向量指纹匹配
        if vector_fp and item.vector_fingerprint == vector_fp:
            score += 0.3

        # 成功率加成
        total_uses = item.success_count + item.failure_count
        if total_uses > 0:
            success_rate = item.success_count / total_uses
            score += 0.1 * success_rate

        return min(score, 1.0)

    def record_usage(
        self,
        tool_name: str,
        query: str,
        parameters: Dict[str, Any],
        success: bool,
        result_summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> MuscleMemoryItem:
        """
        记录工具使用

        Args:
            tool_name: 工具名称
            query: 查询文本
            parameters: 工具参数
            success: 是否成功
            result_summary: 结果摘要
            metadata: 额外元数据
            **kwargs: 额外关键字参数，将被合并到 metadata 中

        Returns:
            记忆条目
        """
        # 将额外的关键字参数合并到 metadata 中
        if metadata is None:
            metadata = {}
        metadata.update(kwargs)
        fingerprint = self._extract_keywords(query)
        vector_fp = self._text_to_embedding_hash(query)

        with self._lock:
            # 尝试找到已有的条目
            existing = self._find_item(tool_name, fingerprint, vector_fp)

            if existing:
                return self._update_existing_item(existing, success, result_summary, metadata)

            # 创建新条目
            item_id = self._generate_item_id(tool_name, query)
            item = MuscleMemoryItem(
                id=item_id,
                tool_name=tool_name,
                query_fingerprint=fingerprint,
                vector_fingerprint=vector_fp,
                parameters=parameters,
                result_summary=result_summary,
                level=MemoryLevel.L3,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
                consecutive_successes=1 if success else 0,
                metadata=metadata or {},
            )

            self._l3[item_id] = item
            self._add_to_keyword_index(item)
            self._add_to_tool_index(item)
            self._save_all()

            logger.debug("New muscle memory item: %s... (L3)", item_id[:8])
            return item

    def _update_existing_item(
        self,
        item: MuscleMemoryItem,
        success: bool,
        result_summary: str,
        metadata: Optional[Dict[str, Any]],
    ) -> MuscleMemoryItem:
        """更新已有条目"""
        item.last_used = time.time()

        if success:
            item.success_count += 1
            item.consecutive_successes += 1
            item.result_summary = result_summary
            if metadata:
                item.metadata.update(metadata)

            # 固化检查：连续成功 N 次提升层级
            if item.consecutive_successes >= _PROMOTE_THRESHOLD:
                self._promote_item(item)
        else:
            item.failure_count += 1
            item.consecutive_successes = 0

        self._save_all()
        return item

    def _promote_item(self, item: MuscleMemoryItem) -> None:
        """提升条目层级"""
        if item.level == MemoryLevel.L3:
            # L3 -> L2
            self._l3.pop(item.id, None)
            item.level = MemoryLevel.L2
            self._l2[item.id] = item
            logger.info("Promoted %s... L3 -> L2", item.id[:8])
        elif item.level == MemoryLevel.L2:
            # L2 -> L1
            self._l2.pop(item.id, None)
            item.level = MemoryLevel.L1
            self._l1[item.id] = item
            logger.info("Promoted %s... L2 -> L1", item.id[:8])

    def check_forgotten(self) -> int:
        """
        检查并处理遗忘

        Returns:
            被遗忘/降级的条目数
        """
        now = time.time()
        demoted = 0

        with self._lock:
            # 注意：扫描顺序必须是 L3 → L2 → L1（从低到高），
            # 这样高层的降级不会在同一轮被低层再次扫描，避免级联降级。
            # 例如：L1→L2 降级后，L2 扫描已完成，不会立即再 L2→L3。

            # L3 删除
            to_delete = []
            for item_id, item in self._l3.items():
                if now - item.last_used > _FORGET_THRESHOLDS[MemoryLevel.L3]:
                    to_delete.append(item_id)

            for item_id in to_delete:
                item = self._l3.pop(item_id)
                self._remove_from_keyword_index(item)
                self._remove_from_tool_index(item)
                demoted += 1

            # L2 降级到 L3
            to_demote_l2 = []
            for item_id, item in self._l2.items():
                if now - item.last_used > _FORGET_THRESHOLDS[MemoryLevel.L2]:
                    to_demote_l2.append(item_id)

            for item_id in to_demote_l2:
                item = self._l2.pop(item_id)
                self._demote_item(item)
                demoted += 1

            # L1 降级到 L2（最后扫描，降级到 L2 后不会被本轮 L2 扫描再次降级）
            to_demote_l1 = []
            for item_id, item in self._l1.items():
                if now - item.last_used > _FORGET_THRESHOLDS[MemoryLevel.L1]:
                    to_demote_l1.append(item_id)

            for item_id in to_demote_l1:
                item = self._l1.pop(item_id)
                self._demote_item(item)
                demoted += 1

        if demoted > 0:
            logger.info("Forgot %s muscle memory items", demoted)
            self._save_all()

        return demoted

    def _demote_item(self, item: MuscleMemoryItem) -> None:
        """降级条目"""
        if item.level == MemoryLevel.L1:
            item.level = MemoryLevel.L2
            self._l2[item.id] = item
            logger.debug("Demoted %s... L1 -> L2", item.id[:8])
        elif item.level == MemoryLevel.L2:
            item.level = MemoryLevel.L3
            self._l3[item.id] = item
            logger.debug("Demoted %s... L2 -> L3", item.id[:8])

    def create_from_skill(
        self,
        skill_name: str,
        tool_name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> MuscleMemoryItem:
        """从技能创建记忆条目"""
        item_id = self._generate_item_id(tool_name, description)
        fingerprint = self._extract_keywords(description)

        item = MuscleMemoryItem(
            id=item_id,
            tool_name=tool_name,
            query_fingerprint=fingerprint,
            parameters=parameters,
            result_summary=f"Skill: {skill_name}",
            level=MemoryLevel.L2,
            metadata={"source": "skill", "skill_name": skill_name},
        )

        with self._lock:
            self._l2[item_id] = item
            self._add_to_keyword_index(item)
            self._add_to_tool_index(item)

        return item

    def _extract_keywords(self, text: str) -> str:
        """提取关键词指纹"""
        # 移除标点和特殊字符，分词
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        words = cleaned.split()
        # 移除停用词
        stopwords = {"的", "了", "是", "在", "有", "和", "与", "the", "a", "an", "is", "are", "to"}
        keywords = sorted(set(w for w in words if w not in stopwords and len(w) > 1))
        return ",".join(keywords[:20])

    def _text_to_embedding_hash(self, text: str) -> str:
        """生成文本的哈希指纹"""
        return hashlib.md5(text.lower().strip().encode()).hexdigest()[:16]

    def _generate_item_id(self, tool_name: str, query: str) -> str:
        """生成条目 ID"""
        # 加入 uuid4 防止同一秒内高频记录产生 ID 碰撞
        raw = f"{tool_name}:{query}:{time.time()}:{uuid.uuid4().hex}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _find_item(self, tool_name: str, fingerprint: str, vector_fp: str) -> Optional[MuscleMemoryItem]:
        """查找已有条目"""
        # 先从工具索引查找
        tool_items = self._tool_index.get(tool_name, set())
        for item_id in tool_items:
            for store in (self._l1, self._l2, self._l3):
                item = store.get(item_id)
                if item and item.query_fingerprint == fingerprint:
                    # 联合判定 vector_fp：若双方都非空则必须相等，避免不同向量指纹的记录被错误合并
                    if vector_fp and item.vector_fingerprint and item.vector_fingerprint != vector_fp:
                        continue
                    return item
        return None

    def _add_to_keyword_index(self, item: MuscleMemoryItem) -> None:
        """添加到关键词索引"""
        for keyword in item.query_fingerprint.split(","):
            if keyword:
                if keyword not in self._keyword_index:
                    self._keyword_index[keyword] = set()
                self._keyword_index[keyword].add(item.id)

    def _remove_from_keyword_index(self, item: MuscleMemoryItem) -> None:
        """从关键词索引移除"""
        for keyword in item.query_fingerprint.split(","):
            if keyword in self._keyword_index:
                self._keyword_index[keyword].discard(item.id)
                if not self._keyword_index[keyword]:
                    del self._keyword_index[keyword]

    def _add_to_tool_index(self, item: MuscleMemoryItem) -> None:
        """添加到工具索引"""
        if item.tool_name not in self._tool_index:
            self._tool_index[item.tool_name] = set()
        self._tool_index[item.tool_name].add(item.id)

    def _remove_from_tool_index(self, item: MuscleMemoryItem) -> None:
        """从工具索引移除"""
        if item.tool_name in self._tool_index:
            self._tool_index[item.tool_name].discard(item.id)

    def _save_all(self) -> None:
        """保存所有层级"""
        if not self._storage_path:
            return
        self._save_level(self._l1, "l1")
        self._save_level(self._l2, "l2")
        self._save_level(self._l3, "l3")

    def _save_level(self, store: Dict[str, MuscleMemoryItem], level_name: str) -> None:
        """保存单个层级"""
        if not self._storage_path:
            return
        try:
            path = Path(self._storage_path) / f"muscle_{level_name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [item.to_dict() for item in store.values()]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to save %s: %s", level_name, e)

    def _load_all(self) -> None:
        """加载所有层级"""
        if not self._storage_path:
            return
        self._l1 = self._load_level("l1")
        self._l2 = self._load_level("l2")
        self._l3 = self._load_level("l3")

        # 重建索引
        for store in (self._l1, self._l2, self._l3):
            for item in store.values():
                self._add_to_keyword_index(item)
                self._add_to_tool_index(item)

        total = len(self._l1) + len(self._l2) + len(self._l3)
        logger.info("Loaded %s muscle memory items", total)

    def _load_level(self, level_name: str) -> Dict[str, MuscleMemoryItem]:
        """加载单个层级"""
        if not self._storage_path:
            return {}
        try:
            path = Path(self._storage_path) / f"muscle_{level_name}.json"
            if not path.exists():
                return {}
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {item["id"]: MuscleMemoryItem.from_dict(item) for item in data}
        except Exception as e:
            logger.warning("Failed to load %s: %s", level_name, e)
            return {}

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "l1_count": len(self._l1),
            "l2_count": len(self._l2),
            "l3_count": len(self._l3),
            "total": len(self._l1) + len(self._l2) + len(self._l3),
            "keyword_index_size": len(self._keyword_index),
            "tool_index_size": len(self._tool_index),
        }
