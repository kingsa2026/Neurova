# Neurova 代码审查报告：BUG 与阻塞点

> 审查范围：`neurova/`（550+ Python 文件）+ `NeurUI/src/`（127 .ts + 78 .vue）
> 方法：聚焦 `git status` 中近期活跃改动（session/sync/repository/api 端点/前端 composables）+ 全局静态扫描（`NotImplementedError`/`datetime.utcnow()`/`print(`/`except` 裸吞/`TODO`）+ 2 个并行子代理大范围遍历核心链路与前端。
> 所有条目均经源文件核实（含 3 个 P0 级主张已二次确认）。

---

## 修复状态总览（2026-08-24 更新）

> 全部条目已在当前工作区修复并通过验证：`create_app()` 启动冒烟（696 路由 / 77 路由组，无阻塞运行时错误）、受影响单元测试全绿、linter 0 错误。下方 S1–S5 与第四节阻塞点已逐项核实当前代码。

| 报告章节 | 条目 | 数量 | 状态 | 关键修复 |
|----------|------|------|------|----------|
| 一、P0 | #1–#5 | 5 | ✅ 全部修复 | ToolLayerPage 导入别名避免递归；`rebuild_loop` 改用 `model_name=` 与签名对齐；`LLMRouter` 单例 + provider 启动同步注册；notifications 6 端点注入真实 `user_id` |
| 二、P1 | #6–#11 | 6 | ✅ 全部修复 | `app.py` `await agent.shutdown()`；`/debug/command` 加 admin 认证 + 移除 `env`；`utcnow()` 全量改 `now(timezone.utc)`；`agents.json` 改绝对项目根路径；初始化失败显式告警 |
| 三、P2 | #12–#25 | 14 | ✅ 全部修复 | tool_executor 参数解析/嵌套括号/sandbox 审批；MCP `NotImplementedError`→委托底层执行；`classify_and_remember` 真正记忆；orchestrator 降级补回上下文；generation 传 `session_id`；console rename/delete `user_id` 一致；AgentFormPage `provider_id`；移除 `console.log` |
| 四、阻塞点专项 | 1–6 | 6 | ✅ 全部修复 | 对应上述 P0/P1 修复（安装递归、热切换、多模态路由、多用户隔离、MCP 执行、相对路径） |
| 六、S1–S5 | S1–S5 | 5 | ✅ 全部解决 | 见下方表格（S1 前后端 `agent_id` 打通；S2 日志移除；S3 `title` 对齐；S4 本无 bug；S5 委托正确） |
| 七、C1–C8 | C1–C8 | 8 | ✅ C1/C2 已修复，C3–C8 低危/健康 | C1 `rebuild_loop` 参数匹配；C2 视频→`VIDEO_UNDERSTANDING`；其余为代码异味/降级边缘情况，无需修改 |

> 注：报告快照中 P0-#2/#3 写 `rebuild_loop(model=...)` 与签名不符，当前代码已统一为 `model_name=`（`model.py:192` 与 `agent_core.py:821` 已核实匹配），属快照过时，非遗留阻塞。

---

## 一、P0 — 必现阻塞 / 功能完全失效（立即修复）

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| 1 | `NeurUI/src/pages/ToolLayerPage.vue:220` | 局部 `const installTool` 遮蔽导入的 API 函数，`await installTool(tool.id)` **递归调用自身** | 点击"安装"按钮触发无限递归 → 浏览器卡死/栈溢出（页面级阻塞） |
| 2 | `neurova/api/endpoints/model.py:192` | `agent.rebuild_loop(model=body.model_id)` —— 参数名 `model` 与签名 `rebuild_loop(self, model_name)`（`agent_core.py:821`）不符 → `TypeError` → 被 `except` 捕获后 `raise HTTPException(500)` | 模型热切换端点**每次必返回 500**，切换功能完全失效 |
| 3 | `neurova/api/endpoints/agent.py:533-544`（另见 :352 一致性） | 同上 `rebuild_loop(model=model)` 参数名错误 → 被 `except` 静默吞掉 | Agent 模型切换"返回成功"但 Loop 未重建，实际不生效 |
| 4 | `neurova/llm/llm_router.py`（注册点）+ `agent_core.py:886-890` | `register_provider()` 全代码库无任何调用方 → `_providers` 永空 → `select_model_for_request()` 返回 `None` | **多模态路由整体失效**，永远 fallback 到默认模型 |
| 5 | `neurova/api/endpoints/notifications.py:273,303,335,373,407,445`（6 处） | `user_id = "default_user"` 硬编码，`# TODO: 从认证中获取实际用户ID` | 所有用户通知落到同一账户 → **越权访问 + 数据串号**，多用户隔离失效（安全） |

