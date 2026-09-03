"""
测试脚本：测试火山引擎编程助手 API 的可用模型
"""
import requests
import json
import time

print("=== 测试：火山引擎编程助手 API ===")

# 从配置读取 API Key
print("\n=== 读取 API Key ===")
try:
    from neurova.llm.provider_manager import get_provider_manager
    pm = get_provider_manager()
    provider = pm.get_provider('volcano-coding-cn')
    api_key = provider.api_key
    print(f"✅ API Key 已读取（前缀: {api_key[:10]}...）")
except Exception as e:
    print(f"❌ 读取 API Key 失败: {e}")
    api_key = None

if not api_key:
    print("\n⚠️  API Key 未配置，使用测试模式（预期返回 401 错误）")
    api_key = "invalid-key-for-testing"

# 测试不同的模型
base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
models_to_test = [
    "glm-5.1",
    "doubao-seed-code",
    "deepseek-v3",
    "claude-3.5-sonnet"
]

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

for model in models_to_test:
    print(f"\n=== 测试模型: {model} ===")
    
    data = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 100
    }
    
    start = time.time()
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=data,
            timeout=10
        )
        elapsed = time.time() - start
        print(f"状态码: {response.status_code}（耗时 {elapsed:.2f} 秒）")
        
        response_data = response.json()
        
        # 检查是否有错误
        if "error" in response_data:
            error_msg = response_data["error"].get("message", "Unknown error")
            print(f"❌ 错误: {error_msg}")
        else:
            print(f"✅ 模型可用！")
            print(f"  响应: {json.dumps(response_data, ensure_ascii=False)[:200]}")
            break  # 找到可用模型，退出循环
            
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"❌ 请求超时（{elapsed:.2f} 秒）")
        
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ 请求失败（{elapsed:.2f} 秒）: {type(e).__name__}: {str(e)[:200]}")

print("\n=== 测试完成 ===")
print("\n建议：")
print("1. 如果所有模型都返回 401 错误，说明 API Key 无效或权限不足")
print("2. 如果模型返回 'model not found' 错误，说明模型不存在")
print("3. 找到可用模型后，更新 agent.json 中的 llm_model 配置")
