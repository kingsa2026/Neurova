"""
测试脚本：直接测试 LLM 客户端（修复版）
"""
import requests
import json
import time

print("=== 测试1: 直接测试火山引擎 API ===")

# 火山引擎 API 配置
base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
model = "glm-5.1"

# 测试连接（使用无效 Key，应该返回 401 错误，而不是卡住）
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer invalid-key-for-testing"
}

data = {
    "model": model,
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
}

print(f"请求 URL: {base_url}/chat/completions")
print(f"模型: {model}")
print("开始请求（超时10秒）...")

start = time.time()
try:
    response = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=data,
        timeout=10
    )
    elapsed = time.time() - start
    print(f"✅ 请求完成（耗时 {elapsed:.2f} 秒）")
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text[:500]}")
    
except requests.exceptions.Timeout:
    elapsed = time.time() - start
    print(f"❌ 请求超时（{elapsed:.2f} 秒）")
    print("结论：无法连接到火山引擎 API")
    
except Exception as e:
    elapsed = time.time() - start
    print(f"❌ 请求失败（{elapsed:.2f} 秒）: {type(e).__name__}: {str(e)[:200]}")

print("\n=== 测试2: 检查 Agent 配置 ===")
try:
    with open("neurova/agents/kai/workspace/agent.json", "r", encoding="utf-8") as f:
        agent_config = json.load(f)
    
    print(f"LLM Provider: {agent_config.get('llm_provider')}")
    print(f"LLM Model: {agent_config.get('llm_model')}")
    print(f"LLM Base URL: {agent_config.get('llm_base_url')}")
    
except Exception as e:
    print(f"❌ 读取配置失败: {e}")

print("\n=== 测试完成 ===")
