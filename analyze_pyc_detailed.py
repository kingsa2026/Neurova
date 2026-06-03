import marshal
import dis
import types
import sys
import os
import re

def analyze_code_object(code, indent=0):
    """递归分析代码对象"""
    prefix = "  " * indent
    
    # 基本信息
    print(f"{prefix}Code object: {code.co_name}")
    print(f"{prefix}  File: {code.co_filename}")
    print(f"{prefix}  Line: {code.co_firstlineno}")
    print(f"{prefix}  Args: {code.co_varnames[:code.co_argcount]}")
    print(f"{prefix}  Locals: {code.co_varnames}")
    print(f"{prefix}  Names: {code.co_names}")
    
    # 常量
    print(f"{prefix}  Constants:")
    for i, const in enumerate(code.co_consts):
        if isinstance(const, (str, int, float, bool)):
            const_str = repr(const)[:100]
            print(f"{prefix}    {i}: {const_str}")
        elif isinstance(const, types.CodeType):
            print(f"{prefix}    {i}: <code object {const.co_name}>")
    
    # 递归分析子代码对象
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            print(f"{prefix}  Sub-code object:")
            analyze_code_object(const, indent + 2)

def analyze_class(class_code, indent=0):
    """分析类定义"""
    prefix = "  " * indent
    print(f"{prefix}Class: {class_code.co_name}")
    
    # 查找方法
    methods = []
    for const in class_code.co_consts:
        if isinstance(const, types.CodeType):
            methods.append(const)
    
    print(f"{prefix}  Methods ({len(methods)}):")
    for method in methods:
        args = method.co_varnames[:method.co_argcount]
        print(f"{prefix}    {method.co_name}({', '.join(args)}) - Line {method.co_firstlineno}")

def analyze_pyc_detailed(pyc_path):
    print(f"Detailed analysis: {pyc_path}")
    print("=" * 80)
    
    with open(pyc_path, 'rb') as f:
        # Skip magic number, flags, timestamp, size (16 bytes for Python 3.15)
        f.read(16)
        code = marshal.load(f)
    
    print("Module info:")
    print(f"  Name: {code.co_name}")
    print(f"  File: {code.co_filename}")
    print(f"  Size: {os.path.getsize(pyc_path)} bytes")
    
    print("\nModule-level imports and names:")
    for i, name in enumerate(code.co_names):
        print(f"  {i}: {name}")
    
    print("\nModule-level constants:")
    for i, const in enumerate(code.co_consts):
        if isinstance(const, (str, int, float, bool)):
            const_str = repr(const)[:200]
            print(f"  {i}: {const_str}")
        elif isinstance(const, tuple):
            print(f"  {i}: {repr(const)[:200]}")
    
    print("\nModule-level code disassembly:")
    dis.dis(code)
    
    print("\nClasses and functions:")
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            if const.co_name.startswith('class'):
                analyze_class(const, 1)
            else:
                analyze_code_object(const, 1)
                print()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_pyc_detailed(sys.argv[1])
    else:
        print("Usage: python analyze_pyc_detailed.py <pyc_file>")