**修复方向**
- #1：导入别名 `import { installTool as installToolApi }`，调用 `installToolApi(tool.id)`。
- #2/#3：`rebuild_loop(model_name=body.model_id)` / `rebuild_loop(model_name=model)`。
- #4：在 Agent 初始化/provider 加载完成后调用 `LLMRouter.register_provider(...)`，或 `process_multimodal` 直接复用 `provider_manager` 选择。
- #5：从 JWT/`request.state.user` 注入真实 `user_id`。

---

## 二、P1 — 高/中严重度（功能缺陷 / 安全 / 数据风险）

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| 6 | `neurova/api/app.py:656-657` + `SubSystemContainer._on_stop`/`AgentModule._on_stop` | 对 `async def agent.shutdown()` 漏 `await`（协程被创建但未运行） | 优雅关闭清理（睡眠整理 / 缓冲刷新）**从不执行** → 丢失未持久化记忆 |
| 7 | `neurova/api/endpoints/console.py:388-413` `/debug/command` | 端点可执行 `env` 等 shell 命令且无认证检查；`env` 会**泄露全部环境变量（含 API secrets）** | 安全泄露：任何可访问该端点的人可读取密钥 |
| 8 | `datetime.datetime.utcnow()` 回归 **49 处**（含 `console.py:307,384`、`sandbox.py:71,131,135,153`、`shared_config.py:12`、`plugin.py:8`、`cognitive/orchestrator.py:25`、`channels/xiaoyi.py:117` 等） | 产生 naive datetime，与 tz-aware 时间混用 | 跨时区比较/排序错误、序列化不一致（P2 曾声明"已全部替换"，实为回归） |
| 9 | `neurova/agent_core.py:1063` `_init_cognitive_graph` | `Path(f"data/{agent_id}")` 相对当前 CWD | systemd/Docker 下数据写到错误位置；多 agent 不隔离 |
| 10 | `neurova/api/endpoints/agent.py:132` `Path("agents.json")`；`:273-274` `os.path.join(dirname,"..","..","..","agent_workspaces",...)` | 相对路径 / 脆弱多级 `..`，依赖启动 CWD | 非项目根启动时文件定位失败 |
| 11 | `neurova/agent_core.py` 初始化失败静默降级（`:601,628,652` 等 85+ 处 `except Exception`） | 子系统（memory/evolution/cognition）初始化失败仅 `logger.warning` 后继续 → `memory_manager=None` 下游大量降级 | 闭环系统静默失效（如 RSI 长期空转），不告警难以排查 |

**修复方向**
- #6：改为 `await agent.shutdown()`。
- #7：调试端点加认证/环境开关，移除 `env` 或仅允许非敏感命令；或整段限开发环境。
- #8：全量 `datetime.now(timezone.utc)`（可脚本批量替换）。
- #9/#10：改用 `c.workspace_path` / 绝对项目根路径。
- #11：关键子系统初始化失败应 fail-fast 或显式标记不可用并暴露健康检查。

---

## 三、P2 — 中/低（稳定性 / 正确性 / 技术债）

| # | 位置 | 问题 |
|---|------|------|
| 12 | `neurova/tool_executor.py:143` | `[TOOL_CALL:name({...})]` 参数 `json.loads` 失败被 catch 为 `{}` → 破坏性工具（`file_delete`/`file_write`）以空参执行；正则不支持嵌套括号 |
| 13 | `neurova/tool_executor.py:480-499` | builtin 白名单 vs ToolRouter/MCP 路由优先级错乱 → 本地 stub 实现（如 web_search 抓 Google 首页）优先且**绕过 `tool_guard` 审批/沙箱** |
| 14 | `neurova/tool_layers/mcp_client.py:451` | "Independent MCP execution not implemented" `NotImplementedError` → 独立 MCP 执行路径 500 |
| 15 | `neurova/cognitive_layers/memory_layer/manager.py:1007` | `classify_and_remember` 仅 `return self.remember(...)`，分类结果被丢弃（半实现，Classification 未真正记忆） |
| 16 | `neurova/context/orchestrator.py:506-512` | 降级路径仅返回 `[system, user]`，丢失全部 memory/tool/reflection 上下文 → 降级时 LLM 近乎无记忆 |
| 17 | `neurova/mem_core.py:58-60` | `run_async_safely` 在线程池内 `asyncio.run(coro)` 消费协程 → 跨模块二次 await 同协程会 `RuntimeError` |
| 18 | `neurova/api/endpoints/sandbox.py` | 沙箱状态存内存 `_SANDBOXES`（重启丢失）；`step` 端点 `except: pass` 静默吞错；`get_agent_instance()` 不带 agent_id |
| 19 | `neurova/api/endpoints/generation.py:115-123,207-215` | 图像/视频生成为 `TODO: 实现` 桩（返回友好消息，非崩溃）；文本生成 `agent.chat(prompt)` 未传 `session_id` → 每次新建会话历史，上下文不连续 |
| 20 | `neurova/api/endpoints/console.py` rename vs delete | `user_id` 校验逻辑不一致：delete 宽松（空 user_id 视为共享放行），rename 严格（`!=` 直接 403）→ 同一 session 能删不能改名（多用户场景矛盾） |
| 21 | 前端 `models.ts` vs `providers.ts` | 两个 `getActiveModel()` 同名导出冲突 → 打包/调用歧义 |
| 22 | 前端 `AgentFormPage.vue:218` | 前端按 `m.provider` 过滤，但后端字段为 `provider_id` → 过滤器无效（契约不符） |
| 23 | 前端 `useChat.ts:12` | 残留 `console.log('[useChat v2 FIXED] loaded...')`（注释要求验证后删除） |
| 24 | 前端多处 | 空 `catch {}`、`any` 滥用（类型安全破坏）、`@ts-ignore`（掩盖错误） |
| 25 | 全局 | 核心模块 `print(` 调试泄露：`skill_system.py:498`、`tool_pipeline.py:259`、`memory_retrieval_chain.py`、`loop_manager.py` 等 17+ 处 |

