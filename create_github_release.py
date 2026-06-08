#!/usr/bin/env python3
"""
创建 GitHub Release 脚本
使用方法：
1. 设置环境变量 GITHUB_TOKEN（GitHub Personal Access Token）
2. 运行脚本：python create_github_release.py
"""

import os
import sys
import json
import requests
from datetime import datetime

# 配置
REPO_OWNER = "kingsa2026"
REPO_NAME = "Neurova"
CURRENT_VERSION = "v0.0.1"  # 当前版本
NEXT_VERSION = "v0.0.2"    # 下一个版本

def get_github_token():
    """获取 GitHub Token"""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("❌ 错误：未设置 GITHUB_TOKEN 环境变量")
        print("\n请按照以下步骤设置：")
        print("1. 访问 https://github.com/settings/tokens")
        print("2. 点击 'Generate new token (classic)'")
        print("3. 选择权限：repo（完整仓库访问权限）")
        print("4. 生成 token 并复制")
        print("5. 设置环境变量：")
        print("   Windows: set GITHUB_TOKEN=your_token_here")
        print("   Linux/Mac: export GITHUB_TOKEN=your_token_here")
        return None
    return token

def get_latest_commit(token):
    """获取最新提交"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits?per_page=1"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        commits = response.json()
        
        if not commits:
            print("❌ 未找到提交")
            return None
        
        latest_commit = commits[0]
        print(f"✅ 最新提交: {latest_commit['sha'][:7]}")
        print(f"   信息: {latest_commit['commit']['message']}")
        print(f"   时间: {latest_commit['commit']['committer']['date']}")
        
        return latest_commit['sha']
    except requests.exceptions.RequestException as e:
        print(f"❌ 获取提交失败: {e}")
        return None

def create_tag(token, commit_sha, tag_name):
    """创建标签"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/tags"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    data = {
        "tag": tag_name,
        "message": f"Release {tag_name}",
        "object": commit_sha,
        "type": "commit",
        "tagger": {
            "name": "Neurova Bot",
            "email": "bot@neurova.com",
            "date": datetime.utcnow().isoformat() + "Z"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        tag_data = response.json()
        print(f"✅ 标签创建成功: {tag_name}")
        return tag_data['sha']
    except requests.exceptions.RequestException as e:
        print(f"❌ 创建标签失败: {e}")
        return None

def create_ref(token, tag_name, tag_sha):
    """创建引用（将标签推送到仓库）"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/refs"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    data = {
        "ref": f"refs/tags/{tag_name}",
        "sha": tag_sha
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        print(f"✅ 引用创建成功: refs/tags/{tag_name}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ 创建引用失败: {e}")
        return False

def create_release(token, tag_name, commit_sha):
    """创建发布"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 获取提交信息用于发布说明
    commit_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{commit_sha}"
    commit_response = requests.get(commit_url, headers=headers)
    commit_data = commit_response.json() if commit_response.status_code == 200 else {}
    
    release_notes = f"""## Neurova {tag_name}

### 更新内容
- {commit_data.get('commit', {}).get('message', '代码更新和改进')}

### 技术细节
- 提交: {commit_sha[:7]}
- 时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

### 安装
```bash
git clone https://github.com/{REPO_OWNER}/{REPO_NAME}.git
cd {REPO_NAME}
git checkout {tag_name}
pip install -r requirements.txt
```

### 文档
- [README.md](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{tag_name}/README.md)
- [CONTEXT.md](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{tag_name}/CONTEXT.md)
"""
    
    data = {
        "tag_name": tag_name,
        "target_commitish": commit_sha,
        "name": f"Neurova {tag_name}",
        "body": release_notes,
        "draft": False,
        "prerelease": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        release_data = response.json()
        print(f"✅ 发布创建成功!")
        print(f"   版本: {tag_name}")
        print(f"   URL: {release_data['html_url']}")
        return release_data
    except requests.exceptions.RequestException as e:
        print(f"❌ 创建发布失败: {e}")
        return None

def main():
    print("=" * 60)
    print("GitHub Release 创建工具")
    print("=" * 60)
    
    # 1. 获取 token
    token = get_github_token()
    if not token:
        return 1
    
    # 2. 获取最新提交
    print("\n1. 获取最新提交...")
    commit_sha = get_latest_commit(token)
    if not commit_sha:
        return 1
    
    # 3. 创建标签
    print(f"\n2. 创建标签 {NEXT_VERSION}...")
    tag_sha = create_tag(token, commit_sha, NEXT_VERSION)
    if not tag_sha:
        return 1
    
    # 4. 创建引用
    print(f"\n3. 创建引用...")
    if not create_ref(token, NEXT_VERSION, tag_sha):
        return 1
    
    # 5. 创建发布
    print(f"\n4. 创建发布...")
    release = create_release(token, NEXT_VERSION, commit_sha)
    if not release:
        return 1
    
    print("\n" + "=" * 60)
    print("🎉 GitHub Release 创建成功！")
    print(f"版本: {NEXT_VERSION}")
    print(f"URL: {release['html_url']}")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())