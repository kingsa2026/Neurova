"""

测试爬虫编排功能
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# 添加项目根目录到 Python 路径
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.computer_use.browser_manager import ScraplingSpiderTool


class TestScraplingSpiderToolInit:
    """"""
    
    def test_spider_tool_initialization(self):
        """"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有基本的属性
        assert spider_tool is not None
        assert hasattr(spider_tool, 'default_concurrency')
        assert hasattr(spider_tool, 'default_domain_delay')
        assert hasattr(spider_tool, 'obey_robots')
    
    def test_spider_tool_default_config(self):
        """"""
        spider_tool = ScraplingSpiderTool()
        
        # 默认配置
        assert spider_tool.default_concurrency == 5
        assert spider_tool.default_domain_delay == 1.0
        assert spider_tool.obey_robots == True


class TestScraplingSpiderToolMethods:
    """"""
    
    def test_spider_tool_has_create_spider_method(self):
        """"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有创建爬虫方法
        assert hasattr(spider_tool, 'create_spider')
        assert callable(spider_tool.create_spider)
    
    def test_spider_tool_has_run_spider_method(self):
        """"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有运行爬虫方法
        assert hasattr(spider_tool, 'run_spider')
        assert callable(spider_tool.run_spider)
    
    def test_spider_tool_has_stop_spider_method(self):
        """"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有停止爬虫方法
        assert hasattr(spider_tool, 'stop_spider')
        assert callable(spider_tool.stop_spider)


class TestScraplingSpiderToolCreateSpider:
    """"""

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_create_spider_with_default_config(self):
        """测试使用默认配置创建爬虫"""
        spider_tool = ScraplingSpiderTool()
        
        # 创建爬虫
        spider_id = spider_tool.create_spider(
            name="test_spider",
            start_urls=["https://example.com"]
        )
        
        # 应该返回爬虫对象
        assert spider_id is not None
        spider = spider_tool.spiderConfig(spider_id)
        assert spider is not None
        assert spider["name"] == "test_spider"
    
    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_create_spider_with_custom_config(self):
        """测试使用自定义配置创建爬虫"""
        spider_tool = ScraplingSpiderTool()
        
        # 创建爬虫
        spider_id = spider_tool.create_spider(
            name="custom_spider",
            start_urls=["https://example.com"],
            concurrency=10,
            domain_delay=2.0,
            obey_robots=False
        )
        
        # 应该返回爬虫对象
        assert spider_id is not None
        spider = spider_tool.spiderConfig(spider_id)
        assert spider["concurrency"] == 10
        assert spider["domain_delay"] == 2.0
        assert spider["obey_robots"] == False


class TestSpiderKnobsActuallyRead:
    """旋钮必须真有读者 —— 只写不读的 kwargs 就是幻影旋钮（与 T-04 同族）。

    登记面之外还要证明 `run_spider` 真的按这些值行动：`obey_robots` 尤其，
    它一旦不生效，默认口径下的抓取就不受 robots.txt 约束 —— 那是合规缺陷。
    """

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_obeyRobotsActuallyRefusesADisallowedUrl(self, monkeypatch):
        tool = ScraplingSpiderTool()
        spider_id = tool.create_spider(
            name="r", start_urls=["https://site.internal/private/page"])

        async def fakeRobots(origin):
            return ("User-agent: *\nDisallow: /private\n", "ok")

        fetched: list = []

        async def fakePage(url):
            fetched.append(url)
            return "body"

        monkeypatch.setattr(tool, "_fetchRobots", fakeRobots)
        monkeypatch.setattr(tool, "_fetchPage", fakePage)

        result = asyncio.run(tool.run_spider(spider_id))
        assert result.success is True, result.error
        assert fetched == [], f"robots.txt 禁止却还是抓了：{fetched}"
        assert result.data[0]["skipped"] is True
        assert "obey_robots" in result.data[0]["reason"], result.data

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_obeyRobotsFalseActuallySkipsTheCheck(self, monkeypatch):
        """反向锁：关掉开关就真的不看 robots —— 两档必须给出不同行为。"""
        tool = ScraplingSpiderTool()
        spider_id = tool.create_spider(
            name="r", start_urls=["https://site.internal/private/page"], obey_robots=False)

        async def explodingRobots(origin):
            raise AssertionError("obey_robots=False 时不该去取 robots.txt")

        async def fakePage(url):
            return "body"

        monkeypatch.setattr(tool, "_fetchRobots", explodingRobots)
        monkeypatch.setattr(tool, "_fetchPage", fakePage)

        result = asyncio.run(tool.run_spider(spider_id))
        assert result.success is True, result.error
        assert result.data[0]["text"] == "body"

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_unreadableRobotsFailsClosed(self, monkeypatch):
        """取不到 robots.txt 且非 404 → 不知道限制就不抓（404 才是"无限制"）。"""
        tool = ScraplingSpiderTool()
        spider_id = tool.create_spider(name="r", start_urls=["https://site.internal/a"])

        async def unreachable(origin):
            return None, "unreachable: ConnectTimeout"

        fetched: list = []

        async def fakePage(url):
            fetched.append(url)
            return "body"

        monkeypatch.setattr(tool, "_fetchRobots", unreachable)
        monkeypatch.setattr(tool, "_fetchPage", fakePage)
        result = asyncio.run(tool.run_spider(spider_id))
        assert fetched == [], f"无法判定时仍抓取 = fail-open：{fetched}"
        assert "unreachable" in result.data[0]["reason"], result.data

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_absentRobotsAllowsFetch(self, monkeypatch):
        """404（没有 robots.txt）标准语义是无限制，不得被保守成"全不抓"。"""
        tool = ScraplingSpiderTool()
        spider_id = tool.create_spider(name="r", start_urls=["https://site.internal/a"])

        async def absent(origin):
            return None, "absent"

        async def fakePage(url):
            return "body"

        monkeypatch.setattr(tool, "_fetchRobots", absent)
        monkeypatch.setattr(tool, "_fetchPage", fakePage)
        result = asyncio.run(tool.run_spider(spider_id))
        assert result.data[0]["text"] == "body", result.data

    @patch('neurova.computer_use.browser_manager.HAS_SCRAPLING', True)
    def test_illegalKnobValueIsNamedNotSilentlyCoerced(self):
        tool = ScraplingSpiderTool()
        with pytest.raises(ValueError):
            tool.create_spider(name="r", start_urls=["https://a.com"], concurrency="abc")
        with pytest.raises(ValueError):
            tool.create_spider(name="r", start_urls=["https://a.com"], concurrency=0)
        with pytest.raises(ValueError):
            tool.create_spider(name="r", start_urls=[])


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
