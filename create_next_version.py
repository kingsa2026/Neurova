#!/usr/bin/env python3
"""
创建下一个版本发布
基于当前版本创建v0.0.2发布
"""
import os
import requests
import json
from datetime import datetime

def create_next_version():
    """创建下一个版本"""
    print("=== 创建下一个版本发布 ===")
    
    # 仓库信息
    owner = "kingsa2026"
    repo = "Neurova"
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    # 获取最新标签
    print("1. 获取最新标签...")
    try:
        response = requests.get(f"{base_url}/tags")
        if response.status_code == 200:
            tags = response.json()
            if tags:
                current_tag = tags[0]['name']
                print(f"   当前版本: {current_tag}")
                
                # 计算下一个版本
                if current_tag.startswith('v'):
                    version_parts = current_tag[1:].split('.')
                    if len(version_parts) >= 3:
                        try:
                            major = int(version_parts[0])
                            minor = int(version_parts[1])
                            patch = int(version_parts[2])
                            next_patch = patch + 1
                            next_version = f"v{major}.{minor}.{next_patch}"
                            print(f"   下一个版本: {next_version}")
                        except:
                            print("   错误: 无法解析版本号")
                            return False
            else:
                print("   没有标签，将创建 v0.0.1")
                next_version = "v0.0.1"
        else:
            print(f"   获取标签失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"   异常: {e}")
        return False
    
    # 获取最新提交
    print("\n2. 获取最新提交...")
    try:
        response = requests.get(f"{base_url}/commits?per_page=1")
        if response.status_code == 200:
            commits = response.json()
            if commits:
                latest_commit = commits[0]
                commit_sha = latest_commit['sha']
                commit_message = latest_commit['commit']['message']
                commit_date = latest_commit['commit']['committer']['date']
                
                print(f"   提交SHA: {commit_sha[:8]}")
                print(f"   提交信息: {commit_message[:50]}...")
                print(f"   提交时间: {commit_date}")
            else:
                print("   没有提交")
                return False
        else:
            print(f"   获取提交失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"   异常: {e}")
        return False
    
    # 创建发布说明
    print("\n3. 生成发布说明...")
    release_notes = f"""## {next_version} 更新内容

### 自动发布
- 基于最新提交自动创建的小版本发布
- 提交时间: {commit_date}
- 提交SHA: {commit_sha[:8]}
- 提交信息: {commit_message}

### 变更统计
- 版本增量: 0.0.01
- 从 {current_tag} 升级到 {next_version}

### 功能更新
- 根据最新提交内容自动更新
- 详见提交记录获取详细变更"""
    
    print(f"   发布说明已生成 ({len(release_notes)} 字符)")
    
    # 注意：由于没有GitHub Token，无法实际创建发布
    # 这里只是模拟过程
    print("\n=== 发布创建模拟 ===")
    print(f"版本: {next_version}")
    print(f"提交: {commit_sha[:8]}")
    print(f"发布时间: {datetime.now().isoformat()}")
    
    print("\n⚠️ 注意: 由于没有设置GITHUB_TOKEN，无法实际创建发布")
    print("要实际创建发布，请:")
    print("1. 设置环境变量 GITHUB_TOKEN")
    print("2. 运行完整的发布脚本")
    
    return True

if __name__ == "__main__":
    create_next_version()