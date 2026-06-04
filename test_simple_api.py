#!/usr/bin/env python3
"""
简单API测试
"""

import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from neurova.api.app import create_app

app = create_app()
client = TestClient(app)

# 测试获取上下文池设置
print("测试获取上下文池设置:")
response = client.get("/api/v1/context/pool-settings")
print(f"状态码: {response.status_code}")
print(f"响应: {response.json()}")

# 测试更新上下文池设置
print("\n测试更新上下文池设置:")
update_data = {
    "max_size": 150,
    "ttl_seconds": 7200,
    "default_token_budget": 32000
}
response = client.put("/api/v1/context/pool-settings", json=update_data)
print(f"状态码: {response.status_code}")
print(f"响应: {response.json()}")

# 测试获取特定模型的Token预算
print("\n测试获取特定模型的Token预算:")
response = client.get("/api/v1/context/pool-settings/token-budget/gpt-4")
print(f"状态码: {response.status_code}")
print(f"响应: {response.json()}")