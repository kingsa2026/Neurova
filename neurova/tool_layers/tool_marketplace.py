"""
ToolMarketplace v1.0.0 — 工具市场 (Phase 3 P3-2)

职责:
- 贝叶斯平均评分（防止少量评分偏差）
- 工具 Fork 机制（派生/修改/追踪）
- 搜索发现（名称/分类/作者/能力）
- 发布/下架管理

架构:
    MarketplaceTool ──▶ 评分聚合 ──▶ BayesianRating
"""

from neurova.core.logger import get_logger
import math
import time
import typing
from dataclasses import dataclass, field

logger = get_logger(__name__)


class BayesianRating:
    """
    贝叶斯平均评分

    使用贝叶斯平均来防止少量评分导致的偏差。
    公式：BayesianAvg = (C * m + sum(ratings)) / (C + n)
    其中：
    - C: 先验权重（默认10）
    - m: 先验平均分（默认3.0）
    - n: 实际评分数量
    """

    def __init__(self, c: int = 10, m: float = 3.0):
        """
        初始化贝叶斯评分

        参数:
            c: 先验权重（越大，先验影响越大）
            m: 先验平均分
        """
        self.c = c
        self.m = m

    def compute(self, ratings: typing.List[float]) -> float:
        """
        计算贝叶斯平均分

        参数:
            ratings: 评分列表

        返回:
            贝叶斯平均分
        """
        if not ratings:
            return self.m

        n = len(ratings)
        total = sum(ratings)

        # 贝叶斯平均公式
        bayesian_avg = (self.c * self.m + total) / (self.c + n)

        # 限制在 0-5 范围内
        return max(0.0, min(5.0, bayesian_avg))

    def confidence_interval(self, ratings: typing.List[float], confidence: float = 0.95) -> typing.Tuple[float, float]:
        """
        计算置信区间

        参数:
            ratings: 评分列表
            confidence: 置信水平（默认95%）

        返回:
            (下限, 上限) 元组
        """
        if not ratings:
            # 无评分时，返回很宽的区间
            return (0.0, 5.0)

        n = len(ratings)
        mean = sum(ratings) / n

        if n < 2:
            # 样本太少，返回基于先验的区间
            return (max(0.0, self.m - 1.0), min(5.0, self.m + 1.0))

        # 计算标准差
        variance = sum((x - mean) ** 2 for x in ratings) / (n - 1)
        std_dev = math.sqrt(variance)

        # 标准误差
        std_error = std_dev / math.sqrt(n)

        # 使用正态分布近似（对于大样本）
        # 95% 置信水平的 z 值约为 1.96
        z = 1.96 if confidence == 0.95 else 2.576 if confidence == 0.99 else 1.645

        margin_of_error = z * std_error

        lower = max(0.0, mean - margin_of_error)
        upper = min(5.0, mean + margin_of_error)

        return (lower, upper)


