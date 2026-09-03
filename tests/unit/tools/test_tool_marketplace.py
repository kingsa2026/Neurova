"""
ToolMarketplace 单元测试

测试目标：
1. BayesianRating 类
2. ToolReview 数据类
3. ToolFork 数据类
4. MarketplaceTool 类
5. ToolMarketplace 类
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import math

# 导入被测模块
from neurova.tool_layers.tool_marketplace import (
    BayesianRating, ToolReview, ToolFork, MarketplaceTool, ToolMarketplace
)


class TestBayesianRating:
    """BayesianRating 类测试"""

    def test_initialization(self):
        """测试初始化"""
        rating = BayesianRating()
        assert rating.c == 10  # 默认先验权重
        assert rating.m == 3.0  # 默认先验平均分

    def test_compute_no_ratings(self):
        """测试无评分时的计算"""
        rating = BayesianRating()
        score = rating.compute([])
        # 无评分时返回先验平均分
        assert score == rating.m

    def test_compute_with_ratings(self):
        """测试有评分时的计算"""
        rating = BayesianRating(c=10, m=3.0)
        ratings = [5, 4, 5, 4, 5]
        score = rating.compute(ratings)
        
        # 贝叶斯平均公式
        expected = (rating.c * rating.m + sum(ratings)) / (rating.c + len(ratings))
        assert abs(score - expected) < 0.001

    def test_compute_single_rating(self):
        """测试单个评分"""
        rating = BayesianRating(c=5, m=3.0)
        score = rating.compute([5])
        expected = (5 * 3.0 + 5) / (5 + 1)
        assert abs(score - expected) < 0.001

    def test_confidence_interval(self):
        """测试置信区间"""
        rating = BayesianRating(c=10, m=3.0)
        ratings = [5, 4, 5, 4, 5]
        lower, upper = rating.confidence_interval(ratings, confidence=0.95)
        
        # 置信区间应该包含真实均值
        assert lower <= upper
        assert lower >= 0
        assert upper <= 5

    def test_confidence_interval_no_ratings(self):
        """测试无评分时的置信区间"""
        rating = BayesianRating()
        lower, upper = rating.confidence_interval([])
        # 无评分时，置信区间应该很宽
        assert lower < rating.m < upper


class TestToolReview:
    """ToolReview 数据类测试"""

    def test_creation(self):
        """测试创建"""
        review = ToolReview(
            user_id="user1",
            rating=4.5,
            comment="Great tool!",
            timestamp=1234567890.0
        )
        assert review.user_id == "user1"
        assert review.rating == 4.5
        assert review.comment == "Great tool!"
        assert review.timestamp == 1234567890.0

    def test_defaults(self):
        """测试默认值"""
        review = ToolReview(user_id="user1", rating=4.0)
        assert review.comment == ""
        assert isinstance(review.timestamp, float)


class TestToolFork:
    """ToolFork 数据类测试"""

    def test_creation(self):
        """测试创建"""
        fork = ToolFork(
            original_tool="original",
            forked_tool="forked",
            user_id="user1",
            changes={"description": "Modified version"},
            timestamp=1234567890.0
        )
        assert fork.original_tool == "original"
        assert fork.forked_tool == "forked"
        assert fork.user_id == "user1"
        assert fork.changes["description"] == "Modified version"

    def test_defaults(self):
        """测试默认值"""
        fork = ToolFork(original_tool="orig", forked_tool="fork", user_id="user1")
        assert fork.changes == {}
        assert isinstance(fork.timestamp, float)


class TestMarketplaceTool:
    """MarketplaceTool 类测试"""

    def test_initialization(self):
        """测试初始化"""
        tool = MarketplaceTool(
            tool_id="tool1",
            name="File Reader",
            description="Reads files",
            version="1.0.0",
            author="author1"
        )
        assert tool.tool_id == "tool1"
        assert tool.name == "File Reader"
        assert tool.description == "Reads files"
        assert tool.version == "1.0.0"
        assert tool.author == "author1"

    def test_defaults(self):
        """测试默认值"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        assert tool.description == ""
        assert tool.version == "1.0.0"
        assert tool.author == ""
        assert tool.categories == []
        assert tool.tags == []
        assert tool.downloads == 0
        assert tool.rating is None
        assert tool.reviews == []
        assert tool.forks == []
        assert tool.featured == False
        assert tool.deprecated == False

    def test_add_review(self):
        """测试添加评论"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        review = ToolReview(user_id="user1", rating=4.0, comment="Good")
        
        tool.add_review(review)
        assert len(tool.reviews) == 1
        assert tool.reviews[0] == review

    def test_recompute_rating(self):
        """测试重新计算评分"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        
        # 添加评论
        tool.add_review(ToolReview(user_id="user1", rating=4.0))
        tool.add_review(ToolReview(user_id="user2", rating=5.0))
        tool.add_review(ToolReview(user_id="user3", rating=3.0))
        
        tool._recompute_rating()
        
        # 验证评分已计算
        assert tool.rating is not None
        assert isinstance(tool.rating, BayesianRating)

    def test_to_dict(self):
        """测试转换为字典"""
        tool = MarketplaceTool(
            tool_id="tool1",
            name="Tool 1",
            description="Description",
            version="1.0.0",
            author="author1"
        )
        
        data = tool.to_dict()
        assert data["tool_id"] == "tool1"
        assert data["name"] == "Tool 1"
        assert data["description"] == "Description"
        assert data["version"] == "1.0.0"
        assert data["author"] == "author1"

    def test_to_published_dict(self):
        """测试转换为发布字典"""
        tool = MarketplaceTool(
            tool_id="tool1",
            name="Tool 1",
            description="Description",
            version="1.0.0",
            author="author1"
        )
        
        data = tool.to_published_dict()
        assert "tool_id" in data
        assert "name" in data
        assert "rating" in data  # 评分应该被包含

    def test_serialization_roundtrip(self):
        """测试序列化往返"""
        tool = MarketplaceTool(
            tool_id="tool1",
            name="Tool 1",
            description="Description",
            version="1.0.0",
            author="author1",
            categories=["file", "utility"],
            tags=["read", "file"]
        )
        
        data = tool.to_dict()
        
        # 从字典重建
        new_tool = MarketplaceTool.from_dict(data)
        assert new_tool.tool_id == tool.tool_id
        assert new_tool.name == tool.name
        assert new_tool.categories == tool.categories


