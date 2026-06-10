#!/usr/bin/env python3
"""创建admin用户"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neurova.auth.user_model import UserModel
from neurova.api.auth import hash_password

def create_admin_user():
    """创建admin用户"""
    try:
        # 初始化用户模型
        user_model = UserModel(db_path="data/users.db")
        
        # 检查admin用户是否已存在
        existing_user = user_model.get_user_by_username("admin")
        if existing_user:
            print(f"admin用户已存在，ID: {existing_user.id}")
            print(f"用户名: {existing_user.username}")
            print(f"角色: {existing_user.role}")
            print(f"状态: {existing_user.status}")
            return
        
        # 哈希密码
        password = "Admin23@"
        password_hash = hash_password(password)
        
        # 创建admin用户
        user = user_model.create_user(
            username="admin",
            password_hash=password_hash,
            email="admin@neurova.local",
            role="admin",
            status="active"
        )
        
        print(f"admin用户创建成功!")
        print(f"用户ID: {user.id}")
        print(f"用户名: {user.username}")
        print(f"邮箱: {user.email}")
        print(f"角色: {user.role}")
        print(f"状态: {user.status}")
        print(f"密码: {password}")
        
    except Exception as e:
        print(f"创建admin用户失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    create_admin_user()