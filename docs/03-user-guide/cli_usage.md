# Neurova REPL CLI 使用文档

> **版本**: 3.0.0（2026-08-31，基于后端实测契约重写）
> **启动**: `python cli.py`（Git Bash / PowerShell / Windows Terminal）

---

## 1. 概述

Neurova REPL 是智星（Neurova）的命令行交互客户端，直连后端 `/api/v1` API：

- **流式聊天**：走 `/api/v1/console/chat`（SSE），逐字显示回复，含思考过程、工具调用与审批提示
- **会话管理**：新建/列出/切换/删除/归档会话，查看历史
- **附件**：上传本地文件并随消息发送
- **审批内联**：后端治理决议（Governance）要求确认时，直接在 REPL 内批准/拒绝
- **记忆与知识库**：查看/保存记忆、知识条目的增查删、混合检索
- **系统诊断**：健康检查、资源统计、系统事件日志、进程概览
- **Agent / LLM**：管理 Agent、切换服务商与模型
- **输入体验**：方向键上下历史回填（持久化到 `~/.neurova_repl_history`）、Tab 前缀补全、行尾 `\` 续行

## 2. 启动

```bash
# 方式一：交互输入用户名/密码
python cli.py

# 方式二：参数传入（密码不回显建议用环境变量）
python cli.py --url http://localhost:9527 --username uitest

# 环境变量方式（推荐，避免命令行泄露）
export NEUROVA_USERNAME=uitest
export NEUROVA_PASSWORD=YourPassword
python cli.py
```

启动流程：健康检查（`/api/v1/health`）→ 登录（`/api/v1/auth/login`）→ 自动选中第一个 Agent → 主循环。

登录失败时不退出：输入 `/login` 手动再次登录（密码用 `getpass` 不回显）。

## 3. 命令表

| 命令 | 说明 |
|---|---|
| `/agent` | 列出 Agent；`/agent switch <序号\|id>` 切换；`/agent add` 创建向导；`/agent del <序号>` 删除（default 不可删） |
| `/llm` | 列出服务商与当前激活模型；`/llm switch <序号>` 选服务商→选模型激活；`/llm add` 向导（openai/anthropic/gemini/ollama/openrouter/custom）；`/llm del <序号>` |
| `/model <id>` | 指定本次对话模型（回车查看当前） |
| `/think 简单\|标准\|深度\|off` | 调整思考深度（thinking_effort: light/standard/deep） |
| `/stream on\|off` | 切换流式 / 非流式输出 |
| `/sessions` | 会话列表（当前会话 ▶ 标记） |
| `/session <序号\|id>` | 切换会话；`/session del <序号>`、`/session archive <序号>` |
| `/new [标题]` | 新建会话并切换 |
| `/history` | 查看当前会话历史 |
| `/file <路径>` | 上传附件（下一消息携带）；`/file clear` 清空 |
| `/approval [list]` | 列出待审批；`/approval <ID>` 批准（服务端立即重放执行） |
| `/reject <ID> [备注]` | 拒绝审批 |
| `/memories [关键词]` | 记忆列表（可关键字过滤）；`/memories del <ID>` 删除 |
| `/memory save <内容> [--category 分类]` | 保存记忆 |
| `/memory stats` | 记忆统计 |
| `/knowledge` | 知识列表（`--scope all\|public\|private\|shared`）；`/knowledge find <词>`；`/knowledge add <标题> --content <内容> [--category][--visibility]`（public 仅 admin）；`/knowledge del <ID>` |
| `/search <词> [memory\|knowledge]` | 混合检索（语义+BM25+FTS） |
| `/health` | 后端健康状态 + 检查器（无检查器时如实提示） |
| `/stats` | CPU/内存/磁盘/性能概览 |
| `/logs [N\|level LEVEL]` | 最近系统事件日志 |
| `/monitor` | 进程级概览 |
| `/status` | 当前用户/Agent/会话/模型/思考深度/附件 |
| `/login` | 重新登录 |
| `/help` `/clear` `/exit` | 帮助 / 清屏 / 退出（Ctrl+C 亦可） |

## 4. 聊天示例

```
$ python cli.py
[✓] 后端连接成功
[✓] 登录成功: uitest
[✓] 已选择 Agent: Neurova (ID: default)
[uitest@default/-]> /new 测试会话
[✓] 已新建会话: 测试会话 (ID: 1a2b3c4d)
[uitest@default/1a2b3c4d]> /think 深度
[✓] 思考深度已设为: 深度
[uitest@default/1a2b3c4d]> 帮我总结这个项目的架构
（生成中，流式输出……）
[ui...]>
```

### 流式输出中的状态行

- `[思考: ...]`：模型推理过程（灰显，折叠显示前 60 字）
- `[工具] web_search`：工具调用/返回（单行折叠）
- `[待审批] remove_file 需要确认，ID: xxx（/approval xxx 批准，/reject xxx 拒绝）`：治理审批，人工确认

### 审批说明

审批批准后**服务端立即重放执行**该工具（`/api/v1/governance/approvals/{id}/approve`），结果仅在本命令回显；原对话流不会自动恢复——这是后端设计，REPL 会在批准后提示，可通过 `/history` 查看或直接继续对话。

## 5. 附件使用

```bash
# 上传并随下一条消息发送
/file ./data/example.txt
[✓] 已添加附件: example.txt (1024 字节)
帮我看看这个文件
（模型将收到附件元数据 file_id → attachments）

# 清空待发送附件
/file clear
```

## 6. 常见问题

- **登录失败**：默认用户不生效（admin/admin 不通用），用你自己的账号或 `/login`；普通用户对未配置的 provider 显示空列表是设计行为，不是故障。
- **`/logs` 显示 NORMAL 级别**：后端事件日志的级别字段为业务 NORMAL，用 `/logs level ERROR` 无法过滤到业务行时属预期（`/api/v1/logs/levels` 查询全量级别）。
- **磁盘占用提示**：命令执行报 "No space left on device" 时，先清理磁盘（如删除大缓存/安装镜像），否则 REPL 与测试都会受影响。
- **无 rich**：运行 `pip install "rich>=15"`（requirements.txt 已声明）。
