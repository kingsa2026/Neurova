# Neurova CLI 使用文档

> **版本**: 2.0.0 (增强版)
> **最后更新**: 2026-05-12
> **作者**: cli-dev

---

## 1. 概述

Neurova CLI 是忆灵（Neurova）的命令行交互界面，支持对话、记忆管理、技能调用、文件上传、会话管理等功能。

### 1.1 新功能（2.0.0 版本）
- ✅ **流式输出**：实时显示 LLM 生成的内容
- ✅ **文件上传**：支持上传文件到工作区
- ✅ **会话管理**：创建、加载、切换、删除会话
- ✅ **CognitionOrchestrator 集成**：使用认知编排器处理任务
- ✅ **增强的统计和配置命令**
- ✅ **命令自动补全**

---

## 2. 安装与启动

### 2.1 环境要求
- Python 3.8+
- 依赖库：`openai`, `mimetypes` (标准库)

### 2.2 配置 API 密钥
```bash
# 设置环境变量
export NEUROVA_LLM_API_KEY="your-api-key"
export NEUROVA_LLM_BASE_URL="https://api.openai.com/v1"

# 或在配置文件中设置
cat > cli_config.json << EOF
{
  "llm_api_key": "your-api-key",
  "llm_base_url": "https://api.openai.com/v1",
  "llm_model": "gpt-4",
  "llm_temperature": 0.7,
  "max_tokens": 2000,
  "enable_streaming": true
}
EOF
```

### 2.3 启动 CLI
```bash
# 方法 1: 直接运行
python -m neurova.cli_enhanced

# 方法 2: 使用增强版 CLI
python neurova/cli_enhanced.py
```

---

## 3. 命令详解

### 3.1 对话命令

#### `chat <消息>` - 与忆灵对话
```
用法: chat <消息内容> [--stream|--no-stream]

选项:
  --stream      启用流式输出（默认）
  --no-stream   禁用流式输出

示例:
  chat 你好
  chat 介绍一下 Python --no-stream
  chat 帮我写一个快速排序算法
```

**功能说明**:
- 支持流式输出，实时显示 LLM 生成的内容
- 支持思考过程可视化（显示 `<think>` 标签内容）
- 自动保存到当前会话

**快捷命令**: `c <消息>`

---

### 3.2 文件上传命令

#### `upload <文件路径>` - 上传文件到工作区
```
用法: upload <文件路径> [--public] [--description "描述"]

选项:
  --public        上传到公共目录
  --description  文件描述

示例:
  upload ./document.pdf --public --description "项目文档"
  upload ./image.png
```

**功能说明**:
- 支持文件类型检测
- 显示上传进度条
- 生成文件 ID 和访问路径

---

### 3.3 会话管理命令

#### `session <子命令>` - 会话管理
```
用法:
  session new                           - 创建新会话
  session load <session_id>             - 加载已有会话
  session list                          - 列出所有会话
  session delete <session_id>           - 删除会话
  session switch <session_id>           - 切换当前会话
  session info                          - 显示当前会话信息

示例:
  session new
  session list
  session switch abc123
  session info
```

**功能说明**:
- 每个会话独立存储对话历史
- 支持跨会话切换
- 自动保存对话记录到文件

---

### 3.4 记忆命令

#### `recall <关键词>` - 检索记忆
```
用法: recall <关键词>

示例:
  recall Python
  recall 机器学习
```

#### `remember <内容>` - 添加记忆
```
用法: remember <内容> [--category 分类] [--important] [--crystallize]

选项:
  --category     记忆分类（默认: conversation）
  --important   标记为重要记忆
  --crystallize 固化记忆（不可遗忘）

示例:
  remember 用户喜欢 Python --category profile --important
  remember 今天学习了机器学习 --crystallize
```

#### `memories` - 列出记忆
```
用法: memories [--limit N] [--category 分类] [--hot] [--since YYYY-MM-DD] [--search "关键词"]

选项:
  --limit N       限制返回数量（默认: 10）
  --category     按分类筛选
  --hot          按温度排序（高温记忆优先）
  --since        指定起始日期
  --search       搜索关键词

示例:
  memories --limit 20 --hot
  memories --category profile --search "Python"
```

---

### 3.5 技能命令

#### `skills` - 列出所有技能
```
用法: skills

示例:
  skills
```

#### `exec <技能名>` - 执行技能
```
用法: exec <技能名> [参数1=值1] [参数2=值2] ...

示例:
  exec file_operation action=read file_path=test.txt
  exec web_search query="Neurova AI"
```

---

### 3.6 系统命令

