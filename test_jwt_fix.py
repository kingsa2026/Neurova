#!/usr/bin/env python3
"""
测试 JWT 修复
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

def test_jwt_import():
    """测试 JWT 导入"""
    print("测试 JWT 导入...")
    
    try:
        import jwt
        print(f"✅ PyJWT 导入成功，版本: {jwt.__version__}")
        return True
    except ImportError as e:
        print(f"❌ PyJWT 导入失败: {e}")
        return False

def test_auth_module():
    """测试 auth 模块导入"""
    print("\n测试 neurova.api.auth 模块...")
    
    try:
        from neurova.api.auth import create_access_token, create_refresh_token, decode_token
        print("✅ neurova.api.auth 模块导入成功")
        
        # 测试创建 token
        test_data = {"sub": "test-user-id", "username": "admin"}
        access_token = create_access_token(data=test_data)
        print(f"✅ Access token 创建成功: {access_token[:20]}...")
        
        # 测试解码 token
        payload = decode_token(access_token)
        print(f"✅ Token 解码成功: {payload}")
        
        return True
    except Exception as e:
        print(f"❌ neurova.api.auth 模块测试失败: {e}")
        return False

def test_login_endpoint():
    """测试登录端点"""
    print("\n测试登录端点...")
    
    try:
        from neurova.api.endpoints.auth import login, LoginRequest
        print("✅ 登录端点模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 登录端点测试失败: {e}")
        return False

def main():
    print("=" * 50)
    print("JWT 修复验证测试")
    print("=" * 50)
    
    results = []
    
    # 测试 1: JWT 导入
    results.append(("PyJWT 导入", test_jwt_import()))
    
    # 测试 2: Auth 模块
    results.append(("Auth 模块", test_auth_module()))
    
    # 测试 3: 登录端点
    results.append(("登录端点", test_login_endpoint()))
    
    print("\n" + "=" * 50)
    print("测试结果")
    print("=" * 50)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 所有测试通过！JWT 修复成功。")
        print("\n下一步:")
        print("1. 重启后端服务器")
        print("2. 尝试重新登录")
    else:
        print("❌ 测试失败，需要进一步检查。")
        print("\n建议:")
        print("1. 确保已安装 PyJWT: pip install PyJWT")
        print("2. 检查 Python 环境是否正确")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)