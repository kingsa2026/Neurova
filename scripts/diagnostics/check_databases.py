"""检查：列出主要 SQLite 数据库文件及其表名。"""
import sqlite3
import os
import sys
from pathlib import Path

# 仓库根须先于 `import neurova` 进 sys.path（脚本以文件路径执行）。
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.core.data_root import get_data_root  # noqa: E402


db_files = [str(get_data_root() / name) for name in ('neurova_memory.db', 'neurflow.db')]

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
