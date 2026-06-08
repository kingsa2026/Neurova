#!/usr/bin/env python3
"""
GitHub 操作脚本
检查代码变更，提交并创建新版本
"""
import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

class GitHubOperations:
    """GitHub 操作类"""
    
    def __init__(self, owner="kingsa2026", repo="Neurova"):
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Neurova-Automation"
        }
    
    def get_latest_tag(self):
        """获取最新标签"""
        url = f"{self.base_url}/tags"
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                tags = response.json()
                if tags:
                    return tags[0]['name']
        except Exception as e:
            print(f"获取标签失败: {e}")
        return None
    
    def get_latest_commits(self, count=5):
        """获取最新提交"""
        url = f"{self.base_url}/commits?per_page={count}"
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取提交失败: {e}")
        return []
    
    def parse_version(self, tag):
        """解析版本号"""
        if not tag or not tag.startswith('v'):
            return None, None, None
        
        version_str = tag[1:]
        parts = version_str.split('.')
        
        if len(parts) >= 3:
            try:
                major = int(parts[0])
                minor = int(parts[1])
                patch = int(parts[2])
                return major, minor, patch
            except ValueError:
                pass
        
        return None, None, None
    
    def get_next_version(self, current_tag):
        """获取下一个版本号（增加0.0.01）"""
        major, minor, patch = self.parse_version(current_tag)
        
        if major is None:
            # 默认从v0.0.1开始
            return "v0.0.1"
        
        # 增加0.0.01（即patch+1）
        next_patch = patch + 1
        return f"v{major}.{minor}.{next_patch}"
    
    def create_release(self, tag_name, target_sha, release_notes=None):
        """创建GitHub Release"""
        print(f"\n=== 创建 GitHub Release: {tag_name} ===")
        
        if not self.token:
            print("错误: 未设置 GITHUB_TOKEN 环境变量")
            return False
        
        # 创建标签
        print("创建标签...")
        tag_url = f"{self.base_url}/git/tags"
        tag_data = {
            "tag": tag_name,
            "message": f"Release {tag_name}",
            "object": target_sha,
            "type": "commit",
            "tagger": {
                "name": "Neurova Automation",
                "email": "automation@neurova.dev",
                "date": datetime.now().isoformat() + "Z"
            }
        }
        
        try:
            response = requests.post(tag_url, headers=self.headers, json=tag_data)
            if response.status_code == 201:
                tag_info = response.json()
                print(f"✅ 标签创建成功: {tag_info['sha'][:8]}")
                tag_sha = tag_info['sha']
            elif response.status_code == 422:
                print("⚠️ 标签可能已存在，继续...")
                tag_sha = target_sha
            else:
                print(f"❌ 创建标签失败: {response.status_code}")
                print(f"响应: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 异常: {e}")
            return False
        
        # 创建标签引用
        print("创建标签引用...")
        ref_url = f"{self.base_url}/git/refs"
        ref_data = {
            "ref": f"refs/tags/{tag_name}",
            "sha": tag_sha
        }
        
        try:
            response = requests.post(ref_url, headers=self.headers, json=ref_data)
            if response.status_code == 201:
                print("✅ 标签引用创建成功")
            elif response.status_code == 422:
                print("⚠️ 标签引用可能已存在，继续...")
            else:
                print(f"❌ 创建标签引用失败: {response.status_code}")
                print(f"响应: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 异常: {e}")
            return False
        
        # 生成发布说明
        if not release_notes:
            release_notes = f"""## {tag_name} 更新内容

### 自动发布
- 自动生成的小版本发布
- 提交时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
- 提交SHA: {target_sha[:8]}

### 变更统计
- 版本增量: 0.0.01
- 基于最新提交自动创建"""
        
        # 创建Release
        print("创建Release...")
        release_url = f"{self.base_url}/releases"
        release_data = {
            "tag_name": tag_name,
            "name": tag_name,
            "body": release_notes,
            "draft": False,
            "prerelease": False,
            "target_commitish": "main"
        }
        
        try:
            response = requests.post(release_url, headers=self.headers, json=release_data)
            if response.status_code == 201:
                release_info = response.json()
                print(f"✅ Release创建成功!")
                print(f"   名称: {release_info['name']}")
                print(f"   URL: {release_info['html_url']}")
                print(f"   发布时间: {release_info['published_at']}")
                return release_info['html_url']
            else:
                print(f"❌ 创建Release失败: {response.status_code}")
                print(f"响应: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 异常: {e}")
            return False
    
    def check_and_create_release(self):
        """检查并创建新版本"""
        print("🚀 GitHub 版本管理")
        print("=" * 50)
        
        # 获取最新标签
        current_tag = self.get_latest_tag()
        print(f"当前版本: {current_tag or '无'}")
        
        # 获取最新提交
        commits = self.get_latest_commits(1)
        if not commits:
            print("❌ 无法获取最新提交")
            return False
        
        latest_commit = commits[0]
        commit_sha = latest_commit['sha']
        commit_message = latest_commit['commit']['message']
        commit_date = latest_commit['commit']['committer']['date']
        
        print(f"最新提交: {commit_sha[:8]}")
        print(f"提交信息: {commit_message}")
        print(f"提交时间: {commit_date}")
        
        # 计算下一个版本
        next_version = self.get_next_version(current_tag)
        print(f"下一个版本: {next_version}")
        
        # 检查是否需要创建新版本
        if current_tag == next_version:
            print("⚠️ 版本号相同，跳过创建")
            return True
        
        # 创建发布
        release_url = self.create_release(
            tag_name=next_version,
            target_sha=commit_sha,
            release_notes=f"""## {next_version} 更新内容

### 自动发布
- 基于最新提交自动创建的小版本发布
- 提交时间: {commit_date}
- 提交SHA: {commit_sha[:8]}
- 提交信息: {commit_message}

### 变更统计
- 版本增量: 0.0.01
- 从 {current_tag or '无'} 升级到 {next_version}"""
        )
        
        if release_url:
            print("\n" + "=" * 50)
            print("✅ 版本创建完成!")
            print(f"版本: {next_version}")
            print(f"发布地址: {release_url}")
            return True
        
        return False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="GitHub版本管理工具")
    parser.add_argument("--owner", default="kingsa2026", help="GitHub所有者")
    parser.add_argument("--repo", default="Neurova", help="仓库名称")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行")
    
    args = parser.parse_args()
    
    # 创建操作类
    ops = GitHubOperations(
        owner=args.owner,
        repo=args.repo
    )
    
    if args.dry_run:
        print("🔍 模拟运行模式")
        print("=" * 50)
        
        # 获取最新标签
        current_tag = ops.get_latest_tag()
        next_version = ops.get_next_version(current_tag)
        
        print(f"当前版本: {current_tag or '无'}")
        print(f"下一个版本: {next_version}")
        
        # 获取最新提交
        commits = ops.get_latest_commits(1)
        if commits:
            latest_commit = commits[0]
            print(f"最新提交: {latest_commit['sha'][:8]}")
            print(f"提交信息: {latest_commit['commit']['message']}")
        
        print("\n将执行以下操作:")
        print(f"1. 创建标签: {next_version}")
        print(f"2. 创建 GitHub Release: {next_version}")
        
        return
    
    # 执行版本创建
    success = ops.check_and_create_release()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()