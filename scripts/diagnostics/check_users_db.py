#!/usr/bin/env python3
"""检查用户数据库"""

import sqlite3
import os

db_path = "data/users.db"
if not os.path.exists(db_path):
    print(f"数据库不存在: {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取所有表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("数据库表:")
    for table in tables:
        print(f"  - {table[0]}")
    
    # 检查用户表结构
    print("\n用户表结构:")
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    # 查询所有用户
    print("\n用户数据:")
    cursor.execute("SELECT id, username, email, role, status FROM users")
    users = cursor.fetchall()
    for user in users:
        print(f"  ID: {user[0]}, 用户名: {user[1]}, 邮箱: {user[2]}, 角色: {user[3]}, 状态: {user[4]}")
    
    # 检查admin用户
    print("\n检查admin用户:")
    cursor.execute("SELECT id, username, password_hash, role, status FROM users WHERE username = 'admin'")
    admin = cursor.fetchone()
    if admin:
        print(f"  找到admin用户:")
        print(f"    ID: {admin[0]}")
        print(f"    用户名: {admin[1]}")
        print(f"    密码哈希: {admin[2][:50]}...")
        print(f"    角色: {admin[3]}")
        print(f"    状态: {admin[4]}")
    else:
        print("  未找到admin用户")
    
    conn.close()
    
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
