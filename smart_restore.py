"""
智能批量恢复脚本：从 .pyc 自动重建 .py 源文件
使用 marshal + dis 提取结构，生成可导入的骨架文件
"""
import os
import sys
import marshal
import dis
import struct
import types
import glob
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
NEUROVA_DIR = PROJECT_ROOT / "neurova"

def get_pyc_header_size():
    """获取 pyc 文件头大小（Python 3.15）"""
    return 16  # magic(4) + flags(4) + timestamp(4) + size(4)

def load_pyc(pyc_path):
    """加载 .pyc 文件"""
    with open(pyc_path, 'rb') as f:
        header_size = get_pyc_header_size()
        f.read(header_size)
        code = marshal.load(f)
    return code

def extract_imports(code):
    """从代码对象提取导入语句"""
    imports = []
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            imports.extend(extract_imports(const))
    
    for inst in dis.get_instructions(code):
        if inst.opname in ('IMPORT_NAME', 'IMPORT_FROM'):
            imports.append(inst.argval)
    
    return list(set(imports))

def extract_classes_and_functions(code):
    """从代码对象提取类和函数定义"""
    items = []
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            if const.co_name.startswith('<'):
                continue
            items.append({
                'name': const.co_name,
                'type': 'class' if any(
                    isinstance(c, types.CodeType) and c.co_name == '__init__'
                    for c in const.co_consts
                ) else 'function',
                'line': const.co_firstlineno,
                'docstring': const.co_consts[0] if const.co_consts and isinstance(const.co_consts[0], str) else None,
                'methods': [
                    c.co_name for c in const.co_consts 
                    if isinstance(c, types.CodeType) and not c.co_name.startswith('<')
                ] if any(isinstance(c, types.CodeType) and c.co_name == '__init__' for c in const.co_consts) else [],
            })
    return items

def extract_module_level_names(code):
    """提取模块级名称（变量、常量等）"""
    names = []
    for name in code.co_names:
        if name.startswith('_') and name.endswith('_'):
            continue  # 跳过 dunder 名称
        names.append(name)
    return names

