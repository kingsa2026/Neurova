# Neurova GitHub Push Skill 使用指南

## 概述

Neurova GitHub Push Skill 是一个封装完整 Git 操作流程的技能，支持：
- 检查 Git 状态
- 添加文件到暂存区
- 提交更改
- 推送到远程仓库（支持直接推送到 main 分支）

## 安装

技能已内置在 Neurova 系统中，无需额外安装。

## 基本用法

### 1. 作为技能系统的一部分使用

```python
from neurova.skill_system import create_default_skills

# 创建默认技能注册表
registry = create_default_skills()

# 获取 GitHub Push 技能
skill = registry.get_skill("github_push")

# 执行操作
result = await skill.execute({
    "action": "full_push",
    "message": "添加新功能",
    "push_to_main": True
})
```

### 2. 直接导入使用

```python
from neurova.skills.builtin.github_push import GitHubPushSkill, create_github_push_skill

# 创建技能实例
skill = create_github_push_skill()

# 设置仓库路径（可选）
skill.repo_path = "/path/to/your/repo"

# 执行操作
result = await skill.execute({
    "action": "status"
})
```

### 3. 使用便捷函数

```python
from neurova.skills.builtin.github_push import push_to_github

# 一键推送到 GitHub
result = await push_to_github(
    message="更新代码",
    push_to_main=True,
    repo_path="."
)
```

## 操作类型

### 1. `status` - 获取状态

```python
result = await skill.execute({"action": "status"})
# 返回:
# {
#   "files": [{"status": "M", "file": "test.txt"}],
#   "total_files": 1,
#   "clean": false
# }
```

### 2. `add` - 添加文件

```python
# 添加所有文件
result = await skill.execute({"action": "add"})

# 添加指定文件
result = await skill.execute({
    "action": "add",
    "files": ["file1.py", "file2.py"]
})
```

### 3. `commit` - 提交更改

```python
result = await skill.execute({
    "action": "commit",
    "message": "修复 bug #123"
})
# 返回:
# {
#   "commit_hash": "abc123...",
#   "message": "修复 bug #123",
#   "files_committed": 1,
#   "files": ["test.txt"]
# }
```

### 4. `push` - 推送更改

```python
# 推送到当前分支
result = await skill.execute({"action": "push"})

# 直接推送到 main 分支
result = await skill.execute({
    "action": "push",
    "push_to_main": True
})
```

### 5. `full_push` - 完整工作流

```python
result = await skill.execute({
    "action": "full_push",
    "message": "实现新功能",
    "push_to_main": True
})
# 返回:
# {
#   "message": "完整推送工作流成功完成",
#   "commit_hash": "abc123...",
#   "pushed_to": "main",
#   "files_committed": 3
# }
```

## 参数说明

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `action` | string | 否 | `"full_push"` | 操作类型 |
| `message` | string | 否 | `"Update from Neurova GitHub Push Skill"` | 提交信息 |
| `files` | array | 否 | `None` | 要添加的文件列表 |
| `push_to_main` | boolean | 否 | `True` | 是否推送到 main 分支 |
| `branch` | string | 否 | `None` | 指定分支 |
| `repo_path` | string | 否 | `"."` | 仓库路径 |

## 工作流程

### 完整推送工作流 (`full_push`)

1. **检查状态**: `git status --porcelain`
2. **添加文件**: `git add .`
3. **提交更改**: `git commit -m "message"`
4. **推送更改**: `git push origin <branch>:main`

### 直接推送到 main 分支

当 `push_to_main=True` 且当前分支不是 `main` 时，技能会执行：
```bash
git push origin <current-branch>:main
```

这允许直接从功能分支推送到 main 分支，而无需合并操作。

## 错误处理

### 常见错误

1. **工作区干净**: 如果没有更改，跳过添加和提交步骤
2. **暂存区为空**: 如果没有暂存的更改，提交操作会失败
3. **远程仓库未配置**: 如果没有配置远程仓库，推送操作会失败
4. **Git 命令失败**: 任何 Git 命令失败都会返回详细的错误信息

### 错误处理示例

```python
result = await skill.execute({"action": "full_push"})

if not result.success:
    print(f"操作失败: {result.error}")
    # 根据错误类型进行处理
    if "远程仓库未配置" in result.error:
        # 配置远程仓库
        pass
```

## 使用场景

### 场景 1: 日常开发推送

```python
# 检查状态
status = await skill.execute({"action": "status"})
if not status.data["clean"]:
    # 完整推送
    result = await skill.execute({
        "action": "full_push",
        "message": "日常开发更新"
    })
```

### 场景 2: 紧急修复推送

```python
# 直接推送到 main 分支
result = await skill.execute({
    "action": "full_push",
    "message": "紧急修复: 登录问题",
    "push_to_main": True
})
```

### 场景 3: 仅提交不推送

```python
# 添加文件
await skill.execute({"action": "add"})

# 提交更改
result = await skill.execute({
    "action": "commit",
    "message": "本地保存"
})

# 之后手动推送
```

## 高级用法

### 自定义仓库路径

```python
skill.repo_path = "/path/to/specific/repo"
result = await skill.execute({"action": "status"})
```

### 指定分支推送

```python
result = await skill.execute({
    "action": "push",
    "branch": "feature/new-feature",
    "push_to_main": False
})
```

### 批量文件操作

```python
# 添加多个文件
result = await skill.execute({
    "action": "add",
    "files": [
        "src/main.py",
        "tests/test_main.py",
        "README.md"
    ]
})
```

## 技术细节

### 异步执行

技能使用 `asyncio.create_subprocess_exec` 异步执行 Git 命令，不会阻塞主线程。

### 跨平台支持

技能支持 Windows 和 Unix 系统，自动处理路径分隔符和命令差异。

### 日志记录

技能使用 Python logging 模块记录所有操作，便于调试：

```python
import logging
logging.getLogger("neurova.skills.builtin.github_push").setLevel(logging.DEBUG)
```

## 注意事项

1. **权限要求**: 确保有 Git 仓库的读写权限
2. **远程仓库**: 需要配置远程仓库（`git remote add origin <url>`）
3. **分支保护**: 如果 main 分支有保护规则，可能需要特殊权限
4. **网络连接**: 推送操作需要网络连接
5. **Git 配置**: 确保 Git 已配置用户名和邮箱

## 故障排除

### 问题 1: 导入错误

```python
# 如果遇到导入错误，尝试：
import sys
sys.path.insert(0, "/path/to/neurova")
```

### 问题 2: Git 命令找不到

确保系统已安装 Git 并在 PATH 中：
```bash
git --version
```

### 问题 3: 权限被拒绝

检查 SSH 密钥或 HTTPS 凭据配置。

## 示例代码

### 完整示例

```python
import asyncio
from neurova.skills.builtin.github_push import create_github_push_skill

async def main():
    # 创建技能
    skill = create_github_push_skill()
    
    # 设置仓库路径
    skill.repo_path = "."
    
    # 获取状态
    status = await skill.execute({"action": "status"})
    print(f"状态: {status.data}")
    
    # 如果有更改，执行完整推送
    if not status.data.get("clean", True):
        result = await skill.execute({
            "action": "full_push",
            "message": "自动推送更新"
        })
        
        if result.success:
            print(f"推送成功: {result.data['commit_hash']}")
        else:
            print(f"推送失败: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())
```

## 相关文件

- `neurova/skills/builtin/github_push/skill.py` - 技能实现
- `neurova/skills/builtin/github_push/manifest.json` - 技能清单
- `neurova/skills/builtin/github_push/README.md` - 技能说明
- `tests/unit/skills/test_github_push_skill.py` - 测试文件