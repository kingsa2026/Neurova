import marshal
import dis
import types
import sys
import os

def analyze_pyc(pyc_path):
    print(f"Analyzing: {pyc_path}")
    print("=" * 60)
    
    with open(pyc_path, 'rb') as f:
        # Skip magic number, flags, timestamp, size (16 bytes for Python 3.15)
        f.read(16)
        code = marshal.load(f)
    
    print("Module name:", code.co_name)
    print("File size:", os.path.getsize(pyc_path), "bytes")
    print("\nModule constants (strings, numbers):")
    for i, c in enumerate(code.co_consts):
        if isinstance(c, (str, int, float, bool)):
            if isinstance(c, str) and len(c) > 100:
                print(f"  {i}: '{c[:100]}...'")
            else:
                print(f"  {i}: {repr(c)}")
    
    print("\nModule names (imports, etc):")
    for i, name in enumerate(code.co_names):
        print(f"  {i}: {name}")
    
    print("\nDisassembly of module-level code:")
    dis.dis(code)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_pyc(sys.argv[1])
    else:
        print("Usage: python analyze_pyc.py <pyc_file>")