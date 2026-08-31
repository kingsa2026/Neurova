"""扫描 docs/ 所有相对链接，报告断链（docs/ 前缀链接按仓库根解析）。"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

broken = []
total = 0
for root, dirs, files in os.walk('docs'):
    if '.mimosa' in root or '__pycache__' in root or 'node_modules' in root:
        continue
    for fn in files:
        if not fn.endswith('.md'):
            continue
        path = os.path.join(root, fn)
        with open(path, encoding='utf-8', errors='ignore') as f:
            text = f.read()
        for m in re.finditer(r'\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)', text):
            target = m.group(1).strip()
            if target.startswith(('http', 'mailto:', '#', 'data:', 'file://', 'C:\\', 'c:\\', 'E:\\', 'e:\\')):
                continue
            total += 1
            if target.startswith('docs/'):
                resolved = os.path.normpath(os.path.join(REPO_ROOT, target))
            else:
                resolved = os.path.normpath(os.path.join(root, target))
            if not os.path.exists(resolved):
                broken.append((path.replace(os.sep, '/'), target))

print(f'有效相对链接: {total}, 断链: {len(broken)}')
for b in broken:
    print(f'  {b[0]} -> {b[1]}')
