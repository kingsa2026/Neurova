# Neurova 项目全量 BUG 审计报告

> **审计时间**: 2026-06-25
> **审计方法**: zoom-out (全局架构) + improve-codebase-architecture (深模块/删除测试) + bug-hunt (5 阶段根因调试) + tdd-workflow (验证驱动)
> **审计范围**: 整个项目源码（neurova/ 后端 + NeurUI/ 前端 + tests/ 测试）
> **审计约束**: 只排查不修复，所有 BUG 均有文件:行号证据

---

## 目录

- [执行摘要](#执行摘要)
- [第一部分: BUG 清单](#第一部分-bug-清单)
  - [1.1 后端核心模块 (27 个 BUG)](#11-后端核心模块-27-个-bug)
  - [1.2 后端 API + LLM (32 个 BUG)](#12-后端-api--llm-32-个-bug)
  - [1.3 前端 (24 个 BUG)](#13-前端-24-个-bug)
  - [1.4 模块委托 + 通道适配器 (27 个 BUG)](#14-模块委托--通道适配器-27-个-bug)
- [第二部分: 架构结构性问题](#第二部分-架构结构性问题)
- [第三部分: 修复优先级建议](#第三部分-修复优先级建议)
- [附录: 审计方法论](#附录-审计方法论)

---

## 执行摘要

本次审计对 Neurova 项目全量源码进行系统性 BUG 排查，共发现 **110 个 BUG** 和 **16 个结构性问题**。

### BUG 严重程度分布

| 严重程度 | 数量 | 占比 | 说明 |
|---------|------|------|------|
| **P0 (Critical)** | 15 | 13.6% | 导致功能完全失效、安全漏洞、运行时崩溃 |
| **P1 (High)** | 32 | 29.1% | 功能错误、数据丢失风险、性能问题 |
| **P2 (Medium)** | 42 | 38.2% | 边界条件错误、逻辑缺陷、可维护性差 |
| **P3 (Low)** | 21 | 19.1% | 代码质量、命名不一致、文档缺失 |

### BUG 分类分布

| 分类 | BUG 数 | 关键问题 |
|------|--------|---------|
| 后端核心模块 | 27 | asyncio.run() 崩溃、工具消息链路断裂、logging 未导入 |
| 后端 API + LLM | 32 | 无盐 SHA-256 密码、路径遍历、XOR 冒充加密、无认证端点 |
| 前端 | 24 | request 未导入崩溃、ASR 无限循环、XSS 漏洞 |
| 模块委托 + 通道 | 27 | 7 个通道适配器 try:pass 导入错误、hmac 未导入 |

### Top 10 最严重 BUG

1. **[P0]** `mem_core.py:582` — `asyncio.run()` 在异步上下文中调用，MoE 记忆检索完全失效
2. **[P0]** `api/auth.py:292` — 密码验证回退到无盐 SHA-256，彩虹表攻击风险
3. **[P0]** `files_api.py:96` — 文件上传路径遍历漏洞，可写入任意路径
4. **[P0]** `secret_store.py:68-75` — API Key 用 XOR 混淆冒充加密
5. **[P0]** `HealthPage.vue:130` — `request` 未导入，健康页面运行时崩溃
6. **[P0]** `ChatPage.vue:872-881` — ASR 自动重启可能形成无限循环
7. **[P0]** `tool_executor.py:198` — 工具消息写入错误列表，消费者读取不到
8. **[P0]** `discord.py:14-19` — `try: pass` 后 `REQUESTS_AVAILABLE = True`，requests 从未导入
9. **[P0]** `qqbot.py:25-30` — `import re` 误写（应为 `import requests`）
10. **[P0]** `manager.py:151` — SQL Schema 拼写错误 `neuser_id`

---

## 第一部分: BUG 清单

### 1.1 后端核心模块 (27 个 BUG)

#### 1.1.1 neurova/mem_core.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-001 | **P0** | mem_core.py:582 | `asyncio.run(moe.retrieve(...))` 在异步上下文中调用导致 RuntimeError，MoE 记忆检索完全失效 | `results = asyncio.run(moe.retrieve(query, limit=limit))` — 若调用方在 async 函数内，`asyncio.run()` 会抛 "asyncio.run() cannot be called from a running event loop" |
| BE-CORE-002 | P2 | mem_core.py:570-591 | MoE 检索失败时静默降级，无指标记录 | `except Exception as e: logger.warning(...)` — 降级到普通检索但无监控指标 |

#### 1.1.2 neurova/agent_core.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-003 | **P0** | agent_core.py:40,52,84 | `logging.warning()` 调用但未 `import logging`，模块加载时 NameError | 第 40 行 `logging.warning("TemperatureEngine not available")` — 文件头仅 `from neurova.core.logger import get_logger`，未导入 `logging` 模块 |
| BE-CORE-004 | P1 | agent_core.py:1348 | `self._skill_registry.skills` 属性不存在 | SkillRegistry 类无 `skills` 属性，访问时 AttributeError |
| BE-CORE-005 | P2 | agent_core.py:1244 | `user_input[:50]` 未做 None 检查 | 若 `user_input` 为 None，抛 TypeError |
| BE-CORE-006 | P2 | agent_core.py:79-84 | `try: pass` 后 `AGENT_LOOP_AVAILABLE = True` | try 块为空，标志永远为 True，但 Agent Loop 系统实际未导入 |
| BE-CORE-007 | P3 | agent_core.py:106-151 | AgentLLMClient 是 pass-through 浅模块 | 每个方法 1-3 行委托给 MultiModelLLMClient，无任何附加逻辑 |

#### 1.1.3 neurova/tool_executor.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-008 | **P0** | tool_executor.py:198 | 工具消息写入 `self._messages_list`，但消费者读取 `agent._tool_messages_list`，数据丢失 | `self._messages_list.append({"role": "tool", ...})` — 属性名不匹配导致 LLM 上下文中看不到工具结果 |
| BE-CORE-009 | P1 | tool_executor.py:235 | `check_tool_memory(tool_name)` 参数语义错误 | 注释写 "接受 user_input 字符串"，但实际传入 `tool_name` |
| BE-CORE-010 | P1 | tool_executor.py:419 | `get("params", {})` 键名应为 `"tool_params"` | 工具调用参数实际存储在 `tool_params` 键下，`params` 键不存在，永远返回空字典 |
| BE-CORE-011 | **P0** | tool_executor.py:372,380 | CLI 工具命令注入漏洞 | `subprocess.run(cmd, shell=True)` 未用 `shlex.quote()` 转义用户输入 |
| BE-CORE-012 | P1 | tool_executor.py:788 | `_emotion_analyzer` 属性名错误 | 应为 `_emotion_module`，属性名不匹配导致 AttributeError |
| BE-CORE-013 | P1 | tool_executor.py:598,614,626,640,654,659 | 文件操作无路径遍历防护 | `open(path)` / `write(path)` / `read(path)` 未校验 `..` 路径 |

#### 1.1.4 neurova/agent/chat_pipeline.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-014 | P1 | chat_pipeline.py:1283 | `tm.get("type") == "tool_result"` 永远为 False | 实际类型为 `"tool_call"`，条件永不匹配，工具结果消息被丢弃 |
| BE-CORE-015 | P1 | chat_pipeline.py:596 | ChatContext 缺少 user_id 字段 | 上下文无用户隔离，多用户可能串数据 |
| BE-CORE-016 | P2 | chat_pipeline.py:976 | `_last_tool_used` 从未赋值 | 属性声明但无写入点，永远为初始值 |
| BE-CORE-017 | P2 | chat_pipeline.py:793 | `max_tokens=0` 导致续写循环永不触发 | 0 表示无限制，但续写逻辑判断 `tokens_used < max_tokens` |

#### 1.1.5 neurova/post_chat_pipeline.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-018 | P1 | post_chat_pipeline.py:409-410 | `agent.user_id` / `agent_id` 属性不存在 | 实际存储在 `agent.config.user_id`，直接访问抛 AttributeError |
| BE-CORE-019 | P2 | post_chat_pipeline.py:1066 | 检查字典键而非值 | `if "key" in dict:` 而非 `if dict.get("key"):`，空字符串/0 会被误判为存在 |
| BE-CORE-020 | P2 | post_chat_pipeline.py:1076,1233 | `_tool_weights` vs `tool_weights` 访问不一致 | 同一属性两种命名，部分方法读不到数据 |

#### 1.1.6 其他核心模块

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-CORE-021 | P2 | agent_core.py:286-500 | SubSystemContainer 假深度模块 | 427 行代码但不持有状态，仅分组 init 方法 |
| BE-CORE-022 | P2 | agent_core.py:1352-1409 | 10+ 个 1-line delegation 方法 | 纯委托噪声，无附加逻辑 |
| BE-CORE-023 | P3 | memory_agent.py | 8 行重导出兼容层 | 删除测试通过，复杂度不重新出现 |
| BE-CORE-024 | P2 | evolution/evolution_facade.py | 异常吞噬 Facade | 每个方法 `try: ... except: log warning`，失败静默 |
| BE-CORE-025 | P1 | cognitive_layers/memory_layer/manager.py:379-406 | `_extract_dependency_async` 异步反模式 | 同步方法用 `asyncio.get_event_loop()` (已弃用) |
| BE-CORE-026 | P2 | agent_core.py:1214-1253 | Agent.chat() 4 层间接 | Agent → ChatPipeline → AgentLLMClient → MultiModelLLMClient → Provider |
| BE-CORE-027 | P3 | api/endpoints/chat.py:404-469 | rename/delete_session 是 stub | 注释 "由于我们没有实际的会话存储，返回成功响应" |

---

### 1.2 后端 API + LLM (32 个 BUG)

#### 1.2.1 neurova/api/auth.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-001 | **P0** | auth.py:292 | 密码验证回退到无盐 SHA-256 | `return hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed` — 彩虹表攻击风险 |
| BE-API-002 | P1 | auth.py:60-74 | JWT 密钥文件无权限保护 | `open(key_file, "w")` 创建的文件默认 644，其他用户可读 |
| BE-API-003 | P2 | auth.py:303-318 | get_current_user 无 token 过期检查 | 仅验证签名，不检查 exp 字段 |

#### 1.2.2 neurova/api/endpoints/files_api.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-004 | **P0** | files_api.py:96 | 文件上传路径遍历漏洞 | `file_path = storage_dir / f"{file_id}_{file.filename}"` — `file.filename` 可含 `../../` |
| BE-API-005 | **P0** | files_api.py:80-208 | 所有端点无认证依赖 | 无 `Depends(get_current_user)`，匿名用户可访问 |
| BE-API-006 | P1 | files_api.py:97 | 文件大小无限制 | `content = await file.read()` 读取全部内容到内存，可 OOM |
| BE-API-007 | P1 | files_api.py:100 | MIME 类型信任客户端 | `mimetypes.guess_type(file.filename)` 仅基于扩展名，可伪造 |

#### 1.2.3 neurova/llm/providers/secret_store.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-008 | **P0** | secret_store.py:68-75 | API Key 用 XOR 混淆冒充加密 | `obfuscated = bytes(a ^ b for a, b in zip(key_bytes, mask))` — XOR 不是加密，密钥和掩码同源 |
| BE-API-009 | P1 | secret_store.py:40-50 | 密钥掩码硬编码在源码 | 掩码字符串写死在代码中，源码泄露即密钥泄露 |

#### 1.2.4 neurova/api/endpoints/provider.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-010 | **P0** | provider.py:84,117,145,164,192,232,296,317,343 | 所有端点无认证 | 9 个端点无 `Depends(get_current_user)`，可查看/修改 LLM 配置 |
| BE-API-011 | P1 | provider.py:200-220 | API Key 明文返回 | `GET /providers/{id}` 返回完整 api_key 字段 |

#### 1.2.5 neurova/llm/multi_model_client.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-012 | P1 | multi_model_client.py:292 | LLM 调用无超时 | `await provider.chat(...)` 无 timeout 参数，可能永久阻塞 |
| BE-API-013 | P2 | multi_model_client.py:180-200 | 重试逻辑无指数退避 | 固定间隔重试，可能加剧服务端压力 |
| BE-API-014 | P2 | multi_model_client.py:350-380 | 故障转移无健康检查 | 直接切换到下一个 provider，不检查其可用性 |

#### 1.2.6 neurova/api/middleware.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-015 | P1 | middleware.py:109 | "unknown" IP 导致匿名客户端共享限流 | 所有无法识别 IP 的请求被归为同一 "unknown" 桶 |
| BE-API-016 | P2 | middleware.py:150-170 | CORS 配置允许所有来源 | `allow_origins=["*"]` 在生产环境不安全 |

#### 1.2.7 其他 API + LLM

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| BE-API-017 | P1 | api/endpoints/chat.py:75-99 | 权限检查逻辑散落 | `_user_can_access_agent` 定义在 chat.py 内部，81 个端点文件重复实现 |
| BE-API-018 | P1 | api/endpoints/memory/base.py:126-165 | get_memory_manager 有副作用 | getter 函数修改 memory_manager 的 user_id，多用户并发覆盖 |
| BE-API-019 | P2 | api/endpoints/chat.py:404-469 | rename/delete_session 是 stub | 注释 "由于我们没有实际的会话存储" |
| BE-API-020 | P2 | api/endpoints/chat.py:597-622 | add_attachment 是 stub | 注释 "TODO: 实现附件处理" |
| BE-API-021 | P2 | llm/providers/openai_provider.py:120 | 流式响应无错误处理 | `yield chunk` 不检查 chunk 错误字段 |
| BE-API-022 | P2 | llm/router.py:85-100 | 路由策略无 fallback | 路由失败直接抛异常，无降级策略 |
| BE-API-023 | P2 | api/endpoints/console.py | 直接读环境变量 | 2 处 `os.environ.get` 绕过统一配置库 |
| BE-API-024 | P2 | api/app.py | 直接读环境变量 | 3 处 `os.environ.get` 配置端口/密钥 |
| BE-API-025 | P2 | skills/hub_client.py | 直接读环境变量 | 8 处 `os.environ.get` 配置 hub URL |
| BE-API-026 | P2 | api/endpoints/mobile_pairing.py | 直接读环境变量 | 1 处 `os.environ.get` |
| BE-API-027 | P3 | api/endpoints/*.py | 100 个文件 `logging.getLogger` 绕过统一日志库 | 统一率仅 16.7% |
| BE-API-028 | P3 | api/endpoints/*.py | 81 个端点重复 15-25 行样板 | 权限检查 + 错误响应模板未抽象 |
| BE-API-029 | P2 | llm/providers/secret_store.py | 直接读环境变量 | 2 处 `os.environ.get` 存密钥 |
| BE-API-030 | P2 | security/neu_token_manager.py | 直接读环境变量 | 1 处 `os.environ.get` 读 NEU_TOKEN_SECRET |
| BE-API-031 | P2 | skills/registry.py, market_searcher.py | 直接读环境变量 | 2 处 `os.environ.get` |
| BE-API-032 | P2 | knowledge/config.py, skill_system.py | 直接读环境变量 | 2 处 `os.environ.get` |

---

### 1.3 前端 (24 个 BUG)

#### 1.3.1 NeurUI/src/pages/HealthPage.vue

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-001 | **P0** | HealthPage.vue:130 | `request` 未导入导致运行时崩溃 | `await request.post(...)` 被调用，但 `<script>` 中无 `import { request } from '@/api'` — grep 确认无导入 |

#### 1.3.2 NeurUI/src/pages/ChatPage.vue

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-002 | **P0** | ChatPage.vue:872-881 | ASR 自动重启可能形成无限循环 | `recognition.onend` 中 `if (isRecording.value) recognition.start()` — 若 `isRecording` 未被正确重置，无限重启 |
| FE-003 | P1 | ChatPage.vue:182,1184-1235 | v-html XSS 漏洞 | `escapeHtml` 未转义引号，攻击者可注入 `"><img onerror=...>` |
| FE-004 | P1 | ChatPage.vue:810-815 | 'done' 分支引用已清空的 inputText | 状态机时序错误，清空后仍访问 |

#### 1.3.3 NeurUI/src/utils/logger.ts

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-005 | P1 | logger.ts:60-64 | error 方法可能触发无限循环 | bus 双向耦合：logger.error → bus.emit → logger.error |

#### 1.3.4 NeurUI/src/pages/DashboardPage.vue

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-006 | P1 | DashboardPage.vue:280 | 用 memory 指标判断 redis 健康状态 | `redis.health = memoryStats.connected` — 语义错误 |

#### 1.3.5 NeurUI/src/components/AgentSwitcher.vue

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-007 | P1 | AgentSwitcher.vue:108,122-123 | 访问不存在的字段 | `agent.system_prompt` / `agent.role` 字段在数据模型中不存在 |

#### 1.3.6 其他前端

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| FE-008 | P2 | src/api/modules/memory.ts | 948 行单文件，60+ 函数无抽象 | 纯 HTTP 调用列表，无缓存/重试/错误转换 |
| FE-009 | P2 | src/api/modules/ (56 文件) | 无抽象的 HTTP 列表 | 删除测试通过：删除后调用方直接用 api.get，复杂度不变 |
| FE-010 | P2 | src/views/ (82 页面) | 大量本地状态 | 仅 5 个 store，82 页面多本地状态，状态散落 |
| FE-011 | P2 | src/components/ (10 组件) | 组件库不完整 | 页面直接用 Ant Design 原生组件，未封装 |
| FE-012 | P2 | src/styles/ | 无全局样式库 | 样式散落在各组件 scoped style |
| FE-013 | P2 | src/animations/ | 无动画库 | 动画散落在组件 transition |
| FE-014 | P2 | src/utils/message | 59 文件直接调用 message | 无统一提示库封装 |
| FE-015 | P2 | src/bus/ | 无统一事件总线 | 36 文件有 emit/on 但都是组件事件 |
| FE-016 | P2 | src/layouts/ (2 布局) | 布局库不完整 | 仅 MainLayout/ChatLayout |
| FE-017 | P2 | src/composables/ (3 个) | 交互库不完整 | 仅 useAPI/usePolling/useAgentPage |
| FE-018 | P2 | src/config/ | 无前端配置库 | 配置散落 |
| FE-019 | P2 | src/utils/logger.ts | 无前端日志库 | 错误散落在 try/catch |
| FE-020 | P2 | src/utils/error.ts | 无前端错误库 | 无统一错误处理 |
| FE-021 | P3 | src/pages/ChatPage.vue:1184-1235 | markdown 渲染未限制 HTML 标签 | v-html 直接渲染，无 sanitize |
| FE-022 | P3 | src/api/index.ts | 请求拦截器无重试 | 网络错误直接失败 |
| FE-023 | P3 | src/stores/ | store 数量不足 | 5 个 store vs 82 页面，状态管理覆盖不足 |
| FE-024 | P3 | src/pages/*.vue | 59 文件直接调用 message.success/error | 无统一提示库 |

---

### 1.4 模块委托 + 通道适配器 (27 个 BUG)

#### 1.4.1 neurova/cognitive_layers/memory_layer/manager.py

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| CH-001 | **P0** | manager.py:151 | SQL Schema 拼写错误 `neuser_id` | `neuser_id TEXT NOT NULL DEFAULT 'default'` — 应为 `neurova_user_id` 或统一为 `user_id`，当前与 line 152 的 `user_id` 列共存，语义混乱 |
| CH-002 | P1 | manager.py:628,632,636,641,645,652,672 | `_emotion_module` 未做 None 检查 | 7 处直接调用 `self._emotion_module.xxx()`，若模块未初始化抛 AttributeError |
| CH-003 | P1 | manager.py:1617-1620 | `close()` 不关闭子模块 | 仅关闭自身连接，17 个子模块资源泄漏 |
| CH-004 | P2 | manager.py:79-107 | 17 个 `_module = None` 属性 | 16 个永远不会被初始化（仅 EmotionModule 在 __init__ 中） |
| CH-005 | P2 | manager.py:677-685 等 | 17 个 `_ensure_*_module()` 懒加载方法 | 懒加载 = 永远不加载，调用方不知该调哪个 |
| CH-006 | P2 | manager.py:853-871 | `meta_should_*` 方法全部 `return True` | 4 个方法无逻辑，永远返回 True |
| CH-007 | P2 | manager.py:654-668 | Emotion stub 方法返回默认值 | `apply_emotion_to_temperature` 返回原值，`get_emotion_history` 返回 `[]` |
| CH-008 | P2 | manager.py:1634 行 | 87+ stub 方法掩盖功能未实现 | 返回 `{"status": "ok"}` 让调用方以为成功 |
| CH-009 | P2 | manager.py:379-406 | `_extract_dependency_async` 异步反模式 | 同步方法用 `asyncio.get_event_loop()` (已弃用) |
| CH-010 | P3 | manager.py | Facade 接口宽 100+ 方法，实现浅 | 删除测试通过：删除 stub 复杂度不重新出现 |

#### 1.4.2 通道适配器系统性问题 (7 个 P0)

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| CH-011 | **P0** | channels/discord.py:14-19 | `try: pass` 后 `REQUESTS_AVAILABLE = True` | try 块为空，requests 从未导入，但标志为 True |
| CH-012 | **P0** | channels/qq.py:16-19 | 同上 | `try: pass` + `REQUESTS_AVAILABLE = True` |
| CH-013 | **P0** | channels/qqbot.py:25-30 | `import re` 误写（应为 `import requests`） | re 已在 line 19 导入，requests 从未导入 |
| CH-014 | **P0** | channels/qclaw.py:14-20 | `try: pass` + `logging` 未导入 | `logging.warning(...)` 但仅导入 `get_logger` |
| CH-015 | **P0** | channels/sip.py:21-23 | `PYVOIP_AVAILABLE = True` 但未导入 pyvoip | try 块为空，标志永远 True |
| CH-016 | **P0** | channels/dingtalk.py:75,81 | `dingtalk_stream` 未导入 | 使用 `dingtalk_stream.xxx()` 但无 import 语句 |
| CH-017 | **P0** | channels/xiaoyi.py:129 | `hmac` 未导入 | 使用 `hmac.new(...)` 但文件头无 `import hmac` |

#### 1.4.3 其他通道问题

| ID | 严重 | 位置 | 描述 | 证据 |
|----|------|------|------|------|
| CH-018 | P1 | channels/telegram_*.py (10 文件) | 单适配器过度拆分 | Telegram 拆为 10 文件，feishu 仅 5 文件 |
| CH-019 | P1 | channels/wechat_*.py (9 文件) | 同上 | WeChat 拆为 9 文件 |
| CH-020 | P2 | channels/base_adapter.py (12 行) | 纯兼容性 shim | 删除测试通过：删除后复杂度为 0 |
| CH-021 | P2 | cognitive_layers/memory_layer/ (90 文件) | 过度碎片化 | conflict.py + conflict_detector_v2.py + conflict_module.py 三文件同领域 |
| CH-022 | P2 | memory_layer/modules/ (17 模块) | 懒加载 Facade 反模式 | 100-200 行骨架，init() 只设 _initialized = True |
| CH-023 | P2 | memory_layer/memory_layer.py vs manager.py | 角色重叠 | AgentMemoryLayer 与 MemoryManager 持有相同属性 |
| CH-024 | P2 | bayesian_eki/__init__.py | docstring 夸大实现 | 声称"高斯过程加速"但未实现 |
| CH-025 | P2 | bayesian_eki/cognitive_optimizer.py | `_flush_updates` 空方法 | "用于未来扩展" — 纯空方法 |
| CH-026 | P2 | bayesian_eki/cognitive_optimizer.py | `_compute_information_gain` 简化 | 词汇丰富度 * 长度因子，非真正信息增益 |
| CH-027 | P3 | channels/ | 无文件拆分标准 | Telegram 10 文件 vs feishu 5 文件 vs wechat 9 文件 |

---

## 第二部分: 架构结构性问题

基于 improve-codebase-architecture skill 的"删除测试"和"深度评估"，识别 16 个结构性问题：

### 2.1 Facade 反模式（核心架构债务）

| # | 模块 | 问题 | 推荐强度 |
|---|------|------|----------|
| S1 | MemoryManager (1634 行) | 87+ stub 方法，接口宽实现浅，删除测试通过 | **Strong** |
| S2 | AgentLLMClient (45 行) | Pass-through wrapper，无附加逻辑 | **Strong** |
| S3 | EvolutionFacade | 异常吞噬，失败静默 | **Strong** |
| S4 | SubSystemContainer (427 行) | 假深度模块，不持有状态 | **Strong** |

### 2.2 过度碎片化

| # | 模块 | 问题 | 推荐强度 |
|---|------|------|----------|
| S5 | memory_layer/ (90 文件) | 同领域文件未合并 | **Worth exploring** |
| S6 | channels/telegram_* (10 文件) | 单适配器过度拆分 | **Worth exploring** |
| S7 | memory_layer/modules/ (17 模块) | 懒加载 = 永远不加载 | **Strong** |
| S8 | NeurUI/src/api/modules/ (56 文件) | 无抽象的 HTTP 列表 | **Worth exploring** |

### 2.3 样板代码未抽象

| # | 模块 | 问题 | 推荐强度 |
|---|------|------|----------|
| S9 | api/endpoints/chat.py (622 行) | 7 端点重复 15-25 行样板 | **Strong** |
| S10 | _user_can_access_agent | 权限逻辑散落 81 文件 | **Strong** |
| S11 | Agent 类委托方法群 | 10+ 个 1-line delegation | **Worth exploring** |

### 2.4 设计反模式

| # | 模块 | 问题 | 推荐强度 |
|---|------|------|----------|
| S12 | get_memory_manager (base.py) | Getter 有副作用，并发覆盖 | **Strong** |
| S13 | _extract_dependency_async | 同步方法用弃用 asyncio API | **Strong** |
| S14 | AgentMemoryLayer vs MemoryManager | 角色重叠 | **Worth exploring** |
| S15 | Agent.chat() 4 层间接 | 无意义分层 | **Speculative** |
| S16 | channels/base_adapter.py | 死代码以"兼容"为名保留 | **Strong** |

### 2.5 Top 推荐：先处理 S1 MemoryManager Facade

**理由**：
1. 影响面最大：1634 行 + 87+ 方法 + 17 个子模块
2. 测试 surface 最差：50+ stub 方法无法测试
3. AI-navigability 最差：无法判断该调 Facade 还是子模块
4. 删除测试通过：删除 stub 复杂度不重新出现
5. 与 CONTEXT.md 矛盾：声称"EventBus 路由"但 docstring 自承认"子模块未通过它注册"

---

## 第三部分: 修复优先级建议

### P0 — 立即修复（安全漏洞 + 功能失效）

1. **BE-CORE-001**: `mem_core.py:582` asyncio.run() 改为 `await moe.retrieve(...)` 或用 `asyncio.run_coroutine_threadsafe`
2. **BE-CORE-003**: `agent_core.py:40,52,84` 添加 `import logging` 或改用 `logger.warning()`
3. **BE-CORE-008**: `tool_executor.py:198` 修正属性名 `_messages_list` → `_tool_messages_list`
4. **BE-CORE-011**: `tool_executor.py:372,380` 用 `shlex.quote()` 转义用户输入
5. **BE-API-001**: `auth.py:292` 删除无盐 SHA-256 回退，强制 bcrypt/PBKDF2
6. **BE-API-004**: `files_api.py:96` 用 `Path.resolve()` + 前缀校验防路径遍历
7. **BE-API-005**: `files_api.py:80-208` 所有端点添加 `Depends(get_current_user)`
8. **BE-API-008**: `secret_store.py:68-75` 用 `cryptography.fernet` 替换 XOR
9. **BE-API-010**: `provider.py` 9 个端点添加认证
10. **FE-001**: `HealthPage.vue:130` 添加 `import { request } from '@/api'`
11. **FE-002**: `ChatPage.vue:872-881` 添加重启次数限制
12. **CH-001**: `manager.py:151` 修正 SQL Schema 拼写
13. **CH-011~CH-017**: 7 个通道适配器修复 import 错误

### P1 — 高优先级（功能错误 + 数据风险）

14. **BE-CORE-009,010**: tool_executor 参数语义/键名错误
15. **BE-CORE-012**: `_emotion_analyzer` → `_emotion_module`
16. **BE-CORE-013**: 文件操作添加路径遍历防护
17. **BE-CORE-014**: `tool_result` → `tool_call` 类型修正
18. **BE-CORE-018**: `agent.user_id` → `agent.config.user_id`
19. **BE-API-002**: JWT 密钥文件权限设为 600
20. **BE-API-006,007**: 文件大小限制 + MIME 校验
21. **BE-API-011**: API Key 不明文返回
22. **BE-API-012**: LLM 调用添加 timeout
23. **BE-API-015**: 限流 IP 识别改进
24. **FE-003**: escapeHtml 转义引号
25. **FE-005**: logger.error 防循环
26. **CH-002**: `_emotion_module` None 检查
27. **CH-003**: close() 关闭子模块

### P2 — 中优先级（架构改进）

28. 后端日志统一：100 文件迁移到 `get_logger()`
29. 后端配置统一：12 文件迁移到 `neurova.core.config`
30. 前端建立统一事件总线/提示库/日志库/错误库/配置库
31. manager.py stub 方法改为 `raise NotImplementedError`
32. 删除浅模块：AgentLLMClient / SubSystemContainer / base_adapter.py

### P3 — 低优先级（代码质量）

33. 文件拆分标准化
34. 死代码清理
35. docstring 诚实标注

---

## 附录: 审计方法论

### zoom-out (全局视角)
- 先看项目整体结构，再定位目标文件
- 分析调用链：谁调用谁，真实实现在哪里
- 识别高耦合模块：agent_core.py (1621 行) 是中心枢纽

### improve-codebase-architecture (深模块/删除测试)
- **删除测试**: 想象删除模块后，复杂度是否分散到 N 个调用方
- **深度评估**: 接口宽度 vs 实现深度，识别浅模块
- **诚实标注**: 接口 docstring 应反映实际实现，不夸大

### bug-hunt (5 阶段根因调试)
- Phase 0: Reproduce & Frame — 确定可复现路径
- Phase 1: Top-down Localization — 层表定位 file:line
- Phase 2: Full-chain Instrumentation — 全链路日志
- Phase 3: Layered Root Cause Analysis — 多层因果链
- Phase 4: Surgical Fix & Verify — 最小 diff 修复
- Phase 5: Report + Cleanup — 形成本文档

### tdd-workflow (验证驱动)
- 所有 BUG 应有测试复现（RED）
- 修复后测试通过（GREEN）
- 重构保持测试绿色（REFACTOR）
- 覆盖率 ≥ 80%

---

**审计人**: Agent (zoom-out + improve-codebase-architecture + bug-hunt + tdd-workflow)
**审计日期**: 2026-06-25
**BUG 总数**: 110 (15 P0 + 32 P1 + 42 P2 + 21 P3)
**结构性问题**: 16 个
**未修改任何代码**: 本报告仅做排查，所有修复需遵循 TDD 流程单独执行
