#!/usr/bin/env python3
"""统计骨架文件数量"""
import os
import sys

def count_skeleton_files(root_dir):
    """统计包含TODO: Auto-restored from .pyc的文件"""
    count = 0
    skeleton_files = []
    
    for root, dirs, files in os.walk(root_dir):
        # 跳过一些目录
        skip_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'TODO: Auto-restored from .pyc, needs implementation' in content:
                            count += 1
                            skeleton_files.append(file_path)
                except:
                    pass
    
    return count, skeleton_files

if __name__ == "__main__":
    root_dir = r"e:\项目\Neurova\neurova"
    count, files = count_skeleton_files(root_dir)
    print(f"找到 {count} 个骨架文件:")
    for file in files:
        print(f"  {file}")