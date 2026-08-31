"""一次性修复脚本：将 neurova/ 下 logger 的 f-string 调用转为 % 惰性格式化。"""
import re
import os
from pathlib import Path

def fix_logging_fstring(filepath):
    try:
        content = Path(filepath).read_text(encoding='utf-8')
    except Exception:
        return False
    
    # Pattern to match logging calls with f-strings
    pattern = r'(logger|logging|log)\.(debug|info|warning|error|critical|exception)\(f(["\'])(.*?)\3\)'
    
    def replace_fstring(match):
        prefix = match.group(1)
        level = match.group(2)
        quote = match.group(3)
        content_inside = match.group(4)
        
        # Skip if no interpolation variables
        if '{' not in content_inside:
            return match.group(0)
        
        # Simple conversion: replace {var} with %s and add args
        new_content = content_inside
        args = []
        
        # Find all {expr} patterns
        def replace_expr(m):
            expr = m.group(1)
            args.append(expr)
            return '%s'
        
        new_content = re.sub(r'\{([^}]+)\}', replace_expr, new_content)
        
        if args:
            args_str = ', '.join(args)
            return f'{prefix}.{level}({quote}{new_content}{quote}, {args_str})'
        return match.group(0)
    
    new_content = re.sub(pattern, replace_fstring, content)
    
    if new_content != content:
        Path(filepath).write_text(new_content, encoding='utf-8')
        return True
    return False

# Process all Python files
fixed_count = 0
for root, dirs, files in os.walk('neurova'):
    # Skip test dependencies
    if '.test_deps' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            if fix_logging_fstring(filepath):
                fixed_count += 1

print(f'Fixed logging f-strings in {fixed_count} files')
