"""
浏览器自动化功能测试脚本

测试 Neurova 的浏览器自动化能力，包括：
- 多后端支持
- 混合路由
- Scrapling 自适应抓取
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neurova.computer_use.browser_manager import get_browser_manager


async def test_browser_automation():
    """测试浏览器自动化功能"""
    print("=" * 60)
    print("Neurova 浏览器自动化功能测试")
    print("=" * 60)
    
    browser = get_browser_manager()
    
    # 显示状态
    print("\n1. 浏览器管理器状态:")
    status = browser.get_status()
    for key, value in status.items():
        print(f"   {key}: {value}")
    
    # 测试公开网站（自动路由到 Playwright）
    print("\n2. 测试公开网站导航（自动路由）:")
    try:
        result = await browser.navigate("https://example.com")
        print(f"   状态: {result.get('status')}")
        print(f"   后端: {result.get('backend')}")
        print(f"   URL: {result.get('url')}")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 测试私有地址（自动路由到本地）
    print("\n3. 测试私有地址导航:")
    try:
        result = await browser.navigate("http://localhost:8080")
        print(f"   状态: {result.get('status')}")
        print(f"   后端: {result.get('backend')}")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 测试提取文本
    print("\n4. 测试提取文本:")
    try:
        result = await browser.extract_text("https://example.com", "h1")
        print(f"   状态: {result.get('status')}")
        if "text" in result:
            print(f"   文本: {result['text'][:100]}...")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 测试提取链接
    print("\n5. 测试提取链接:")
    try:
        result = await browser.extract_links("https://example.com")
        print(f"   状态: {result.get('status')}")
        if "links" in result:
            print(f"   链接数量: {len(result['links'])}")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 测试 JavaScript 执行
    print("\n6. 测试 JavaScript 执行:")
    try:
        result = await browser.execute_js("https://example.com", "document.title")
        print(f"   状态: {result.get('status')}")
        if "result" in result:
            print(f"   结果: {result['result']}")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 测试 Scrapling 抓取（如果可用）
    print("\n7. 测试 Scrapling 抓取:")
    try:
        result = await browser.scrape("https://example.com", mode="auto")
        print(f"   状态: {result.get('status')}")
        print(f"   后端: {result.get('backend')}")
    except Exception as e:
        print(f"   错误: {e}")
    
    # 清理
    print("\n8. 清理资源:")
    try:
        await browser.close_all()
        print("   所有后端已关闭")
    except Exception as e:
        print(f"   清理错误: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


async def test_routing_logic():
    """测试混合路由逻辑"""
    print("\n" + "=" * 60)
    print("混合路由逻辑测试")
    print("=" * 60)
    
    browser = get_browser_manager()
    
    test_cases = [
        ("https://example.com", "playwright", "公开网站"),
        ("http://localhost:3000", "playwright", "本地地址"),
        ("http://127.0.0.1:8080", "playwright", "本地回环"),
        ("http://192.168.1.100:8080", "playwright", "内网地址"),
        ("https://cloudflare.com/test", "scrapling-stealthy", "Cloudflare 站点"),
        ("https://example.com/app/dashboard", "scrapling-dynamic", "SPA 应用"),
    ]
    
    for url, expected_backend, description in test_cases:
        backend = browser._resolve_backend(url)
        status = "✓" if backend == expected_backend else "✗"
        print(f"   {status} {description}: {url}")
        print(f"     期望: {expected_backend}, 实际: {backend}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    print("Neurova 浏览器自动化测试")
    print("注意：此测试需要安装以下依赖：")
    print("  - playwright")
    print("  - websockets")
    print("  - scrapling (可选)")
    print()
    
    # 运行测试
    asyncio.run(test_routing_logic())
    asyncio.run(test_browser_automation())
