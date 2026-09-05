#!/usr/bin/env python3
"""
从Istanbul覆盖率HTML文件中提取原始源代码
"""
import re
import os
from pathlib import Path

def extract_source_from_html(html_file):
    """从HTML文件中提取源代码"""
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 匹配 <pre class="prettyprint lang-js"> 到 </pre> 之间的内容
    pattern = r'<pre class="prettyprint lang-js">(.*?)</pre>'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        # 尝试其他模式
        pattern = r'<pre class="prettyprint lang-(?:js|ts)">(.*?)</pre>'
        match = re.search(pattern, content, re.DOTALL)
    
    if match:
        code = match.group(1)
        # 移除HTML标签和覆盖率标记
        # 移除 <span> 标签
        code = re.sub(r'<span[^>]*>', '', code)
        code = re.sub(r'</span>', '', code)
        # 移除覆盖率标记如 "cstat-no", "cline-any" 等
        code = re.sub(r'class="[^"]*"', '', code)
        # 移除多余空白
        code = re.sub(r'\n\s*\n', '\n', code)
        return code.strip()
    return None

def process_coverage_directory(coverage_dir, output_dir):
    """处理整个覆盖率目录"""
    coverage_path = Path(coverage_dir)
    output_path = Path(output_dir)
    
    # 遍历所有HTML文件
    for html_file in coverage_path.rglob('*.html'):
        if html_file.name == 'index.html':
            continue  # 跳过目录汇总页
        
        # 获取相对路径
        rel_path = html_file.relative_to(coverage_path)
        
        # 转换文件名：xxx.vue.html -> xxx.vue, xxx.ts.html -> xxx.ts
        if rel_path.name.endswith('.vue.html'):
            target_name = rel_path.name[:-5]  # 移除 .html，保留 .vue
        elif rel_path.name.endswith('.ts.html'):
            target_name = rel_path.name[:-5]  # 移除 .html，保留 .ts
        else:
            continue
        
        # 构建目标路径 - 注意：rel_path已经包含了src/前缀
        # 我们需要去掉第一级目录（neuUI/src/）
        parts = rel_path.parts
        if len(parts) > 1 and parts[0] == 'src':
            # 跳过第一个'src'目录，避免重复
            target_path = output_path / Path(*parts[1:-1]) / target_name
        else:
            target_path = output_path / rel_path.parent / target_name
        
        # 提取源代码
        source_code = extract_source_from_html(html_file)
        if source_code:
            # 创建目标目录
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
            except FileExistsError:
                # 目录已存在，忽略
                pass
            
            # 写入文件
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(source_code)
            
            print(f"恢复: {rel_path} -> {target_path}")

if __name__ == '__main__':
    coverage_dir = 'coverage/neuUI'
    output_dir = 'src'
    process_coverage_directory(coverage_dir, output_dir)
    print("完成！")