#### `stats` - 显示系统统计信息
```
用法: stats [--detailed]

选项:
  --detailed   显示详细信息

示例:
  stats
  stats --detailed
```

**显示内容**:
- LLM 统计（请求数、错误次数、成功率）
- 会话统计（总会话数、当前会话）
- 认知状态（注意力级别、记忆负载、学习率）
- 配置状态（流式输出、当前会话）

#### `config` - 显示/修改配置
```
用法:
  config                              - 显示当前配置
  config set <key> <value>            - 修改配置
  config reset                         - 重置配置
  config export                        - 导出配置
  config import <file>                - 导入配置

示例:
  config
  config set llm_temperature 0.8
  config set streaming_enabled true
  config export > config.json
  config import config.json
```

#### `clear` - 清空对话历史
```
用法: clear

示例:
  clear
```

#### `reset` - 重置 Agent
```
用法: reset

示例:
  reset
```

---

### 3.7 其他命令

#### `help` - 显示帮助信息
```
用法: help [命令名]

示例:
  help
  help chat
  help session
```

#### `quit` / `exit` - 退出 CLI
```
用法: quit
      exit

示例:
  quit
  exit
```

**快捷键**: `Ctrl+D` 也可以退出

---

## 4. 配置说明

### 4.1 配置文件格式
```json
{
  "llm_api_key": "your-api-key",
  "llm_base_url": "https://api.openai.com/v1",
  "llm_model": "gpt-4",
  "llm_temperature": 0.7,
  "max_tokens": 2000,
  "enable_streaming": true
}
```

### 4.2 配置项说明
| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `llm_api_key` | string | "" | LLM API 密钥 |
| `llm_base_url` | string | "https://api.openai.com/v1" | LLM API 地址 |
| `llm_model` | string | "gpt-4" | LLM 模型名称 |
| `llm_temperature` | float | 0.7 | 温度参数（0.0-1.0） |
| `max_tokens` | int | 2000 | 最大生成 Token 数 |
| `enable_streaming` | bool | true | 是否启用流式输出 |

---

## 5. 使用示例

### 5.1 基本对话
```bash
$ python -m neurova.cli_enhanced

╔══════════════════════════════════════════════════════════╗
║       🧠  忆灵 (Neurova) 控制台 (增强版)              ║
║       版本: 2.0.0                                      ║
║       输入 'help' 获取帮助                              ║
╚══════════════════════════════════════════════════════════╝

正在初始化忆灵（增强版）...
✓ 忆灵初始化完成

忆灵> chat 你好
忆灵思考中... 

你好！我是忆灵，很高兴和你交流。今天有什么想聊的吗？

忆灵> 
```

### 5.2 流式输出
```bash
忆灵> chat 介绍一下 Python --stream

忆灵思考中... 

Python 是一种高级编程语言，由 Guido van Rossum 创建...

忆灵> 
```

### 5.3 文件上传
```bash
忆灵> upload ./document.pdf --public --description "项目文档"

正在上传文件: document.pdf
文件类型: application/pdf
文件大小: 102400 字节

  上传进度: |██████████████████████████████████████████████| 100%

✓ 文件上传成功
  文件 ID: file_01234
  访问路径: e:\项目\Neurova\neurova\public\document.pdf
  描述: 项目文档

忆灵> 
```

### 5.4 会话管理
```bash
忆灵> session new

✓ 已创建新会话: abc123

忆灵> chat 你好
...

忆灵> session list

📝 会话列表 (2 个):

1. Session ID: abc123
   日期: 2026-05-12
   文件数: 1
   消息数: 2

2. Session ID: def456
   日期: 2026-05-11
   文件数: 1
   消息数: 10

忆灵> session switch def456

✓ 已切换到会话: def456

忆灵> session info

📋 当前会话信息:

  Session ID: def456
  消息数量: 10
  创建时间: 2026-05-11T10:30:00
  更新时间: 2026-05-11T11:45:00

忆灵> 
```

### 5.5 记忆管理
```bash
忆灵> remember 用户喜欢 Python --category profile --important

✓ 记忆已添加 (ID: mem_abc123)
  ⭐ 标记为重要记忆

忆灵> memories --hot

🔥 高温记忆 (Top 10):

1. ⭐ [profile] [温度: 85.2°C]
   用户喜欢 Python
   
2. [conversation] [温度: 72.3°C]
   今天学习了机器学习...

忆灵> recall Python

找到 3 条相关记忆:

1. ⭐ [profile] [温度: 85.2°C]
   用户喜欢 Python
   
...

忆灵> 
```

