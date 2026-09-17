"""最终检查：验证后端是否正常启动并响应请求"""
import sys
import time
sys.path.insert(0, r"e:\项目\Neurova")

print("=== 1. 检查 NEUTokenManager 方法 ===")
try:
    from neurova.auth import NEUTokenManager
    mgr = NEUTokenManager()
    for method in ['_on_init', '_on_start', '_on_ready', '_on_stop', '_health_check']:
        has = hasattr(mgr, method)
        print(f"  {method}: {'OK' if has else 'MISSING'}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== 2. 检查 MultiAgentSleepManager 方法 ===")
try:
    from neurova.core.multi_agent_sleep_manager import MultiAgentSleepManager
    mgr = MultiAgentSleepManager()
    for method in ['_on_init', '_on_start', '_on_ready', '_on_stop', '_health_check']:
        has = hasattr(mgr, method)
        print(f"  {method}: {'OK' if has else 'MISSING'}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== 3. 尝试导入 app ===")
try:
    from neurova.api.app import app
    print("  app imported OK")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback
    # 只打印最后 10 行
    tb = traceback.format_exc().split("\n")
    for line in tb[-10:]:
        print(f"  {line}")

print("\n=== 4. 启动后端并测试 ===")
# 如果前面都 OK，尝试启动后端
if __name__ == "__main__":
    pass
