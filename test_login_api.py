#!/usr/bin/env python3
"""测试登录API"""

import requests
import json

# 测试登录
url = "http://localhost:9527/api/v1/auth/login"
data = {
    "username": "admin",
    "password": "Admin23@"
}

headers = {
    "Content-Type": "application/json"
}

try:
    print("测试登录API...")
    response = requests.post(url, json=data, headers=headers)
    print(f"状态码: {response.status_code}")
    print(f"响应头: {response.headers}")
    print(f"响应内容: {response.text}")
    
    if response.status_code == 200:
        result = response.json()
        print("登录成功!")
        print(f"Token: {result.get('access_token', 'N/A')[:50]}...")
    else:
        print(f"登录失败: {response.status_code}")
        
except Exception as e:
    print(f"请求失败: {e}")
    import traceback
    traceback.print_exc()