"""
ToolCache v1.0.0 — 三级智能工具缓存

Phase 2 P2-2: 减少重复工具调用的延迟和资源消耗。

三级缓存架构:
  L1 - 精确匹配: 参数哈希 → O(1) 查找，适用于幂等调用
  L2 - 语义相似: Embedding 相似度 → 复用语义接近的调用结果
  L3 - 预测预加载: 基于能力图预测 → 提前加载高频搭档工具的结果

与现有模块集成:
- ToolOrchestrator: 在执行前检查缓存
- ToolRouter: 在路由时检查缓存
- ToolCapabilityGraph: 用于预测预加载
"""

import hashlib
import json
import logging
import time
import typing
from collections import OrderedDict
from dataclasses import dataclass, field

# tool_layers imports
from neurova.tool_layers.capability_graph import ToolCapabilityGraph

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""

    tool_name: str
    params: typing.Dict[str, typing.Any]
    result: typing.Dict[str, typing.Any]
    timestamp: float = field(default_factory=time.time)
    ttl: float = 300.0  # 默认5分钟
    hit_count: int = 0
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > self.ttl

    def hit(self) -> None:
        """记录命中"""
        self.hit_count += 1

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "params": self.params,
            "result": self.result,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "hit_count": self.hit_count,
            "metadata": self.metadata,
        }


