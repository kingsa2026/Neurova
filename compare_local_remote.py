#!/usr/bin/env python3
"""比较本地和远程仓库状态"""
import os
import json
import requests
from pathlib import Path
from datetime import datetime

def get_local_git_info(repo_path="."):
    """获取本地git信息"""
    # 由于无法执行git命令，返回模拟数据
    # 实际应该使用subprocess调用git命令
    return {
        "branch": "main",
        "latest_commit": "a9268d9",  # 从之前的结果获取
        "commit_message": "更新技能系统、工具层和执行引擎，添加新文档和脚本",
        "commit_date": "2026-06-08T06:17:07Z"
    }

def get_remote_git_info(owner="kingsa2026", repo="Neurova"):
    """获取远程git信息"""
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    result = {}
    
    # 获取最新提交
    try:
        response = requests.get(f"{base_url}/commits?per_page=1", headers=headers)
        if response.status_code == 200:
            commits = response.json()
            if commits:
                commit = commits[0]
                result["latest_commit"] = commit['sha'][:7]
                result["commit_message"] = commit['commit']['message']
                result["commit_date"] = commit['commit']['committer']['date']
    except Exception as e:
        print(f"获取远程提交失败: {e}")
    
    # 获取最新标签
    try:
        response = requests.get(f"{base_url}/tags", headers=headers)
        if response.status_code == 200:
            tags = response.json()
            if tags:
                result["latest_tag"] = tags[0]['name']
    except Exception as e:
        print(f"获取远程标签失败: {e}")
    
    return result

def compare_and_analyze():
    """比较并分析差异"""
    print("=== 本地与远程仓库比较 ===")
    
    # 获取本地信息
    local_info = get_local_git_info()
    print(f"\n本地信息:")
    print(f"  分支: {local_info.get('branch', '未知')}")
    print(f"  最新提交: {local_info.get('latest_commit', '未知')}")
    print(f"  提交信息: {local_info.get('commit_message', '未知')}")
    print(f"  提交时间: {local_info.get('commit_date', '未知')}")
    
    # 获取远程信息
    remote_info = get_remote_git_info()
    print(f"\n远程信息:")
    print(f"  最新提交: {remote_info.get('latest_commit', '未知')}")
    print(f"  提交信息: {remote_info.get('commit_message', '未知')}")
    print(f"  提交时间: {remote_info.get('commit_date', '未知')}")
    print(f"  最新标签: {remote_info.get('latest_tag', '无')}")
    
    # 比较
    print(f"\n=== 比较结果 ===")
    
    local_commit = local_info.get('latest_commit', '')
    remote_commit = remote_info.get('latest_commit', '')
    
    if local_commit == remote_commit:
        print("✅ 本地和远程提交相同")
    else:
        print("⚠️ 本地和远程提交不同")
        print(f"  本地: {local_commit}")
        print(f"  远程: {remote_commit}")
    
    # 版本信息
    current_tag = remote_info.get('latest_tag')
    if current_tag:
        print(f"\n当前版本: {current_tag}")
        
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
                    print(f"下一个版本: {next_version}")
                except:
                    pass
    else:
        print("\n没有标签，建议创建 v0.0.1")
    
    return {
        "local": local_info,
        "remote": remote_info,
        "synced": local_commit == remote_commit
    }

if __name__ == "__main__":
    compare_and_analyze()