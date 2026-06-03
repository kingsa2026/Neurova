"""
批量恢复脚本：扫描所有有 .pyc 但无 .py 的模块
"""
import os
import glob

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
NEUROVA_DIR = os.path.join(PROJECT_ROOT, "neurova")

def scan_missing():
    """扫描所有缺失的 .py 文件"""
    missing = []
    pyc_files = glob.glob(os.path.join(NEUROVA_DIR, "**", "__pycache__", "*.cpython-315.pyc"), recursive=True)
    
    for pyc_path in pyc_files:
        # 跳过 __pycache__ 本身
        parts = pyc_path.replace("\\", "/").split("/")
        if "__pycache__" in parts:
            cache_idx = parts.index("__pycache__")
            py_name = parts[cache_idx + 1].replace(".cpython-315.pyc", ".py")
            py_path = "/".join(parts[:cache_idx] + [py_name])
            
            if not os.path.exists(py_path):
                rel_py = os.path.relpath(py_path, PROJECT_ROOT).replace("\\", "/")
                size = os.path.getsize(pyc_path)
                missing.append({
                    'pyc': os.path.relpath(pyc_path, PROJECT_ROOT).replace("\\", "/"),
                    'py': rel_py,
                    'size': size,
                    'package': os.path.dirname(rel_py).replace("neurova/", "").replace("/", "."),
                })
    
    # 按大小排序（最大的可能是最复杂的）
    missing.sort(key=lambda x: -x['size'])
    return missing

if __name__ == "__main__":
    missing = scan_missing()
    print(f"Total missing .py files: {len(missing)}")
    print()
    
    # 按包分组
    by_package = {}
    for m in missing:
        pkg = m['package']
        if pkg not in by_package:
            by_package[pkg] = []
        by_package[pkg].append(m)
    
    for pkg, files in sorted(by_package.items(), key=lambda x: -len(x[1])):
        print(f"\n[{len(files)}] {pkg}")
        for f in files:
            print(f"  {f['py']} ({f['size']} bytes)")
