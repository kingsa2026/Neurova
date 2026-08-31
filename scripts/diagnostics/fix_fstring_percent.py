"""一次性修复脚本：修复 Black 格式化导致的 f-string 百分比语法错误。

Black 将 {rate:.0%} 格式化为 {rate:.0%}，但 Python 的 f-string 不支持这种语法。
正确的写法是 {rate:.0%} → {rate * 100:.0f}%% 或使用 format()。
"""

import os
import re
from pathlib import Path


def fix_fstring_percent(filepath):
    """修复文件中的 f-string 百分比格式错误"""
    try:
        content = Path(filepath).read_text(encoding='utf-8')
    except Exception:
        return False

    # 匹配 {var:.0%} 或 {var:.1%} 等模式
    # 在 f-string 中，这应该写成 {var * 100:.0f}%% 或使用 format()
    pattern = r'\{(\w+(?:\.\w+)*)\:(\.\d+)%\}'

    def replace_match(match):
        var_name = match.group(1)
        precision = match.group(2)
        # 转换为 {var_name * 100:.0f}%%
        return f'{{{var_name} * 100:{precision}f}}%%'

    new_content = re.sub(pattern, replace_match, content)

    if new_content != content:
        Path(filepath).write_text(new_content, encoding='utf-8')
        return True
    return False


def main():
    fixed_files = []
    for root, dirs, files in os.walk('neurova'):
        # Skip test dependencies
        if '.test_deps' in root:
            continue
        for f in files:
            if f.endswith('.py'):
                filepath = os.path.join(root, f)
                if fix_fstring_percent(filepath):
                    fixed_files.append(filepath)

    print(f'Fixed f-string percent formatting in {len(fixed_files)} files')
    for f in fixed_files:
        print(f'  {f}')


if __name__ == '__main__':
    main()