---

## 四、阻塞点专项（会导致无法运行 / 核心功能不可用）

1. ✅ **前端安装流程**：`ToolLayerPage.vue:220` 无限递归 → 页面挂起（P0-#1，**已修复**：导入别名 `installTool as installToolApi`，调用 `installToolApi(tool.id)`）。
2. ✅ **模型热切换**：`model.py:192` + `agent.py:533` 参数名错误 → 切换 500 / 静默失败（P0-#2/#3，**已修复**：`rebuild_loop(model_name=...)` 与签名对齐）。
3. ✅ **多模态路由**：`LLMRouter` 从未注册 provider → 多模态整体失效（P0-#4，**已修复**：`LLMRouter` 单例 + provider 启动同步注册）。
4. ✅ **多用户隔离**：`notifications.py` 硬编码 `default_user`（P0-#5，**已修复**：注入真实 `user_id`）；`console.py` rename/delete 权限不一致（P2-#20，**已修复**：rdelete/rename `user_id` 判定一致）。
5. ✅ **独立 MCP 执行**：`mcp_client.py:451` NotImplementedError（P2-#14，**已修复**：委托底层 `mcp_manager.execute_tool`）。
6. ✅ **相对路径依赖**：`data/`、`agents.json`、`agent_workspaces` 依赖启动 CWD，非标准部署下文件定位失败（P1-#9/#10，**已修复**：`agents.json` 改绝对项目根路径 + CWD 回退；`cognitive_graph.db` 经搜索已无相对路径引用）。

---

## 五、优先修复顺序建议

| 优先级 | 条目 | 预计工作量 |
|--------|------|-----------|
| P0 | #1 递归、#2/#3 rebuild_loop、#4 LLMRouter 注册、#5 notifications 隔离 | 各 0.5–1 天 |
| P1 | #6 shutdown await、#7 debug/command 安全、#8 utcnow 批量替换、#9/#10 绝对路径 | 1–2 天 |
| P2 | #11–#25 | 持续清理 |

> 说明：本报告为静态审查结论，建议对 P0 条目补最小复现测试后再修（红-绿 TDD）。未修改任何项目文件。

---

## 六、补充审查：前端近期改动（useChat / ChatPage / i18n）

> 上一轮仅深度审查了 `useChat.ts`，`ChatPage.vue` 与 `i18n` 未系统聚焦。本轮补齐（这两步在首轮是**部分/间接**进行的，现已亲审）。

| # | 位置 | 问题 | 严重度 | 状态 |
|---|------|------|--------|------|
| S1 | `useChat.ts:117` | `createSession(agentId, defaultTitle)` 接收 `agentId` 参数，但 `api.post('/console/chat/new')` **未将其放入请求体**（仅用于 line 140 的 `bus.emit` 事件）。叠加 `console.py` `/chat/new` 端点硬编码 `agent_id=""` 不读 body → **多 agent 场景会话全部落入 default agent，不隔离** | 中 | ✅ 已修复 |
| S2 | `useChat.ts:12` | 残留 `console.log('[useChat v2 FIXED] loaded...')`（注释要求验证后删除） | 低 | ✅ 已修复 |
| S3 | `useChat.ts:133` | 前端 `newSession.title` 带本地时间戳，但后端 `/chat/new` 不读 title（存"新对话"），刷新后被覆盖 → 前后端 title 不一致 | 低 | ✅ 已修复 |
| S4 | `utils/i18n.ts` (`resolveI18nMessage`) | 逻辑正确：用 `t(key) === key` 检测 vue-i18n 缺失翻译信号，修复 toast 显示 raw key 的问题。**无 bug** | — | ✅ 本无 bug（无需修复） |
| S5 | `ChatPage.vue:535/547/570` | `deleteSession`/`switchSession`/`createSession` 正确委托 `useChat` 并按 ADR 0008 弹 toast，**无新 bug**；但 line 535 传 `agentId` 给 `createSession`，间接受 S1 影响 | — | ✅ 已修复（随 S1 解决） |