### 5.6 技能执行
```bash
忆灵> skills

🔧 可用技能 (5 个):

✅ file_operation
   文件操作（读取、写入、删除）
   标签: file, io
   使用次数: 10

✅ web_search
   网络搜索
   标签: web, search
   使用次数: 5

...

忆灵> exec file_operation action=read file_path=test.txt

✓ 执行成功 (耗时: 0.045s)

结果:
这是文件内容...

忆灵> 
```

### 5.7 统计信息
```bash
忆灵> stats

📊 系统统计 (增强版)

🤖 LLM 统计:
  总请求数: 25
  错误次数: 1
  成功率: 96.0%

💬 会话统计:
  总会话数: 3
  当前会话: abc123

🧠 认知状态:
  注意力级别: medium
  记忆负载: 45.0%
  学习率: 50.0%

⚙️ 配置状态:
  流式输出: 启用
  当前会话: abc123

忆灵> 
```

### 5.8 配置管理
```bash
忆灵> config

⚙️ 当前配置 (增强版):

LLM 模型: gpt-4
LLM 温度: 0.7
最大 Token: 2000
流式输出: 启用
当前会话: abc123

忆灵> config set llm_temperature 0.8

✓ 配置已更新: llm_temperature = 0.8

忆灵> config export > config.json

忆灵> 
```

---

## 6. 高级功能

### 6.1 思考过程可视化
当 LLM 生成 `<think>...</think>` 标签内容时，CLI 会特殊显示：
```bash
忆灵> chat 分析这个问题

忆灵思考中... 

💭 [思考过程].......

经过分析，我认为...

忆灵> 
```

### 6.2 命令自动补全
按 `Tab` 键可以自动补全命令和参数：
```bash
忆灵> chat --[Tab]
--stream    --no-stream

忆灵> session [Tab]
new    load    list    delete    switch    info

忆灵> 
```

---

## 7. 常见问题解答

### 7.1 LLM API Key 未设置
**问题**: 启动 CLI 时显示 "LLM API Key 未设置"

**解决方案**:
```bash
# 设置环境变量
export NEUROVA_LLM_API_KEY="your-api-key"

# 或在配置文件中设置
echo '{"llm_api_key": "your-api-key"}' > cli_config.json
```

### 7.2 流式输出不工作
**问题**: 启用流式输出后没有反应

**解决方案**:
1. 检查 LLM 客户端是否初始化成功
2. 使用 `config set enable_streaming false` 禁用流式输出
3. 检查网络连接

### 7.3 文件上传失败
**问题**: 上传文件时显示 "文件不存在"

**解决方案**:
1. 检查文件路径是否正确
2. 使用绝对路径
3. 检查文件权限

### 7.4 会话管理问题
**问题**: 无法创建或切换会话

**解决方案**:
1. 检查 `session_manager` 是否初始化成功
2. 查看日志文件
3. 使用 `session list` 查看所有会话

---

## 8. 技术细节

### 8.1 流式输出实现
- 使用 `LLMClient.chat_stream()` 方法获取流式响应
- 实现 SSE（Server-Sent Events）风格的实时输出
- 支持思考过程可视化（`<think>` 标签）

### 8.2 文件上传实现
- 使用 `mimetypes` 模块检测文件类型
- 实现上传进度条显示
- 支持公共目录和私有目录

### 8.3 会话管理实现
- 使用 `SessionManager` 管理会话
- 会话数据存储在 `session/` 目录
- 支持跨会话切换和历史记录查询

### 8.4 CognitionOrchestrator 集成
- 使用 `CognitionOrchestrator` 处理任务
- 实现认知循环调用
- 支持错误处理和重试

---

## 9. 更新日志

### v2.0.0 (2026-05-12)
- ✅ 新增：流式输出支持
- ✅ 新增：文件上传命令
- ✅ 新增：会话管理命令
- ✅ 新增：CognitionOrchestrator 集成
- ✅ 增强：统计和配置命令
- ✅ 新增：命令自动补全

### v0.1.0 (2026-05-10)
- ✅ 初始版本
- ✅ 基本对话功能
- ✅ 记忆管理功能
- ✅ 技能执行功能

---

## 10. 参考资料

- 架构文档：`docs/NEUROVA_CogArch_2.0.md`（第 2662-2700 行）
- 模块设计文档：`docs/dev_progress/module_designs/cli_enhanced.md`
- LLM 客户端：`neurova/llm_client.py`
- 会话管理器：`neurova/session_manager.py`
- 认知编排器：`neurova/cognitive/orchestrator.py`

---

**最后更新**: 2026-05-12 23:50
**作者**: cli-dev
**版本**: 2.0.0