@dataclass
class ToolReview:
    """工具评论"""

    user_id: str
    rating: float
    comment: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolFork:
    """工具 Fork 记录"""

    original_tool: str
    forked_tool: str
    user_id: str
    changes: typing.Dict[str, typing.Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MarketplaceTool:
    """市场工具"""

    tool_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    categories: typing.List[str] = field(default_factory=list)
    tags: typing.List[str] = field(default_factory=list)
    downloads: int = 0
    rating: typing.Optional[BayesianRating] = None
    reviews: typing.List[ToolReview] = field(default_factory=list)
    forks: typing.List[ToolFork] = field(default_factory=list)
    featured: bool = False
    deprecated: bool = False
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def add_review(self, review: ToolReview) -> None:
        """添加评论"""
        self.reviews.append(review)
        self._recompute_rating()

    def _recompute_rating(self) -> None:
        """重新计算评分"""
        if not self.reviews:
            self.rating = None
            return

        # 创建贝叶斯评分计算器
        self.rating = BayesianRating(c=10, m=3.0)

        # 提取所有评分
        ratings = [review.rating for review in self.reviews]

        # 计算贝叶斯平均分
        self.rating.compute(ratings)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        data = {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "categories": self.categories,
            "tags": self.tags,
            "downloads": self.downloads,
            "featured": self.featured,
            "deprecated": self.deprecated,
            "metadata": self.metadata,
            "review_count": len(self.reviews),
            "fork_count": len(self.forks),
        }

        # 添加评分信息
        if self.rating:
            ratings = [r.rating for r in self.reviews]
            data["rating"] = {
                "bayesian_average": self.rating.compute(ratings),
                "count": len(ratings),
                "average": sum(ratings) / len(ratings) if ratings else 0,
            }

        return data

    def to_published_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为发布字典（包含评分详情）

        发布契约: rating 字段恒存在（无评论时为 None），保证市场卡片
        渲染端不需要判空缺键。
        """
        data = self.to_dict()
        if "rating" not in data:
            data["rating"] = None

        # 添加评分详情
        if self.rating and self.reviews:
            ratings = [r.rating for r in self.reviews]
            data["rating_details"] = {
                "bayesian_average": self.rating.compute(ratings),
                "raw_average": sum(ratings) / len(ratings),
                "count": len(ratings),
                "distribution": self._get_rating_distribution(),
            }

        return data

    def _get_rating_distribution(self) -> typing.Dict[int, int]:
        """获取评分分布"""
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for review in self.reviews:
            rating_int = int(review.rating)
            if 1 <= rating_int <= 5:
                distribution[rating_int] += 1
        return distribution

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "MarketplaceTool":
        """从字典创建工具"""
        tool = cls(
            tool_id=data["tool_id"],
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            categories=data.get("categories", []),
            tags=data.get("tags", []),
            downloads=data.get("downloads", 0),
            featured=data.get("featured", False),
            deprecated=data.get("deprecated", False),
            metadata=data.get("metadata", {}),
        )

        # 重建评分
        if "rating" in data and data["rating"]:
            tool.rating = BayesianRating()

        return tool


class ToolMarketplace:
    """
    工具市场

    功能：
    1. 工具注册和管理
    2. 评分和评论
    3. 搜索和发现
    4. Fork 机制
    5. 分类和标签
    """

    def __init__(self):
        """初始化工具市场"""
        self._tools: typing.Dict[str, MarketplaceTool] = {}
        self._name_index: typing.Dict[str, str] = {}  # name -> tool_id

    def add_tool(self, tool: MarketplaceTool) -> None:
        """添加工具"""
        self._tools[tool.tool_id] = tool
        self._name_index[tool.name] = tool.tool_id

    def get_tool(self, tool_id: str) -> typing.Optional[MarketplaceTool]:
        """获取工具"""
        return self._tools.get(tool_id)

    def get_tool_by_name(self, name: str) -> typing.Optional[MarketplaceTool]:
        """按名称获取工具"""
        tool_id = self._name_index.get(name)
        if tool_id:
            return self._tools.get(tool_id)
        return None

    def deprecate(self, tool_id: str) -> None:
        """弃用工具"""
        tool = self._tools.get(tool_id)
        if tool:
            tool.deprecated = True

    def search(self, query: str) -> typing.List[MarketplaceTool]:
        """
        搜索工具

        参数:
            query: 搜索查询（匹配名称、描述、标签）

        返回:
            匹配的工具列表
        """
        query_lower = query.lower()
        results = []

        for tool in self._tools.values():
            # 跳过已弃用的工具
            if tool.deprecated:
                continue

            # 检查名称
            if query_lower in tool.name.lower():
                results.append(tool)
                continue

            # 检查描述
            if query_lower in tool.description.lower():
                results.append(tool)
                continue

            # 检查标签
            if any(query_lower in tag.lower() for tag in tool.tags):
                results.append(tool)
                continue

            # 检查分类
            if any(query_lower in cat.lower() for cat in tool.categories):
                results.append(tool)
                continue

        return results

    def get_top_rated(self, limit: int = 10) -> typing.List[MarketplaceTool]:
        """获取评分最高的工具"""
        # 过滤有评分的工具
        rated_tools = [tool for tool in self._tools.values() if tool.rating and not tool.deprecated]

        # 按贝叶斯平均分排序
        def get_rating(tool: MarketplaceTool) -> float:
            if not tool.rating:
                return 0.0
            ratings = [r.rating for r in tool.reviews]
            return tool.rating.compute(ratings)

        rated_tools.sort(key=get_rating, reverse=True)
        return rated_tools[:limit]

    def get_most_downloaded(self, limit: int = 10) -> typing.List[MarketplaceTool]:
        """获取下载量最高的工具"""
        # 过滤未弃用的工具
        active_tools = [tool for tool in self._tools.values() if not tool.deprecated]

        # 按下载量排序
        active_tools.sort(key=lambda t: t.downloads, reverse=True)
        return active_tools[:limit]

    def get_featured(self) -> typing.List[MarketplaceTool]:
        """获取精选工具"""
        return [tool for tool in self._tools.values() if tool.featured and not tool.deprecated]

    def mark_featured(self, tool_id: str, featured: bool = True) -> None:
        """标记精选"""
        tool = self._tools.get(tool_id)
        if tool:
            tool.featured = featured

    def rate(self, tool_id: str, user_id: str, rating: float, comment: str = "") -> None:
        """
        评分工具

        参数:
            tool_id: 工具 ID
            user_id: 用户 ID
            rating: 评分 (1-5)
            comment: 评论
        """
        tool = self._tools.get(tool_id)
        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        # 验证评分范围
        if not (1 <= rating <= 5):
            raise ValueError("Rating must be between 1 and 5")

        # 创建评论
        review = ToolReview(user_id=user_id, rating=rating, comment=comment, timestamp=time.time())

        # 添加评论
        tool.add_review(review)

    def record_download(self, tool_id: str) -> None:
        """记录下载"""
        tool = self._tools.get(tool_id)
        if tool:
            tool.downloads += 1

    def fork_tool(
        self,
        original_tool_id: str,
        new_tool_id: str,
        new_name: str,
        user_id: str,
        changes: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> MarketplaceTool:
        """
        Fork 工具

        参数:
            original_tool_id: 原始工具 ID
            new_tool_id: 新工具 ID
            new_name: 新工具名称
            user_id: Fork 用户 ID
            changes: 修改内容

        返回:
            新创建的工具
        """
        original = self._tools.get(original_tool_id)
        if not original:
            raise ValueError(f"Original tool {original_tool_id} not found")

        # 创建新工具
        forked_tool = MarketplaceTool(
            tool_id=new_tool_id,
            name=new_name,
            description=original.description,
            version="1.0.0",  # Fork 的版本重置
            author=user_id,  # Fork 的作者是 fork 用户
            categories=original.categories.copy(),
            tags=original.tags.copy(),
            metadata=original.metadata.copy(),
        )

        # 应用修改
        if changes:
            for key, value in changes.items():
                if hasattr(forked_tool, key):
                    setattr(forked_tool, key, value)

        # 添加到市场
        self.add_tool(forked_tool)

        # 记录 fork
        fork_record = ToolFork(
            original_tool=original_tool_id,
            forked_tool=new_tool_id,
            user_id=user_id,
            changes=changes or {},
            timestamp=time.time(),
        )
        original.forks.append(fork_record)

        return forked_tool

    def get_fork_history(self, tool_id: str) -> typing.List[ToolFork]:
        """获取工具的 Fork 历史"""
        tool = self._tools.get(tool_id)
        if not tool:
            return []
        return tool.forks

    def get_categories(self) -> typing.List[str]:
        """获取所有分类"""
        categories = set()
        for tool in self._tools.values():
            categories.update(tool.categories)
        return sorted(list(categories))

    def get_tools_by_category(self, category: str) -> typing.List[MarketplaceTool]:
        """按分类获取工具"""
        return [tool for tool in self._tools.values() if category in tool.categories and not tool.deprecated]

    def list_tools(self) -> typing.List[MarketplaceTool]:
        """列出所有工具"""
        return list(self._tools.values())
