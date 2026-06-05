#!/usr/bin/env python3
"""
简单测试脚本 - tool_marketplace
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Testing tool_marketplace...")

try:
    from neurova.tool_layers.tool_marketplace import (
        BayesianRating, ToolReview, ToolFork, MarketplaceTool, ToolMarketplace
    )
    
    # 测试 BayesianRating
    rating = BayesianRating(c=10, m=3.0)
    score = rating.compute([5, 4, 5, 4, 5])
    print(f"✓ BayesianRating computed: {score:.2f}")
    
    # 测试 ToolReview
    review = ToolReview(user_id="user1", rating=4.5, comment="Great tool!")
    print(f"✓ ToolReview created: {review.user_id}")
    
    # 测试 ToolFork
    fork = ToolFork(original_tool="orig", forked_tool="fork", user_id="user1")
    print(f"✓ ToolFork created: {fork.original_tool}")
    
    # 测试 MarketplaceTool
    tool = MarketplaceTool(
        tool_id="tool1",
        name="File Reader",
        description="Reads files",
        version="1.0.0",
        author="author1"
    )
    print(f"✓ MarketplaceTool created: {tool.name}")
    
    # 测试添加评论
    tool.add_review(review)
    print(f"✓ Review added: {len(tool.reviews)} reviews")
    
    # 测试 ToolMarketplace
    marketplace = ToolMarketplace()
    marketplace.add_tool(tool)
    print(f"✓ Tool added to marketplace")
    
    # 测试获取工具
    retrieved = marketplace.get_tool("tool1")
    print(f"✓ Tool retrieved: {retrieved.name}")
    
    # 测试搜索
    results = marketplace.search("file")
    print(f"✓ Search results: {len(results)} tools")
    
    # 测试 Fork
    forked = marketplace.fork_tool(
        original_tool_id="tool1",
        new_tool_id="fork1",
        new_name="Forked Reader",
        user_id="user2",
        changes={"description": "Modified version"}
    )
    print(f"✓ Tool forked: {forked.name}")
    
    # 测试评分
    marketplace.rate("tool1", "user3", 4.0, "Good")
    print(f"✓ Tool rated")
    
    # 测试下载记录
    marketplace.record_download("tool1")
    print(f"✓ Download recorded")
    
    print("✓ tool_marketplace tests passed!")
    
except Exception as e:
    print(f"✗ tool_marketplace test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nAll tests passed!")