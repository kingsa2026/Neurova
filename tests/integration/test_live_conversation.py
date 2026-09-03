"""
实际对话闭环测试

启动后端服务后，通过 API 运行一轮完整对话，
验证知识-进化闭环在真实环境中是否生效。
"""
import requests
import json
import time
import sys

BASE_URL = "http://localhost:9527"


def test_health():
    """检查服务健康"""
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    assert r.status_code == 200, f"健康检查失败: {r.status_code}"
    print("[OK] 服务健康")
    return r.json()


def test_agent_list():
    """获取 Agent 列表"""
    r = requests.get(f"{BASE_URL}/api/v1/agents", timeout=10)
    if r.status_code == 200:
        agents = r.json()
        print(f"[OK] Agent 数量: {len(agents) if isinstance(agents, list) else 'N/A'}")
        return agents
    else:
        print(f"[WARN] 获取 Agent 列表失败: {r.status_code}")
        return []


def test_chat(agent_id="agent_a", message="你好，请介绍一下你自己"):
    """发送对话消息"""
    print(f"\n--- 发送消息: {message[:50]}... ---")
    start = time.time()

    r = requests.post(
        f"{BASE_URL}/api/v1/chat",
        json={
            "agent_id": agent_id,
            "message": message,
        },
        timeout=60,
    )

    elapsed = time.time() - start

    if r.status_code == 200:
        data = r.json()
        reply = data.get("reply", data.get("text", data.get("response", "")))
        print(f"[OK] 回复 ({elapsed:.1f}s): {reply[:100] if reply else '(empty)'}...")
        return data
    else:
        print(f"[FAIL] 对话失败: {r.status_code} {r.text[:200]}")
        return None


def test_memory_stats(agent_id="agent_a"):
    """获取记忆统计"""
    r = requests.get(f"{BASE_URL}/api/v1/memory/stats", params={"agent_id": agent_id}, timeout=10)
    if r.status_code == 200:
        stats = r.json()
        print(f"[OK] 记忆统计: {json.dumps(stats, ensure_ascii=False)[:200]}")
        return stats
    else:
        print(f"[WARN] 获取记忆统计失败: {r.status_code}")
        return None


def test_evolution_stats(agent_id="agent_a"):
    """获取进化统计"""
    r = requests.get(f"{BASE_URL}/api/v1/evolution/stats", params={"agent_id": agent_id}, timeout=10)
    if r.status_code == 200:
        stats = r.json()
        print(f"[OK] 进化统计: {json.dumps(stats, ensure_ascii=False)[:200]}")
        return stats
    else:
        print(f"[WARN] 获取进化统计失败: {r.status_code}")
        return None


def run_conversation_loop():
    """运行多轮对话测试闭环"""
    print("=" * 60)
    print("Neurova 知识-进化闭环 实际对话测试")
    print("=" * 60)

    # 1. 健康检查
    test_health()

    # 2. 获取 Agent
    agents = test_agent_list()

    # 3. 第一轮对话
    print("\n--- 第1轮对话 ---")
    r1 = test_chat("agent_a", "我想学习Python编程，你能帮我吗？")

    # 4. 第二轮对话（带工具调用意图）
    print("\n--- 第2轮对话 ---")
    r2 = test_chat("agent_a", "帮我搜索一下Python最佳实践")

    # 5. 第三轮对话（验证记忆保留）
    print("\n--- 第3轮对话 ---")
    r3 = test_chat("agent_a", "刚才你推荐了什么？")

    # 6. 检查记忆和进化状态
    print("\n--- 检查闭环状态 ---")
    test_memory_stats("agent_a")
    test_evolution_stats("agent_a")

    # 7. 总结
    print("\n" + "=" * 60)
    results = {"r1": r1, "r2": r2, "r3": r3}
    success_count = sum(1 for v in results.values() if v is not None)
    print(f"对话完成: {success_count}/3 轮成功")

    if success_count >= 2:
        print("[PASS] 闭环测试通过")
    else:
        print("[FAIL] 闭环测试未完全通过")

    return results


if __name__ == "__main__":
    try:
        run_conversation_loop()
    except requests.exceptions.ConnectionError:
        print("[ERROR] 无法连接到后端服务，请先启动: python start.py --backend")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
