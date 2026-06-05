# Neurova GitHub Push Skill

GitHub 推送技能 - 封装完整的 Git 操作流程，支持状态检查、文件添加、提交和推送到 main 分支。

## 功能特性

- **状态检查**: 查看 Git 工作区状态
- **文件添加**: 添加文件到暂存区
- **提交更改**: 提交暂存的更改
- **推送更改**: 推送到远程仓库（支持直接推送到 main 分支）
- **完整工作流**: 一键执行完整的推送流程

## 使用方法

### 1. 作为技能系统的一部分使用

```python
from neurova.skills.builtin.github_push.skill import GitHubPushSkill, create_github_push_skill

# 创建技能实例
skill = create_github_push_skill()

# 获取状态
result = await skill.execute({"action": "status"})

# 完整推送
result = await skill.execute({
    "action": "full_push",
    "message": "添加新功能",
    "push_to_main": True
})
```

### 2. 使用便捷函数

```python
from neurova.skills.builtin.github_push.skill import push_to_github

# 一键推送
result = await push_to_github(
    message="更新代码",
    push_to_main=True,
    repo_path="."
)
```

### 3. 命令行使用

```bash
# 直接运行技能文件
python neurova/skills/builtin/github_push/skill.py
```

## 参数说明

| 参数 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| action | string | 否 | "full_push" | 操作类型：status, add, commit, push, full_push |
| message | string | 否 | "Update from Neurova GitHub Push Skill" | 提交信息 |
| files | array | 否 | None | 要添加的文件列表（默认所有文件） |
| push_to_main | boolean | 否 | True | 是否直接推送到 main 分支 |
| branch | string | 否 | None | 指定分支 |
| repo_path | string | 否 | "." | 仓库路径 |

## 操作类型

### 1. `status` - 获取状态
```python
result = await skill.execute({"action": "status"})
# 返回: 工作区状态、更改文件列表
```

### 2. `add` - 添加文件
```python
result = await skill.execute({
    "action": "add",
    "files": ["file1.py", "file2.py"]  # 可选，不指定则添加所有
})
# 返回: 暂存的文件列表
```

### 3. `commit` - 提交更改
```python
result = await skill.execute({
    "action": "commit",
    "message": "修复 bug"
})
# 返回: 提交哈希、提交信息
```

### 4. `push` - 推送更改
```python
result = await skill.execute({
    "action": "push",
    "push_to_main": True
})
# 返回: 推送目标分支
```

### 5. `full_push` - 完整工作流
```python
result = await skill.execute({
    "action": "full_push",
    "message": "添加新功能",
    "push_to_main": True
})
# 返回: 完整工作流结果
```

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

- **工作区干净**: 如果没有更改，跳过添加和提交步骤
- **暂存区为空**: 如果没有暂存的更改，提交操作会失败
- **远程仓库未配置**: 如果没有配置远程仓库，推送操作会失败
- **Git 命令失败**: 任何 Git 命令失败都会返回详细的错误信息

## 示例

### 示例 1: 检查状态
```python
result = await skill.execute({"action": "status"})
if result.success:
    if result.data["clean"]:
        print("工作区干净")
    else:
        print(f"有 {result.data['total_files']} 个文件更改")
```

### 示例 2: 完整推送
```python
result = await skill.execute({
    "action": "full_push",
    "message": "实现新功能 #123"
})

if result.success:
    print(f"提交哈希: {result.data['commit_hash']}")
    print(f"推送到: {result.data['pushed_to']}")
    print(f"提交文件数: {result.data['files_committed']}")
```

### 示例 3: 仅提交不推送
```python
# 先添加文件
await skill.execute({"action": "add"})

# 再提交
result = await skill.execute({
    "action": "commit",
    "message": "本地保存"
})
```

## 依赖

- Python 3.7+
- Git 命令行工具
- Neurova 技能系统

## 注意事项

1. **权限要求**: 确保有 Git 仓库的读写权限
2. **远程仓库**: 需要配置远程仓库（`git remote add origin <url>`）
3. **分支保护**: 如果 main 分支有保护规则，可能需要特殊权限
4. **网络连接**: 推送操作需要网络连接

## 技术实现

- 使用 `asyncio.create_subprocess_exec` 异步执行 Git 命令
- 支持 Windows 和 Unix 系统
- 详细的日志记录
- 完整的错误处理和状态报告