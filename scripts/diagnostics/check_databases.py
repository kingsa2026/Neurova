"""检查：列出主要 SQLite 数据库文件及其表名。"""
import sqlite3
import os

db_files = ['neurova_memory.db', 'neurflow.db', 'data/neurova_memory.db']

for db in db_files:
    if os.path.exists(db):
        size = os.path.getsize(db)
        print(f'{db}: {size:,} bytes')
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            if tables:
                print(f'  Tables: {[t[0] for t in tables]}')
            conn.close()
        except Exception as e:
            print(f'  Error: {e}')
    else:
        print(f'{db}: not found')