class TestToolMarketplace:
    """ToolMarketplace 类测试"""

    def setup_method(self):
        """每个测试前重置"""
        self.marketplace = ToolMarketplace()

    def test_initialization(self):
        """测试初始化"""
        assert len(self.marketplace._tools) == 0

    def test_add_tool(self):
        """测试添加工具"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        self.marketplace.add_tool(tool)
        
        assert len(self.marketplace._tools) == 1
        assert self.marketplace.get_tool("tool1") == tool

    def test_get_tool(self):
        """测试获取工具"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        self.marketplace.add_tool(tool)
        
        retrieved = self.marketplace.get_tool("tool1")
        assert retrieved == tool
        
        # 测试不存在的工具
        assert self.marketplace.get_tool("nonexistent") is None

    def test_get_tool_by_name(self):
        """测试按名称获取工具"""
        tool = MarketplaceTool(tool_id="tool1", name="File Reader")
        self.marketplace.add_tool(tool)
        
        retrieved = self.marketplace.get_tool_by_name("File Reader")
        assert retrieved == tool
        
        # 测试不存在的名称
        assert self.marketplace.get_tool_by_name("Nonexistent") is None

    def test_deprecate(self):
        """测试弃用工具"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        self.marketplace.add_tool(tool)
        
        self.marketplace.deprecate("tool1")
        
        deprecated = self.marketplace.get_tool("tool1")
        assert deprecated.deprecated == True

    def test_search(self):
        """测试搜索工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="File Reader", description="Reads files")
        tool2 = MarketplaceTool(tool_id="tool2", name="File Writer", description="Writes files")
        tool3 = MarketplaceTool(tool_id="tool3", name="Web Search", description="Searches web")
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        # 搜索文件相关工具
        results = self.marketplace.search("file")
        assert len(results) == 2
        assert tool1 in results
        assert tool2 in results
        
        # 搜索网络相关工具
        results = self.marketplace.search("web")
        assert len(results) == 1
        assert tool3 in results

    def test_get_top_rated(self):
        """测试获取评分最高的工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1")
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2")
        tool3 = MarketplaceTool(tool_id="tool3", name="Tool 3")
        
        # 添加评论
        tool1.add_review(ToolReview(user_id="user1", rating=5.0))
        tool2.add_review(ToolReview(user_id="user1", rating=3.0))
        tool3.add_review(ToolReview(user_id="user1", rating=4.0))
        
        # 重新计算评分
        tool1._recompute_rating()
        tool2._recompute_rating()
        tool3._recompute_rating()
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        top_rated = self.marketplace.get_top_rated(limit=2)
        assert len(top_rated) == 2
        assert top_rated[0] == tool1  # 最高分

    def test_get_most_downloaded(self):
        """测试获取下载量最高的工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1", downloads=100)
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2", downloads=50)
        tool3 = MarketplaceTool(tool_id="tool3", name="Tool 3", downloads=200)
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        most_downloaded = self.marketplace.get_most_downloaded(limit=2)
        assert len(most_downloaded) == 2
        assert most_downloaded[0] == tool3  # 最高下载量

    def test_get_featured(self):
        """测试获取精选工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1", featured=True)
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2", featured=False)
        tool3 = MarketplaceTool(tool_id="tool3", name="Tool 3", featured=True)
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        featured = self.marketplace.get_featured()
        assert len(featured) == 2
        assert tool1 in featured
        assert tool3 in featured

    def test_mark_featured(self):
        """测试标记精选"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        self.marketplace.add_tool(tool)
        
        self.marketplace.mark_featured("tool1", featured=True)
        
        featured_tool = self.marketplace.get_tool("tool1")
        assert featured_tool.featured == True

    def test_rate(self):
        """测试评分"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1")
        self.marketplace.add_tool(tool)
        
        self.marketplace.rate("tool1", "user1", 4.5, "Good tool")
        
        rated_tool = self.marketplace.get_tool("tool1")
        assert len(rated_tool.reviews) == 1
        assert rated_tool.reviews[0].rating == 4.5

    def test_record_download(self):
        """测试记录下载"""
        tool = MarketplaceTool(tool_id="tool1", name="Tool 1", downloads=0)
        self.marketplace.add_tool(tool)
        
        self.marketplace.record_download("tool1")
        self.marketplace.record_download("tool1")
        
        downloaded_tool = self.marketplace.get_tool("tool1")
        assert downloaded_tool.downloads == 2

    def test_fork_tool(self):
        """测试 Fork 工具"""
        original = MarketplaceTool(
            tool_id="original",
            name="Original Tool",
            description="Original description",
            author="author1"
        )
        self.marketplace.add_tool(original)
        
        forked = self.marketplace.fork_tool(
            original_tool_id="original",
            new_tool_id="forked",
            new_name="Forked Tool",
            user_id="user1",
            changes={"description": "Modified description"}
        )
        
        assert forked.tool_id == "forked"
        assert forked.name == "Forked Tool"
        assert forked.author == "user1"  # Fork 的作者是 fork 用户
        
        # 验证 fork 记录
        assert len(original.forks) == 1
        assert original.forks[0].forked_tool == "forked"

    def test_get_fork_history(self):
        """测试获取 Fork 历史"""
        original = MarketplaceTool(tool_id="original", name="Original")
        self.marketplace.add_tool(original)
        
        # 创建几个 fork
        self.marketplace.fork_tool("original", "fork1", "Fork 1", "user1")
        self.marketplace.fork_tool("original", "fork2", "Fork 2", "user2")
        
        history = self.marketplace.get_fork_history("original")
        assert len(history) == 2
        assert history[0].forked_tool == "fork1"
        assert history[1].forked_tool == "fork2"

    def test_get_categories(self):
        """测试获取分类"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1", categories=["file", "utility"])
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2", categories=["web", "search"])
        tool3 = MarketplaceTool(tool_id="tool3", name="Tool 3", categories=["file", "data"])
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        categories = self.marketplace.get_categories()
        assert "file" in categories
        assert "web" in categories
        assert "utility" in categories
        assert "search" in categories
        assert "data" in categories

    def test_get_tools_by_category(self):
        """测试按分类获取工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1", categories=["file"])
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2", categories=["web"])
        tool3 = MarketplaceTool(tool_id="tool3", name="Tool 3", categories=["file", "data"])
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        self.marketplace.add_tool(tool3)
        
        file_tools = self.marketplace.get_tools_by_category("file")
        assert len(file_tools) == 2
        assert tool1 in file_tools
        assert tool3 in file_tools
        
        web_tools = self.marketplace.get_tools_by_category("web")
        assert len(web_tools) == 1
        assert tool2 in web_tools

    def test_list_tools(self):
        """测试列出所有工具"""
        tool1 = MarketplaceTool(tool_id="tool1", name="Tool 1")
        tool2 = MarketplaceTool(tool_id="tool2", name="Tool 2")
        
        self.marketplace.add_tool(tool1)
        self.marketplace.add_tool(tool2)
        
        tools = self.marketplace.list_tools()
        assert len(tools) == 2
        assert tool1 in tools
        assert tool2 in tools


if __name__ == "__main__":
    pytest.main([__file__, "-v"])