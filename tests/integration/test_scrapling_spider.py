"""
Scrapling Spider 测试

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
    """测试 ScraplingSpiderTool 初始化"""
    
    def test_spider_tool_initialization(self):
        """测试 ScraplingSpiderTool 初始化"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有基本的属性
        assert spider_tool is not None
        assert hasattr(spider_tool, 'default_concurrency')
        assert hasattr(spider_tool, 'default_domain_delay')
        assert hasattr(spider_tool, 'obey_robots')
    
    def test_spider_tool_default_config(self):
        """测试 ScraplingSpiderTool 默认配置"""
        spider_tool = ScraplingSpiderTool()
        
        # 默认配置
        assert spider_tool.default_concurrency == 5
        assert spider_tool.default_domain_delay == 1.0
        assert spider_tool.obey_robots == True


class TestScraplingSpiderToolMethods:
    """测试 ScraplingSpiderTool 方法"""
    
    def test_spider_tool_has_create_spider_method(self):
        """测试 ScraplingSpiderTool 有创建爬虫方法"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有创建爬虫方法
        assert hasattr(spider_tool, 'create_spider')
        assert callable(spider_tool.create_spider)
    
    def test_spider_tool_has_run_spider_method(self):
        """测试 ScraplingSpiderTool 有运行爬虫方法"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有运行爬虫方法
        assert hasattr(spider_tool, 'run_spider')
        assert callable(spider_tool.run_spider)
    
    def test_spider_tool_has_stop_spider_method(self):
        """测试 ScraplingSpiderTool 有停止爬虫方法"""
        spider_tool = ScraplingSpiderTool()
        
        # 应该有停止爬虫方法
        assert hasattr(spider_tool, 'stop_spider')
        assert callable(spider_tool.stop_spider)


class TestScraplingSpiderToolCreateSpider:
    """测试 ScraplingSpiderTool 创建爬虫"""
    
    @patch('neurova.computer_use.browser_manager.HAS_SCRAPELY', True)
    def test_create_spider_with_default_config(self):
        """测试使用默认配置创建爬虫"""
        spider_tool = ScraplingSpiderTool()
        
        # 创建爬虫
        spider = spider_tool.create_spider(
            name="test_spider",
            start_urls=["https://example.com"]
        )
        
        # 应该返回爬虫对象
        assert spider is not None
        assert hasattr(spider, 'name')
        assert spider.name == "test_spider"
    
    @patch('neurova.computer_use.browser_manager.HAS_SCRAPELY', True)
    def test_create_spider_with_custom_config(self):
        """测试使用自定义配置创建爬虫"""
        spider_tool = ScraplingSpiderTool()
        
        # 创建爬虫
        spider = spider_tool.create_spider(
            name="custom_spider",
            start_urls=["https://example.com"],
            concurrency=10,
            domain_delay=2.0,
            obey_robots=False
        )
        
        # 应该返回爬虫对象
        assert spider is not None
        assert spider.concurrency == 10
        assert spider.domain_delay == 2.0
        assert spider.obey_robots == False


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])