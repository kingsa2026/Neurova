import marshal
import types
import os
import sys

def analyze_pyc(pyc_path):
    """分析 pyc 文件，提取类和函数结构"""
    with open(pyc_path, 'rb') as f:
        f.read(16)
        code = marshal.load(f)
    
    result = {
        'name': code.co_name,
        'file': code.co_filename,
        'size': os.path.getsize(pyc_path),
        'imports': list(code.co_names),
        'constants': [],
        'classes': [],
        'functions': [],
    }
    
    for i, const in enumerate(code.co_consts):
        if isinstance(const, (str, int, float, bool, tuple)):
            result['constants'].append((i, repr(const)[:200]))
        elif isinstance(const, types.CodeType):
            # Determine if it's a class or function
            if any(c == const for c in code.co_consts if isinstance(c, types.CodeType)):
                # Check if it has 'class' in its name or is defined with LOAD_BUILD_CLASS
                result['classes'].append({
                    'name': const.co_name,
                    'line': const.co_firstlineno,
                    'args': const.co_varnames[:const.co_argcount],
                    'names': list(const.co_names),
                    'constants': [repr(c)[:100] for c in const.co_consts if isinstance(c, (str, int, float, bool))],
                    'sub_codes': [{
                        'name': sc.co_name,
                        'line': sc.co_firstlineno,
                        'args': sc.co_varnames[:sc.co_argcount],
                        'names': list(sc.co_names),
                    } for sc in const.co_consts if isinstance(sc, types.CodeType)],
                })
    
    return result

if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(f"\n{'='*60}")
        info = analyze_pyc(path)
        print(f"File: {path}")
        print(f"Size: {info['size']} bytes")
        print(f"Names: {info['imports']}")
        print(f"Classes/Functions:")
        for cls in info['classes']:
            print(f"  {cls['name']} (line {cls['line']})")
            print(f"    args: {cls['args']}")
            print(f"    names: {cls['names'][:20]}")
            print(f"    constants: {cls['constants'][:10]}")
            for sub in cls['sub_codes']:
                print(f"    -> {sub['name']}(line {sub['line']}) args={sub['args'][:5]} names={sub['names'][:10]}")