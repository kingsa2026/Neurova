# Mind Expander 使用指南

## 什么是 Mind Expander?

Mind Expander 是一个为 AI 编程代理设计的无限画布工作区。它将代码库转换为交互式的可视化图表，开发者与 AI 代理可以在同一个基于源代码的图表上协作。

## 快速开始

### 1. 打开代码库可视化

```bash
# 在浏览器中打开 Neurova 项目的交互式图表
npx mind-expander view e:/项目/Neurova
```

### 2. 查看最近的更改（Diff 模式）

```bash
# 查看未提交的更改
npx mind-expander view e:/项目/Neurova --at HEAD..

# 查看最近一次提交的更改
npx mind-expander view e:/项目/Neurova --at HEAD~1..HEAD

# 查看最近 5 次提交的更改
npx mind-expander view e:/项目/Neurova --at HEAD~5..HEAD

# 查看相对于 main 分支的更改
npx mind-expander view e:/项目/Neurova --at main..
```

### 3. 列出正在运行的实例

```bash
npx mind-expander list
```

### 4. 发送导览（Tour）

```bash
# 从文件发送导览
npx mind-expander tour tour.json

# 从 stdin 发送导览
echo '{"schema_version":2,"title":"Tour","steps":[{"say":"Start here","ref":{"file":"neurova/agent_core.py","line":1}}]}' | npx mind-expander tour -
```

## Tour JSON 格式

```json
{
  "schema_version": 2,
  "title": "导览标题",
  "steps": [
    {
      "say": "步骤描述",
      "ref": { "file": "path/to/file.py", "line": 42 }
    }
  ]
}
```

### Tour 示例：Neurova 架构导览

```json
{
  "schema_version": 2,
  "title": "Neurova 架构导览",
  "steps": [
    {
      "say": "Neurova 是一个基于神经科学原理的 AI Agent 框架",
      "ref": { "file": "neurova/agent_core.py", "line": 1 }
    },
    {
      "say": "核心 Agent 类是整个系统的中心协调器",
      "ref": { "file": "neurova/agent_core.py", "line": 255 }
    },
    {
      "say": "记忆系统负责存储和检索对话历史",
      "ref": { "file": "neurova/mem_core.py", "line": 1 }
    },
    {
      "say": "上下文系统构建 LLM 所需的完整上下文",
      "ref": { "file": "neurova/context/orchestrator.py", "line": 1 }
    },
    {
      "say": "工具系统允许 Agent 调用外部工具",
      "ref": { "file": "neurova/tool_executor.py", "line": 1 }
    }
  ]
}
```

## 使用场景

### 1. 代码库导览

当用户说：
- "带我走查一下这个代码库"
- "在图表上展示这个功能的架构"
- "可视化地解释这个模块"

### 2. PR 审查

当用户说：
- "可视化地审查我当前的更改"
- "展示这个 PR 的重要关系"
- "解释这些更改的影响"

### 3. 重构规划

当用户说：
- "将你的重构计划变成一个交互式导览"
- "展示这个重构涉及的所有文件"
- "可视化地规划这个变更"

## 高级用法

### 指定语言

```bash
# 仅显示 Rust 代码
npx mind-expander view e:/项目/Neurova --lang rust

# 仅显示 TypeScript 代码
npx mind-expander view e:/项目/Neurova --lang typescript
```

### 指定端口

```bash
npx mind-expander view e:/项目/Neurova --port 8080
```

## 注意事项

1. **首次使用前**：运行 `npx mind-expander --help` 获取完整的协议参考文档
2. **路径**：使用仓库相对路径，而不是绝对路径
3. **Tour 是回复的核心**：发送导览时，周围的文本应该尽量简洁
4. **以问题或下一步行动结束**：让用户知道接下来该做什么

## 故障排除

### 问题：服务启动失败

```bash
# 检查是否有正在运行的实例
npx mind-expander list

# 如果有，可以终止它们
kill <pid>
```

### 问题：看不到代码

```bash
# 确保在正确的目录中运行
cd e:/项目/Neurova
npx mind-expander view .
```

### 问题：TypeScript 文件没有显示

```bash
# 确保安装了 TypeScript 支持
npm install -g typescript
```

## 相关链接

- GitHub 仓库：https://github.com/mbbill/mind-expander
- 技能文件：`mind-expander-skill.md`
