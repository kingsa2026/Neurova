#!/usr/bin/env python3
"""
创建 GitHub Release 脚本
使用方法：
1. 设置环境变量 GITHUB_TOKEN（GitHub Personal Access Token）
2. 运行脚本：python create_github_release.py
"""

import os
import sys
# 本档全程往终端念中文；cp936 控制台上不钉这一行，一句 print 就能把流程自己打断。
# 钉 stdout 是进程所有者的责任——被 import 的模块不各自钉（那会劫持导入方的流）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import requests
from datetime import datetime

# 配置
REPO_OWNER = "kingsa2020"
REPO_NAME = "Neurova"
# 版本事实源 = neurova/__init__.__version__（与 Chart.yaml 的 R4 同一口径）：
# 发布 tag 跟随代码版本，不再手写死值（fullrepo 审计 2026-11-18）。
from neurova import __version__ as _code_version  # noqa: E402

NEXT_VERSION = f"v{_code_version}"  # 发布版本（=当前代码版本）
REQUEST_TIMEOUT = (10, 30)  # 连接/读取均有界；发布写请求也不得无限等待。

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
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
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
        response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
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
        response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        print(f"✅ 引用创建成功: refs/tags/{tag_name}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ 创建引用失败: {e}")
        return False

def get_commit_message(token, commit_sha):
    """读取发布说明所需详情；失败必须阻止首次写入。"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{commit_sha}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()["commit"]["message"]
    except (requests.exceptions.RequestException, KeyError, TypeError) as e:
        print(f"❌ 获取提交详情失败: {e}")
        return None


def find_release(token, tag_name):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags/{tag_name}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ 对账发布失败: {e}")
        raise


def find_tag_and_ref(token, tag_name):
    """重跑先 GET 对账；返回 (tag_sha, ref_sha)，不存在则为 None。"""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    root = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    ref_sha = None
    tag_sha = None
    try:
        response = requests.get(f"{root}/git/ref/tags/{tag_name}", headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            return None, None
        response.raise_for_status()
        ref_sha = response.json()["object"]["sha"]
        response = requests.get(f"{root}/git/tags/{ref_sha}", headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        tag_sha = response.json()["sha"]
    except (requests.exceptions.RequestException, KeyError, TypeError) as e:
        print(f"❌ 对账标签/引用失败: {e}")
        raise
    return tag_sha, ref_sha


def rollback_release(token, tag_name, *, ref_sha=None, tag_sha=None):
    """仅清理本轮确认创建的资源；清理失败保持非零，留给下次 GET 对账。"""
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    root = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    targets = []
    if ref_sha:
        targets.append(f"{root}/git/refs/tags/{tag_name}")
    if tag_sha:
        targets.append(f"{root}/git/tags/{tag_sha}")
    clean = True
    for url in targets:
        try:
            response = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            clean = False
            print(f"❌ 回滚失败（下次运行将先对账）: {e}")
    return clean


def create_release(token, tag_name, commit_sha, commit_message=None):
    """创建发布；详情读取与状态校验先于唯一一次发布写入。"""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    if commit_message is None:
        commit_message = get_commit_message(token, commit_sha)
        if commit_message is None:
            return None

    release_notes = f"""## Neurova {tag_name}

### 更新内容
- {commit_message}

### 技术细节
- 提交: {commit_sha[:7]}
- 时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

### 安装
```bash
git clone https://github.com/{REPO_OWNER}/{REPO_NAME}.git
cd {REPO_NAME}
git checkout {tag_name}
pip install -r requirements-full.lock
```

### 文档
- [README.md](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/{tag_name}/README.md)
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
        response = requests.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
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
    
    # 2. 获取最新提交与详情（必须先于首次写入）
    print("\n1. 获取最新提交与详情...")
    commit_sha = get_latest_commit(token)
    if not commit_sha:
        return 1
    commit_message = get_commit_message(token, commit_sha)
    if commit_message is None:
        return 1
    
    # 3. 重跑先 GET 对账，已存在资源幂等复用
    created_tag_sha = None
    created_ref = False
    try:
        release = find_release(token, NEXT_VERSION)
        if release:
            print(f"✅ 复用已存在发布: {release['html_url']}")
            return 0
        tag_sha, ref_sha = find_tag_and_ref(token, NEXT_VERSION)
        if tag_sha and ref_sha:
            print(f"✅ 复用已存在标签/引用: {NEXT_VERSION}")
        else:
            if tag_sha:
                print(f"✅ 复用已存在标签对象: {tag_sha}")
            else:
                print(f"\n2. 创建标签 {NEXT_VERSION}...")
                tag_sha = create_tag(token, commit_sha, NEXT_VERSION)
                if not tag_sha:
                    return 1
                created_tag_sha = tag_sha
            print("\n3. 创建引用...")
            if not create_ref(token, NEXT_VERSION, tag_sha):
                rollback_release(token, NEXT_VERSION, tag_sha=created_tag_sha)
                return 1
            created_ref = True
    except (requests.exceptions.RequestException, KeyError, TypeError):
        return 1

    # 5. 创建发布
    print(f"\n4. 创建发布...")
    release = create_release(token, NEXT_VERSION, commit_sha, commit_message)
    if not release:
        rollback_release(token, NEXT_VERSION, ref_sha=created_ref or None, tag_sha=created_tag_sha)
        return 1
    
    print("\n" + "=" * 60)
    print("🎉 GitHub Release 创建成功！")
    print(f"版本: {NEXT_VERSION}")
    print(f"URL: {release['html_url']}")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())