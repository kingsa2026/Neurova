"""一次性修复脚本：批量修复 logger 调用中的格式化语法错误。"""
import os
import re
from pathlib import Path


def fix_file(filepath):
    try:
        lines = Path(filepath).read_text(encoding='utf-8').splitlines(keepends=True)
    except Exception:
        return False
    
    changed = False
    new_lines = []
    
    for line in lines:
        # Fix pattern: logger.xxx("...", var:.2f)
        # Convert to: logger.xxx("...", var) with %:.2f in format string
        match = re.search(r'logger\.\w+\("[^"]*",\s*\w+:\.\d+f\)', line)
        if match:
            # Extract the format spec
            format_match = re.search(r':(\.\d+f)', line)
            if format_match:
                precision = format_match.group(1)
                # Replace %s with %<precision>
                line = re.sub(r'%s', f'%{precision}', line, count=1)
                # Remove the :<precision> from variable
                line = re.sub(r',\s*(\w+):\.\d+f\)', r', \1)', line)
                changed = True
        
        new_lines.append(line)
    
    if changed:
        Path(filepath).write_text(''.join(new_lines), encoding='utf-8')
        return True
    return False


# Find and fix files
fixed = 0
for root, dirs, files in os.walk('neurova'):
    if '.test_deps' in root:
        continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            if fix_file(path):
                fixed += 1
                print(f'Fixed: {path}')

print(f'\nTotal fixed: {fixed} files')