class ToolCache:
    """
    三级智能工具缓存

    功能：
    1. L1 精确匹配缓存（基于参数哈希）
    2. L2 语义相似缓存（基于参数相似度）
    3. L3 预测预加载（基于能力图预测）
    4. 缓存淘汰策略
    5. 缓存统计
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0, similarity_threshold: float = 0.8):
        """
        初始化缓存

        参数:
            max_size: 最大缓存条目数
            default_ttl: 默认过期时间（秒）
            similarity_threshold: L2 语义相似度阈值
        """
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._similarity_threshold = similarity_threshold

        # L1 精确匹配缓存 (key -> CacheEntry)
        self._l1_cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # L2 语义相似缓存 (tool_name -> list of (params_hash, CacheEntry))
        self._l2_cache: typing.Dict[str, typing.List[typing.Tuple[str, CacheEntry]]] = {}

        # L3 预测预加载缓存 (tool_name -> list of CacheEntry)
        self._l3_cache: typing.Dict[str, typing.List[CacheEntry]] = {}

        # 能力图（用于预测）
        self._capability_graph = ToolCapabilityGraph()

        # 统计信息
        self._stats = {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "misses": 0, "sets": 0, "evictions": 0}

    def get(
        self, tool_name: str, params: typing.Dict[str, typing.Any]
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """
        获取缓存结果

        参数:
            tool_name: 工具名称
            params: 工具参数

        返回:
            缓存的结果，如果不存在则返回 None
        """
        # 生成缓存键
        key = self._make_key(tool_name, params)

        # L1 精确匹配
        if key in self._l1_cache:
            entry = self._l1_cache[key]
            if not entry.is_expired():
                entry.hit()
                self._stats["l1_hits"] += 1

                # 移动到末尾（LRU）
                self._l1_cache.move_to_end(key)

                logger.debug("L1 cache hit for %s", tool_name)
                return entry.result
            else:
                # 过期，删除
                del self._l1_cache[key]

        # L2 语义相似匹配
        l2_result = self._search_l2(tool_name, params)
        if l2_result is not None:
            self._stats["l2_hits"] += 1
            logger.debug("L2 cache hit for %s", tool_name)
            return l2_result

        # L3 预测预加载匹配
        if tool_name in self._l3_cache:
            for entry in self._l3_cache[tool_name]:
                if not entry.is_expired():
                    # 检查参数是否匹配
                    if self._calculate_param_similarity(params, entry.params) > self._similarity_threshold:
                        entry.hit()
                        self._stats["l3_hits"] += 1
                        logger.debug("L3 cache hit for %s", tool_name)
                        return entry.result

        # 缓存未命中
        self._stats["misses"] += 1
        return None

    def set(
        self,
        tool_name: str,
        params: typing.Dict[str, typing.Any],
        result: typing.Dict[str, typing.Any],
        ttl: typing.Optional[float] = None,
    ) -> None:
        """
        设置缓存

        参数:
            tool_name: 工具名称
            params: 工具参数
            result: 工具结果
            ttl: 过期时间（秒）
        """
        # 生成缓存键
        key = self._make_key(tool_name, params)

        # 创建缓存条目
        entry = CacheEntry(
            tool_name=tool_name, params=params, result=result, timestamp=time.time(), ttl=ttl or self._default_ttl
        )

        # 检查是否需要淘汰
        if len(self._l1_cache) >= self._max_size:
            self._evict_l1()

        # 添加到 L1 缓存
        self._l1_cache[key] = entry

        # 添加到 L2 缓存
        if tool_name not in self._l2_cache:
            self._l2_cache[tool_name] = []
        self._l2_cache[tool_name].append((key, entry))

        # 更新统计
        self._stats["sets"] += 1

        logger.debug("Cached result for %s", tool_name)

    def preload(
        self,
        tool_name: str,
        params_list: typing.List[typing.Dict[str, typing.Any]],
        results: typing.List[typing.Dict[str, typing.Any]],
    ) -> None:
        """
        预加载缓存

        参数:
            tool_name: 工具名称
            params_list: 参数列表
            results: 结果列表
        """
        if len(params_list) != len(results):
            raise ValueError("params_list and results must have the same length")

        for params, result in zip(params_list, results):
            self.set(tool_name, params, result)

    def predict(
        self, tool_name: str, params: typing.Dict[str, typing.Any]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        预测可能的后续工具调用

        参数:
            tool_name: 当前工具名称
            params: 当前参数

        返回:
            预测的结果列表
        """
        predictions = []

        # 从能力图获取协作工具
        companions = self._capability_graph.suggest_companion_tools(tool_name)

        for companion in companions:
            # 检查协作工具是否有缓存
            if companion in self._l2_cache:
                for _, entry in self._l2_cache[companion]:
                    if not entry.is_expired():
                        predictions.append(entry.result)

        # 预加载到 L3 缓存
        if predictions:
            if tool_name not in self._l3_cache:
                self._l3_cache[tool_name] = []

            # 添加预测结果到 L3 缓存
            for i, prediction in enumerate(predictions[:3]):  # 最多预加载3个
                entry = CacheEntry(
                    tool_name=f"{tool_name}_predicted_{i}",
                    params=params,
                    result=prediction,
                    timestamp=time.time(),
                    ttl=self._default_ttl * 2,  # 预测缓存 TTL 更长
                )
                self._l3_cache[tool_name].append(entry)

        return predictions

    def invalidate(self, tool_name: str, params: typing.Optional[typing.Dict[str, typing.Any]] = None) -> None:
        """
        使缓存失效

        参数:
            tool_name: 工具名称
            params: 工具参数（如果为 None，使所有该工具的缓存失效）
        """
        if params is not None:
            # 使特定缓存失效
            key = self._make_key(tool_name, params)
            if key in self._l1_cache:
                del self._l1_cache[key]

            # 从 L2 缓存中移除
            if tool_name in self._l2_cache:
                self._l2_cache[tool_name] = [(k, e) for k, e in self._l2_cache[tool_name] if k != key]
        else:
            # 使所有该工具的缓存失效
            keys_to_remove = []
            for key, entry in self._l1_cache.items():
                if entry.tool_name == tool_name:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._l1_cache[key]

            # 清空 L2 缓存
            if tool_name in self._l2_cache:
                del self._l2_cache[tool_name]

            # 清空 L3 缓存
            if tool_name in self._l3_cache:
                del self._l3_cache[tool_name]

    def clear(self) -> None:
        """清空所有缓存"""
        self._l1_cache.clear()
        self._l2_cache.clear()
        self._l3_cache.clear()
        logger.info("Cache cleared")

    def get_stats(self) -> typing.Dict[str, typing.Any]:
        """获取缓存统计信息"""
        return {
            "l1_size": len(self._l1_cache),
            "l2_size": sum(len(entries) for entries in self._l2_cache.values()),
            "l3_size": sum(len(entries) for entries in self._l3_cache.values()),
            "max_size": self._max_size,
            "hit_count": self._stats["l1_hits"] + self._stats["l2_hits"] + self._stats["l3_hits"],
            "miss_count": self._stats["misses"],
            "set_count": self._stats["sets"],
            "eviction_count": self._stats["evictions"],
            "hit_rate": (
                (self._stats["l1_hits"] + self._stats["l2_hits"] + self._stats["l3_hits"])
                / max(
                    1, self._stats["l1_hits"] + self._stats["l2_hits"] + self._stats["l3_hits"] + self._stats["misses"]
                )
            ),
        }

    def _make_key(self, tool_name: str, params: typing.Dict[str, typing.Any]) -> str:
        """
        生成缓存键

        参数:
            tool_name: 工具名称
            params: 工具参数

        返回:
            缓存键字符串
        """
        # 将参数转换为稳定的 JSON 字符串
        param_str = json.dumps(params, sort_keys=True, default=str)

        # 生成哈希
        hash_obj = hashlib.md5(f"{tool_name}:{param_str}".encode())
        return hash_obj.hexdigest()

    def _calculate_param_similarity(
        self, params1: typing.Dict[str, typing.Any], params2: typing.Dict[str, typing.Any]
    ) -> float:
        """
        计算参数相似度

        参数:
            params1: 参数1
            params2: 参数2

        返回:
            相似度分数 (0-1)
        """
        if params1 == params2:
            return 1.0

        # 获取所有键
        all_keys = set(params1.keys()) | set(params2.keys())
        if not all_keys:
            return 1.0

        # 计算匹配的键值对数量
        matches = 0
        for key in all_keys:
            if key in params1 and key in params2:
                if params1[key] == params2[key]:
                    matches += 1

        # 计算相似度
        similarity = matches / len(all_keys)
        return similarity

    def _search_l2(
        self, tool_name: str, params: typing.Dict[str, typing.Any]
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """
        L2 语义相似搜索

        参数:
            tool_name: 工具名称
            params: 工具参数

        返回:
            最相似的结果，如果不存在则返回 None
        """
        if tool_name not in self._l2_cache:
            return None

        best_match = None
        best_similarity = 0.0

        for _, entry in self._l2_cache[tool_name]:
            if entry.is_expired():
                continue

            # 计算参数相似度
            similarity = self._calculate_param_similarity(params, entry.params)

            # 如果相似度超过阈值，且比之前找到的更相似
            if similarity >= self._similarity_threshold and similarity > best_similarity:
                best_similarity = similarity
                best_match = entry

        if best_match:
            best_match.hit()
            return best_match.result

        return None

    def _evict_l1(self) -> None:
        """
        L1 缓存淘汰（LRU 策略）
        """
        if not self._l1_cache:
            return

        # 淘汰最久未使用的条目
        self._l1_cache.popitem(last=False)
        self._stats["evictions"] += 1

        logger.debug("Evicted L1 cache entry")

    def _calculate_l1_key_similarity(self, key1: str, key2: str) -> float:
        """
        计算 L1 键相似度（用于调试）

        参数:
            key1: 键1
            key2: 键2

        返回:
            相似度分数 (0-1)
        """
        # 简单的字符串相似度
        if key1 == key2:
            return 1.0

        # 计算共同前缀长度
        common_prefix = 0
        for c1, c2 in zip(key1, key2):
            if c1 == c2:
                common_prefix += 1
            else:
                break

        # 计算相似度
        similarity = common_prefix / max(len(key1), len(key2))
        return similarity

    def _record_l2_vector(self, tool_name: str, params: typing.Dict[str, typing.Any], entry: CacheEntry) -> None:
        """
        记录 L2 向量（用于语义搜索）

        参数:
            tool_name: 工具名称
            params: 工具参数
            entry: 缓存条目
        """
        # 这里可以集成向量数据库进行语义搜索
        # 目前使用简单的参数相似度