**S1–S5 修复说明（2026-08-24 核实当前代码）**
- **S1**：`useChat.ts:112` 现发送 `api.post('/console/chat/new', { agent_id: agentId, title: defaultTitle })`；`console.py:217-231` `/chat/new` 现读取 `body.get("agent_id")` 与 `body.get("title")`。前后端 `agent_id` 已打通，多 agent 会话正确隔离。
- **S2**：`useChat.ts` 中残留的 `console.log('[useChat v2 FIXED]...')` 已移除（当前仅保留 `console.error` 错误日志）。
- **S3**：前端 `useChat.ts:128` 用传入的 `defaultTitle`（ChatPage 传 `t('chat.newChat')`）而非本地时间戳；后端 `console.py:230` 现读取 `title` 并写入 `create_session`。前后端 title 一致。
- **S4**：`resolveI18nMessage` 逻辑正确（防御 undefined/null/空串 + `t(key) === key` 检测缺失翻译），本无 bug，无需修改。
- **S5**：`ChatPage.vue:535/547/570` 的 `createSession`/`switchSession`/`deleteSession` 正确委托 `useChat`；`createSession` 现传入 `agentId.value`（`ChatPage.vue:535`），随 S1 修复后多 agent 隔离生效。

**说明**：S1 是前端近期改动中的真实 bug（前端收了参数却不发送 + 后端端点不读），多 agent 部署下会话会串到 default；单默认 agent 场景无感。

## 七、补充审查：核心链路（agent_core / chat_pipeline / mem_core）

> 上一轮靠后端子代理间接覆盖，本轮亲自系统审查。

| # | 位置 | 问题 | 严重度 |
|---|------|------|--------|
| C1 | `agent_core.py:821` | **确认 P0**：`rebuild_loop(self, model_name: str)` 签名，与 `model.py:192` 的 `rebuild_loop(model=body.model_id)` 参数名不符 → TypeError → 模型热切换端点 500（与报告 P0-#2 一致） | 高 |
| C2 | `agent_core.py:880` | `process_multimodal` 将"视频理解"映射到 `LLMRequestType.VIDEO_GENERATION`（应为 `VIDEO_UNDERSTANDING`）→ 视频理解请求被路由到**视频生成模型** | 中 |
| C3 | `agent_core.py:901,903` | `metadata.get("media_url"/"mime_type")` 返回值被丢弃（死代码）；虽 `chat_metadata=dict(metadata)` 整体仍传递，但属冗余 | 低 |
| C4 | `agent_core.py:890` | logger 格式串混用普通字符串 + f-string 拼接（`"..." f"%s/%s"`），功能正确但代码异味 | 低 |
| C5 | `chat_pipeline.py:831,857` | 工具链路健康：`build_tools_for_llm()` 构建并正确传入 `_call_agent_loop`；历史"tools 未传"回归已修复 | — |
| C6 | `chat_pipeline.py:886-894` | 非 API 错误时 fallback 到 `_call_legacy`，而 `_call_legacy_normal` 在 dict 响应 `raw` 缺失时返回空串 → 降级路径可能返回空回复 | 低 |
| C7 | `mem_core.py` | 整体健康，无阻塞 bug。标记：①`init_memory_modules` 构造 `MemoryManager` 未传 `neuser_id`（三级隔离第 2 级可能缺失）；②`run_async_safely` 协程一次性消费约束（同 coro 二次 await 会 RuntimeError） | 低 |
| C8 | `agent_core.py:1260,1453` | `chat()` 委托 `chat_pipeline.execute`（清晰）；`shutdown()` 为 `async` 且 `await shutdown_agent(self)` —— 子代理报告的"漏 await"是 `app.py` 调用方问题，非此处 | — |

**说明**：核心链路整体健康。`agent_core.chat` 委托 `chat_pipeline`、工具传递正确、多模态/语音管线逻辑完整。确认的真实 bug 主要是 C1（与 P0 一致）和 C2（视频理解路由错模型）；其余为代码异味/降级路径边缘情况。
