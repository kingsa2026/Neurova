#!/usr/bin/env python3
"""
GitHub 自动提交和发布脚本
检查代码变更，提交到GitHub，并创建小版本发布
"""
import os
import sys
import subprocess
import json
import requests
from datetime import datetime
from pathlib import Path

class GitHubAutoRelease:
    """GitHub自动发布管理器"""
    
    def __init__(self, repo_path=".", owner="kingsa2026", repo="Neurova"):
        self.repo_path = Path(repo_path).resolve()
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Neurova-AutoRelease"
        }
    
    def run_git_command(self, command):
        """运行git命令"""
        try:
            result = subprocess.run(
                command,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                shell=True
            )
            return result.stdout.strip(), result.stderr.strip(), result.returncode
        except Exception as e:
            return "", str(e), 1
    
    def get_current_branch(self):
        """获取当前分支"""
        stdout, stderr, code = self.run_git_command(["git", "branch", "--show-current"])
        if code == 0:
            return stdout
        return None
    
    def get_latest_tag(self):
        """获取最新标签"""
        stdout, stderr, code = self.run_git_command(["git", "tag", "--sort=-v:refname", "--list", "v*"])
        if code == 0 and stdout:
            tags = stdout.split('\n')
            return tags[0] if tags[0] else None
        return None
    
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
    
    def check_changes(self):
        """检查代码变更"""
        print("=== 检查代码变更 ===")
        
        # 检查是否有未提交的更改
        stdout, stderr, code = self.run_git_command(["git", "status", "--porcelain"])
        if code != 0:
            print(f"错误: 无法获取git状态 - {stderr}")
            return False
        
        changes = stdout.strip()
        if not changes:
            print("没有未提交的更改")
            return False
        
        # 统计更改文件
        changed_files = [line.strip() for line in changes.split('\n') if line.strip()]
        print(f"发现 {len(changed_files)} 个文件有更改:")
        
        # 显示更改的文件
        for i, file in enumerate(changed_files[:10]):  # 只显示前10个
            status = file[:2]
            filename = file[3:]
            print(f"  {i+1}. [{status}] {filename}")
        
        if len(changed_files) > 10:
            print(f"  ... 还有 {len(changed_files) - 10} 个文件")
        
        return True
    
    def commit_changes(self, message=None):
        """提交更改"""
        print("\n=== 提交更改 ===")
        
        # 添加所有更改
        print("添加文件到暂存区...")
        stdout, stderr, code = self.run_git_command(["git", "add", "."])
        if code != 0:
            print(f"错误: 无法添加文件 - {stderr}")
            return False
        
        # 检查是否有暂存的更改
        stdout, stderr, code = self.run_git_command(["git", "diff", "--cached", "--name-only"])
        staged_files = [f for f in stdout.split('\n') if f.strip()]
        
        if not staged_files:
            print("没有暂存的更改")
            return False
        
        print(f"暂存了 {len(staged_files)} 个文件")
        
        # 生成提交信息
        if not message:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"auto: 代码更新 {timestamp}"
        
        # 提交更改
        print(f"提交信息: {message}")
        stdout, stderr, code = self.run_git_command(["git", "commit", "-m", message])
        
        if code != 0:
            print(f"错误: 提交失败 - {stderr}")
            return False
        
        # 获取提交哈希
        stdout, stderr, code = self.run_git_command(["git", "rev-parse", "HEAD"])
        commit_hash = stdout if code == 0 else "unknown"
        
        print(f"✅ 提交成功: {commit_hash[:8]}")
        return commit_hash
    
    def push_to_remote(self, branch=None):
        """推送到远程仓库"""
        print("\n=== 推送到远程仓库 ===")
        
        if not branch:
            branch = self.get_current_branch()
            if not branch:
                print("错误: 无法获取当前分支")
                return False
        
        # 推送到main分支
        print(f"推送到 origin/{branch}...")
        stdout, stderr, code = self.run_git_command(["git", "push", "origin", f"{branch}:main"])
        
        if code != 0:
            print(f"错误: 推送失败 - {stderr}")
            return False
        
        print(f"✅ 推送成功到 main 分支")
        return True
    
    def create_release(self, tag_name, release_notes=None):
        """创建GitHub Release"""
        print(f"\n=== 创建 GitHub Release: {tag_name} ===")
        
        if not self.token:
            print("错误: 未设置 GITHUB_TOKEN 环境变量")
            return False
        
        # 获取最新提交SHA
        stdout, stderr, code = self.run_git_command(["git", "rev-parse", "HEAD"])
        if code != 0:
            print(f"错误: 无法获取最新提交 - {stderr}")
            return False
        
        target_sha = stdout
        
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
- 文件更新: 自动检测
- 版本增量: 0.0.01"""
        
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
    
    def auto_release(self, commit_message=None, release_notes=None):
        """自动发布流程"""
        print("🚀 开始自动发布流程")
        print("=" * 50)
        
        # 检查是否有更改
        if not self.check_changes():
            print("没有需要发布的更改")
            return True
        
        # 获取当前版本和下一个版本
        current_tag = self.get_latest_tag()
        next_version = self.get_next_version(current_tag)
        
        print(f"\n当前版本: {current_tag or '无'}")
        print(f"下一个版本: {next_version}")
        
        # 提交更改
        commit_hash = self.commit_changes(commit_message)
        if not commit_hash:
            return False
        
        # 推送到远程
        if not self.push_to_remote():
            return False
        
        # 创建发布
        release_url = self.create_release(next_version, release_notes)
        if not release_url:
            return False
        
        print("\n" + "=" * 50)
        print("✅ 自动发布完成!")
        print(f"版本: {next_version}")
        print(f"提交: {commit_hash[:8]}")
        print(f"发布地址: {release_url}")
        
        return True

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="GitHub自动发布工具")
    parser.add_argument("--repo", default=".", help="仓库路径")
    parser.add_argument("--owner", default="kingsa2026", help="GitHub所有者")
    parser.add_argument("--repo-name", default="Neurova", help="仓库名称")
    parser.add_argument("--message", help="提交信息")
    parser.add_argument("--notes", help="发布说明")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行")
    
    args = parser.parse_args()
    
    # 创建发布管理器
    manager = GitHubAutoRelease(
        repo_path=args.repo,
        owner=args.owner,
        repo=args.repo_name
    )
    
    if args.dry_run:
        print("🔍 模拟运行模式")
        print("=" * 50)
        
        # 检查更改
        if manager.check_changes():
            current_tag = manager.get_latest_tag()
            next_version = manager.get_next_version(current_tag)
            
            print(f"\n当前版本: {current_tag or '无'}")
            print(f"下一个版本: {next_version}")
            print("\n将执行以下操作:")
            print("1. 添加所有更改到暂存区")
            print(f"2. 提交更改: {args.message or 'auto: 代码更新'}")
            print("3. 推送到 origin/main")
            print(f"4. 创建 GitHub Release: {next_version}")
        else:
            print("没有需要发布的更改")
        
        return
    
    # 执行自动发布
    success = manager.auto_release(
        commit_message=args.message,
        release_notes=args.notes
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()