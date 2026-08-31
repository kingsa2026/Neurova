"""一次性修复脚本：修复 Black 格式化导致的 logger 调用语法错误。

Black 将 logger.info("msg %s", var:.2f) 格式化为无效语法。
正确的写法是 logger.info("msg %.2f", var)。
"""

import os
import re
from pathlib import Path


def fix_logger_format(filepath):
    """修复文件中的 logger 格式错误"""
    try:
        content = Path(filepath).read_text(encoding='utf-8')
    except Exception:
        return False

    # 匹配 logger.xxx("...", var:.2f) 模式
    # 转换为 logger.xxx("...", var) 并将 %s 改为 %.2f
    pattern = r'(logger\.\w+\([^)]*?)(%s)([^)]*?),\s*(\w+):(\.\d+f)(\))'

    def replace_match(match):
        prefix = match.group(1)
        placeholder = match.group(2)
        middle = match.group(3)
        var_name = match.group(4)
        precision = match.group(5)
        suffix = match.group(6)

        # 将 %s 替换为 %.2f 格式
        new_placeholder = f'%{precision}'

        return f'{prefix}{new_placeholder}{middle}, {var_name}{suffix}'

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
                if fix_logger_format(filepath):
                    fixed_files.append(filepath)

    print(f'Fixed logger format in {len(fixed_files)} files')
    for f in fixed_files:
        print(f'  {f}')


if __name__ == '__main__':
    main()