def generate_skeleton(pyc_path, py_path, code):
    """生成骨架 .py 文件"""
    module_name = py_path.stem
    package_dir = py_path.parent
    
    # 提取结构
    imports = extract_imports(code)
    items = extract_classes_and_functions(code)
    module_names = extract_module_level_names(code)
    
    # 获取模块 docstring
    docstring = code.co_consts[0] if code.co_consts and isinstance(code.co_consts[0], str) else None
    
    lines = []
    
    # 模块 docstring
    if docstring:
        # 截断过长的 docstring
        doc_lines = docstring.strip().split('\n')
        if len(doc_lines) > 10:
            doc_lines = doc_lines[:10] + ['...']
        lines.append('"""')
        lines.extend(doc_lines)
        lines.append('"""')
        lines.append('')
    else:
        lines.append(f'"""')
        lines.append(f'{module_name} - Auto-restored from .pyc')
        lines.append(f'"""')
        lines.append('')
    
    # 标准库导入（只导入确实使用的）
    stdlib_imports = []
    thirdparty_imports = []
    local_imports = []
    
    for imp in imports:
        if imp.startswith('neurova.'):
            local_imports.append(imp)
        elif imp in ('os', 'sys', 'time', 'json', 'logging', 'datetime', 'typing', 
                     'pathlib', 'dataclasses', 'threading', 'asyncio', 'enum', 
                     'uuid', 'abc', 'functools', 'collections', 're', 'math',
                     'hashlib', 'base64', 'io', 'tempfile', 'shutil', 'copy',
                     'textwrap', 'contextlib', 'contextvars', 'traceback', 'inspect'):
            stdlib_imports.append(imp)
        elif imp in ('Dict', 'List', 'Optional', 'Any', 'Tuple', 'Set', 'Union',
                     'Callable', 'Iterator', 'Generator', 'AsyncGenerator',
                     'ClassVar', 'TypeVar', 'Generic', 'Protocol',
                     'dataclass', 'field', 'asdict'):
            pass  # 跳过 typing 内部导入
        else:
            thirdparty_imports.append(imp)
    
    # 写入导入
    if stdlib_imports:
        for imp in sorted(set(stdlib_imports)):
            lines.append(f'import {imp}')
        lines.append('')
    
    if thirdparty_imports:
        for imp in sorted(set(thirdparty_imports)):
            lines.append(f'import {imp}')
        lines.append('')
    
    # 按包分组 local imports
    local_groups = {}
    for imp in sorted(set(local_imports)):
        parts = imp.split('.')
        if len(parts) >= 2:
            group = parts[1]
            if group not in local_groups:
                local_groups[group] = []
            local_groups[group].append(imp)
    
    for group, imps in sorted(local_groups.items()):
        lines.append(f'# {group} imports')
        for imp in imps:
            lines.append(f'import {imp}')
        lines.append('')
    
    if not (stdlib_imports or thirdparty_imports or local_imports):
        lines.append('import logging')
        lines.append('')
        lines.append('logger = logging.getLogger(__name__)')
        lines.append('')
    
    # 写入类和函数
    for item in items:
        if item['type'] == 'class':
            lines.append('')
            if item['docstring']:
                doc = item['docstring'].strip().split('\n')
                if len(doc) > 5:
                    doc = doc[:5] + ['...']
                lines.append('class ' + item['name'] + ':')
                lines.append('    """')
                for d in doc:
                    lines.append(f'    {d}')
                lines.append('    """')
            else:
                lines.append(f'class {item["name"]}:')
                lines.append(f'    """TODO: Auto-restored from .pyc, needs implementation"""')
            
            if item['methods']:
                for method in item['methods']:
                    if method == '__init__':
                        lines.append(f'    def __init__(self, *args, **kwargs):')
                        lines.append(f'        pass')
                    else:
                        lines.append(f'    def {method}(self, *args, **kwargs):')
                        lines.append(f'        pass')
            else:
                lines.append(f'    pass')
            lines.append('')
        else:
            lines.append('')
            if item['docstring']:
                doc = item['docstring'].strip().split('\n')
                if len(doc) > 3:
                    doc = doc[:3] + ['...']
                lines.append(f'"""')
                lines.extend(doc)
                lines.append(f'"""')
            lines.append(f'def {item["name"]}(*args, **kwargs):')
            lines.append(f'    """TODO: Auto-restored from .pyc, needs implementation"""')
            lines.append(f'    pass')
            lines.append('')
    
    # 如果没有任何类/函数，写一个 pass
    if not items:
        lines.append('')
        lines.append('pass')
    
    # 写入文件
    content = '\n'.join(lines)
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(content, encoding='utf-8')
    return len(content)

def scan_and_restore(dry_run=False):
    """扫描并恢复所有缺失的 .py 文件"""
    pyc_files = glob.glob(
        str(NEUROVA_DIR / "**" / "__pycache__" / "*.cpython-315.pyc"),
        recursive=True
    )
    
    restored = 0
    failed = 0
    skipped = 0
    total_size = 0
    
    for pyc_path_str in pyc_files:
        pyc_path = Path(pyc_path_str)
        parts = pyc_path.parts
        
        # 找到 __pycache__ 的位置
        try:
            cache_idx = list(parts).index('__pycache__')
        except ValueError:
            continue
        
        # 构建 .py 路径
        py_name = parts[cache_idx + 1].replace('.cpython-315.pyc', '.py')
        py_parts = list(parts[:cache_idx]) + [py_name]
        py_path = Path(*py_parts)
        
        # 跳过已存在的文件
        if py_path.exists():
            skipped += 1
            continue
        
        try:
            code = load_pyc(pyc_path)
            size = generate_skeleton(pyc_path, py_path, code)
            restored += 1
            total_size += size
            rel = py_path.relative_to(PROJECT_ROOT)
            print(f"  RESTORED: {rel} ({size} bytes)")
        except Exception as e:
            failed += 1
            rel = py_path.relative_to(PROJECT_ROOT)
            print(f"  FAILED: {rel} -> {e}")
    
    print(f"\n=== Summary ===")
    print(f"Restored: {restored}")
    print(f"Failed: {failed}")
    print(f"Skipped (already exist): {skipped}")
    print(f"Total size: {total_size} bytes")

if __name__ == "__main__":
    scan_and_restore()
