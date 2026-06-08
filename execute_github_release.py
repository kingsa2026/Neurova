#!/usr/bin/env python3
"""
执行GitHub版本发布
创建v0.0.2版本
"""
import os
import sys
import requests
import json
from datetime import datetime

def main():
    """主函数"""
    print("🚀 开始执行GitHub版本发布")
    print("=" * 50)
    
    # 设置GitHub token
    # 使用connect_cloud_service获取的token
    github_token = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJteWZFenA3ODNLaV9KQ3g4Vm5jM1hfaXg2alpyYjZDZjVPTWtHWk1QSTNzIn0.eyJleHAiOjE4MTA5NzY4MjAsImlhdCI6MTc4MDg2NDAzMCwiYXV0aF90aW1lIjoxNzc5NDQwODIwLCJqdGkiOiJkMWYzNDU5Ny1jODY3LTQxYTItOTcxOC0yZDU0ODA0OTM2MzgiLCJpc3MiOiJodHRwczovL3d3dy5jb2RlYnVkZHkuY24vYXV0aC9yZWFsbXMvY29waWxvdCIsImF1ZCI6ImFjY291bnQiLCJzdWIiOiJhMWQzMDg5YS05ZGNlLTRmZDYtODlmNS0yOTJhZGJhOWNkY2YiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJjb25zb2xlIiwic2lkIjoiZjliMDlkZjktYWU3Zi00NTEwLTkwNmEtYjViZTA3ZGJjZjc4IiwiYWNyIjoiMCIsImFsbG93ZWQtb3JpZ2lucyI6WyIqIl0sInJlYWxtX2FjY2VzcyI6eyJyb2xlcyI6WyJkZWZhdWx0LXJvbGVzIiwib2ZmbGluZV9hY2Nlc3MiLCJ1bWFfYXV0aG9yaXphdGlvbiJdfSwicmVzb3VyY2VfYWNjZXNzIjp7ImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoib3BlbmlkIHByb2ZpbGUgb2ZmbGluZV9hY2Nlc3MgZW1haWwiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsIm5pY2tuYW1lIjoiRGlyLuafmuWtkOWFiOajrtmH2aUiLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiIxNjYzODY2NjYxOSJ9.VPJj5FJYHR65dQI5n28luoovp_Hk4-4rHzC5cUGMrALQpl0yRpYiPkGW_U2C2pJybhyhHLP7UGHdxnxv4c9FLoIHJCsHgHvAEGHZwM0Kd-M9QwuUnYAuvCj18Fec1rDY0rWH-j-zz7cMMBZdfNhKcOoy5V7wymmcknuuONe9w4itDzDLT-One7zof_jnmRsiF5buj4_NRWEfFdS5ASfixZIPbtRnxA2Ls1lcVVgw51RAC6zbUqKZB1lR2uClycfxONipmP4rWc0I1yzID9UKwJcDC0smS8twjWz618fbgA7F7mzpT9PAnXpVjYxe5sp1dC9ZoJTSoOxhNuRLjETfHg"
    
    # 设置环境变量
    os.environ["GITHUB_TOKEN"] = github_token
    
    # 仓库信息
    owner = "kingsa2026"
    repo = "Neurova"
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    # 请求头
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Neurova-AutoRelease"
    }
    
    # 步骤1: 获取最新标签
    print("1. 获取最新标签...")
    try:
        response = requests.get(f"{base_url}/tags", headers=headers)
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
    
    # 步骤2: 获取最新提交
    print("\n2. 获取最新提交...")
    try:
        response = requests.get(f"{base_url}/commits?per_page=1", headers=headers)
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
    
    # 步骤3: 创建标签
    print("\n3. 创建标签...")
    tag_url = f"{base_url}/git/tags"
    tag_data = {
        "tag": next_version,
        "message": f"Release {next_version}",
        "object": commit_sha,
        "type": "commit",
        "tagger": {
            "name": "Neurova Automation",
            "email": "automation@neurova.dev",
            "date": datetime.now().isoformat() + "Z"
        }
    }
    
    try:
        response = requests.post(tag_url, headers=headers, json=tag_data)
        if response.status_code == 201:
            tag_info = response.json()
            print(f"   ✅ 标签创建成功: {tag_info['sha'][:8]}")
            tag_sha = tag_info['sha']
        elif response.status_code == 422:
            print("   ⚠️ 标签可能已存在，继续...")
            tag_sha = commit_sha
        else:
            print(f"   ❌ 创建标签失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False
    
    # 步骤4: 创建标签引用
    print("\n4. 创建标签引用...")
    ref_url = f"{base_url}/git/refs"
    ref_data = {
        "ref": f"refs/tags/{next_version}",
        "sha": tag_sha
    }
    
    try:
        response = requests.post(ref_url, headers=headers, json=ref_data)
        if response.status_code == 201:
            print("   ✅ 标签引用创建成功")
        elif response.status_code == 422:
            print("   ⚠️ 标签引用可能已存在，继续...")
        else:
            print(f"   ❌ 创建标签引用失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False
    
    # 步骤5: 创建Release
    print("\n5. 创建Release...")
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
    
    release_url = f"{base_url}/releases"
    release_data = {
        "tag_name": next_version,
        "name": next_version,
        "body": release_notes,
        "draft": False,
        "prerelease": False,
        "target_commitish": "main"
    }
    
    try:
        response = requests.post(release_url, headers=headers, json=release_data)
        if response.status_code == 201:
            release_info = response.json()
            print(f"   ✅ Release创建成功!")
            print(f"   名称: {release_info['name']}")
            print(f"   URL: {release_info['html_url']}")
            print(f"   发布时间: {release_info['published_at']}")
            
            print("\n" + "=" * 50)
            print("✅ 版本发布完成!")
            print(f"版本: {next_version}")
            print(f"发布地址: {release_info['html_url']}")
            
            return True
        else:
            print(f"   ❌ 创建Release失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)