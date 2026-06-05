#!/usr/bin/env python3
"""扫描项目中的 TODO 骨架文件"""
import os
import re
from pathlib import Path
from collections import Counter

ROOT = Path('neurova')
py_files = list(ROOT.rglob('*.py'))
print(f'总 Python 文件数: {len(py_files)}')

todo_files = []
for f in py_files:
    try:
        content = f.read_text(encoding='utf-8')
        pyc_count = content.count('TODO: Auto-restored')
        todo_inline = len(re.findall(r'#\s*TODO', content))
        if pyc_count > 0 or todo_inline > 0:
            todo_files.append((str(f.relative_to(ROOT)), pyc_count, todo_inline))
    except Exception:
        pass

print(f'\n含 TODO 标记的文件数: {len(todo_files)}')

# 按目录分布
dirs = Counter()
for path, _, _ in todo_files:
    parts = Path(path).parts
    key = parts[1] if len(parts) >= 2 else parts[0]
    dirs[key] += 1
print('\n按目录分布:')
for d, c in sorted(dirs.items(), key=lambda x: -x[1]):
    print(f'  {d}: {c}')

# pyc 恢复文件
pyc_files = [f for f in todo_files if f[1] > 0]
print(f'\n含 "Auto-restored from .pyc" 标记的文件:')
print(f'  数量: {len(pyc_files)}')
print(f'  总占位符数: {sum(f[1] for f in pyc_files)}')

# 内联 TODO
inline_files = [f for f in todo_files if f[2] > 0]
print(f'\n含内联 # TODO 的文件:')
print(f'  数量: {len(inline_files)}')
print(f'  总数: {sum(f[2] for f in inline_files)}')

# 列出 pyc 文件
print('\n--- 全部 pyc 骨架文件 ---')
for path, count, _ in sorted(pyc_files):
    print(f'  {path}: {count} 个占位符')
