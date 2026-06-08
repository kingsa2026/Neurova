#!/usr/bin/env python3
"""
使用GitHub API创建v0.0.2版本发布
"""
import os
import requests
import json
import sys

def create_github_release():
    """创建GitHub Release"""
    
    # GitHub配置
    owner = "kingsa2026"
    repo = "Neurova"
    token = os.environ.get("GITHUB_TOKEN", "")
    
    # API端点
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    # 请求头
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Neurova-Automation"
    }
    
    # 目标提交SHA
    target_sha = "d25fde871840f6e9be64020ee570dfba72cee656"
    
    # 新版本信息
    tag_name = "v0.0.2"
    release_name = "v0.0.2"
    
    # 发布说明
    release_notes = """## v0.0.2 更新内容

### 🚀 新增功能
- **RSI 递归自改进系统**：实现完整的递归自我改进架构，包括编排器、收敛分析、回滚管理、指标面板、部署控制器
- **语音引擎增强**：语音管线、ASR模块、TTS模块完善
- **会话同步系统**：跨设备会话同步能力
- **记忆共享机制**：Agent间记忆共享与隔离

### 🔧 改进
- Agent管线优化与认知层记忆系统增强
- 前端API模块更新与架构文档完善
- LLM Router + Context Pool 模块实现
- 多模态路由系统修复
- 飞书/钉钉/企业微信渠道集成系统完成

### 📚 文档更新
- RSI架构文档完善
- TencentDB对比文档
- CONTEXT.md 上下文文档更新
- 递归自我改进系统架构文档

### 🐛 修复
- 记忆系统、元认知、进化模块、API更新
- 导入路径修复
- 向量存储模块修复
- 工具记忆闭环修复
- 情感闭环修复
- 经验闭环修复
- 睡眠闭环修复

### 📊 统计
- 自v0.0.1以来有10+次提交
- 涉及145+个文件更新
- 覆盖17个核心模块改进"""
    
    print(f"创建 GitHub Release: {tag_name}")
    print("=" * 50)
    
    # 步骤1: 创建tag对象
    print("1. 创建tag对象...")
    tag_url = f"{base_url}/git/tags"
    tag_data = {
        "tag": tag_name,
        "message": f"Release {tag_name}",
        "object": target_sha,
        "type": "commit",
        "tagger": {
            "name": "Neurova Automation",
            "email": "automation@neurova.dev",
            "date": "2026-06-08T11:17:00+00:00"
        }
    }
    
    try:
        response = requests.post(tag_url, headers=headers, json=tag_data)
        if response.status_code == 201:
            tag_info = response.json()
            print(f"   ✅ Tag对象创建成功: {tag_info['sha'][:8]}")
            tag_sha = tag_info['sha']
        elif response.status_code == 422:
            # Tag可能已存在
            print(f"   ⚠️ Tag可能已存在，尝试继续...")
            tag_sha = target_sha
        else:
            print(f"   ❌ 创建tag对象失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False
    
    # 步骤2: 创建tag引用
    print("2. 创建tag引用...")
    ref_url = f"{base_url}/git/refs"
    ref_data = {
        "ref": f"refs/tags/{tag_name}",
        "sha": tag_sha
    }
    
    try:
        response = requests.post(ref_url, headers=headers, json=ref_data)
        if response.status_code == 201:
            print(f"   ✅ Tag引用创建成功")
        elif response.status_code == 422:
            print(f"   ⚠️ Tag引用可能已存在，尝试继续...")
        else:
            print(f"   ❌ 创建tag引用失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False
    
    # 步骤3: 创建Release
    print("3. 创建Release...")
    release_url = f"{base_url}/releases"
    release_data = {
        "tag_name": tag_name,
        "name": release_name,
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
            return True
        else:
            print(f"   ❌ 创建Release失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False

if __name__ == "__main__":
    print("Neurova GitHub Release 创建工具")
    print("=" * 50)
    
    success = create_github_release()
    
    print("=" * 50)
    if success:
        print("✅ Release创建成功!")
        sys.exit(0)
    else:
        print("❌ Release创建失败!")
        sys.exit(1)