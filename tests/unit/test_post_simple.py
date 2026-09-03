"""
最简单的 POST 测试脚本
用于诊断为什么 POST 请求返回 404 Not Found
"""
import requests
import json

BASE_URL = "http://localhost:9528"

def test_get():
    """测试 GET 请求"""
    print("=" * 50)
    print("测试 GET /api/v1/chat/test")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/chat/test", timeout=5)
        print(f"✅ Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_post():
    """测试 POST 请求"""
    print("=" * 50)
    print("测试 POST /api/v1/chat/test-post-direct2")
    print("=" * 50)
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/chat/test-post-direct2",
            json={},
            timeout=5
        )
        print(f"✅ Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_post_stream():
    """测试 POST /api/v1/chat/stream"""
    print("=" * 50)
    print("测试 POST /api/v1/chat/stream")
    print("=" * 50)
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/chat/stream",
            json={"message": "test", "agent_id": "yi_ling"},
            timeout=5
        )
        print(f"✅ Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("开始测试...")
    print()
    
    # 测试 GET
    if not test_get():
        print("\n⚠️ GET 请求失败，后端可能未启动")
        exit(1)
    
    print()
    
    # 测试 POST
    if not test_post():
        print("\n⚠️ POST 请求失败，可能的原因：")
        print("  1. 路由未注册")
        print("  2. 函数定义有错误")
        print("  3. 中间件拦截了请求")
    
    print()
    
    # 测试 POST /stream
    if not test_post_stream():
        print("\n⚠️ POST /stream 请求失败")
    
    print()
    print("测试完成")
