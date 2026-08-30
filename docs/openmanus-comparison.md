# OpenManus 代码级对比分析 —— Neurova 可吸收改进清单

> 对比对象：FoundationAgents/OpenManus（原 mannaandpoem/OpenManus，项目已迁移）
> 克隆位置：`E:/项目/_reference/OpenManus`（浅克隆）
> 分析基线：OpenManus 核心 ~11.6K 行 Python；Neurova 后端 550+ 文件

## 一、架构速览

OpenManus 是一个**极简自治 Agent 框架**，继承链 `BaseAgent → ReActAgent → ToolCallAgent → Manus/BrowserAgent/SWEAgent`，外挂 `PlanningFlow` 编排：

```
BaseAgent(状态机 IDLE/RUNNING/FINISHED/ERROR + 停滞检测 + run 循环)
  └─ ReActAgent(think/act 抽象)
       └─ ToolCallAgent(工具调用执行 + 特殊工具终止 + cleanup 协议)
            └─ Manus(工具集合组装) / BrowserAgent(BrowserContextHelper)
PlanningFlow(LLM 用 PlanningTool 建计划 → 逐步路由 executor → 状态标记 → 收尾总结)
LLM(tiktoken TokenCounter + max_input_tokens 预算 + TokenLimitExceeded 不重试 + tenacity 重试)
Sandbox(Docker 容器隔离 shell/文件/浏览器执行)
```

## 二、核心差异总览

| 维度 | OpenManus | Neurova | 结论 |
|---|---|---|---|
| Agent 状态 | 显式状态机 + `state_context` | 隐式（异常+fallback 链） | **吸收 O** |
| LLM 错误 | 分类学：TokenLimit 不重试优雅终止 | 一律包装 RuntimeError 层层 fallback | **吸收 O** |
| 停滞检测 | 检测→注入"换策略"提示闭环 | 检测函数存在但无消费方 | **吸收 O** |
| Token 预算 | tiktoken 精确计数 + 超限闸门 | `len(text)*1.5` 估算，无闸门 | **吸收 O** |
| 任务计划 | PlanningTool（计划即工具）+ PlanningFlow | scheduler 是定时任务，无任务分解追踪 | **吸收 O** |
| 执行隔离 | Docker Sandbox 全套 | LocalExecutor 本机直跑 | **吸收 O**（反向） |
| 记忆 | `Memory = messages 列表` | 17 维分类/温度/结晶经验 | Neurova 强 |
| 治理 | 无 | 防火墙/审计/ASK 审批 | Neurova 强 |
| 流式 | 工具请求强制非流式 | SSE 全链路增量流式 | Neurova 强 |
| 渠道/持久化 | 无 | 14 渠道 + 会话持久化 | Neurova 强 |

## 三、可吸收改进点（按优先级）

### P1：Agent 执行状态机 + `state_context`（结构性根治 fallback 掩盖类 bug）

**OpenManus**（`app/agent/base.py:50-74, 100-135`）：
- `AgentState` 枚举：IDLE/RUNNING/FINISHED/ERROR（`app/schema.py:34-40`）
- `state_context(new_state)` 异步上下文管理器：进入设状态，**异常转 ERROR 并上抛**，finally 恢复前态
- `run()` 主循环只在 `state==IDLE` 时可启动，`FINISHED`/`max_steps` 双条件退出

**Neurova 现状**：`chat_pipeline._call_agent_loop`（chat_pipeline.py:953-963）失败后静默 `_call_legacy` fallback——2026-08-29 实测中 LLM 限流错误被 fallback 链层层转译，最终以无关的 TypeError 面目出现（当日已修的 `_call_legacy_stream` bug 即此风格的产物）。

**落地方案**：
1. `neurova/agent/` 新增 `agent_state.py`：`AgentState` 枚举 + `state_context` 异步上下文管理器（照抄语义，~40 行）
2. `ChatPipeline._step_llm_call` 用 `state_context(RUNNING)` 包裹 Agent Loop 调用
3. **fallback 必须携带原因**：`_call_legacy(ctx, reason: str)`，fallback 决策与原因写入 `ctx` 供日志/SSE 透出——禁止静默降级

**收益**：错误不再变形；前端能区分"正常完成 / 达到步数上限 / 执行出错"。

### P2：LLM 错误分类学 + 优雅终止

**OpenManus**（`app/llm.py:690-700, 749-766` + `app/agent/toolcall.py:45-63`）：
- `TokenLimitExceeded` 单独异常类，tenacity 重试策略**显式排除**它
- `think()` 捕获后：写一条 assistant 消息（"token 上限 reached, cannot continue"）→ `state = FINISHED` → 优雅收尾
- 其他异常才走重试

**Neurova 现状**（llm_client.py:235-247）：RateLimitError/认证/连接错误一律包装 `RuntimeError` 抛出，无重试策略区分、无终止语义。今日限流事故即此。

**落地方案**：
1. `llm_client.py` 定义异常分类：`TokenLimitExceeded`（不重试）、`RateLimitError`（可退避重试 N 次）、`AuthError`（直接失败）
2. `chat_pipeline` 捕获 `TokenLimitExceeded` → 向用户流式输出明确原因 → 本轮**优雅终止**（不是错误）
3. RateLimit 加指数退避重试（OpenManus tenacity 等价物可用简单 asyncio.sleep 循环）

### P3：停滞检测 → 提示注入闭环（改动最小、收益直接）

**OpenManus**（`app/agent/base.py:137-165`）：
- `is_stuck()`：统计最近 assistant 消息与最后一条相同内容的次数，`>= duplicate_threshold(2)` 判定卡死
- `handle_stuck_state()`：向 `next_step_prompt` **前插**"Observed duplicate responses. Consider new strategies..."——下一轮 LLM 自动换策略

**Neurova 现状**：`agent_loop_detection.py` 的 `has_repeated_patterns`/`detect_content_loop` 已实现，`agent_core.py:1547-1557` 有委托方法——**但全仓库无调用方**（死代码）。工具轮次循环靠 `openai_loop._tool_rounds <= 10` 硬上限截断，截断时用户只看到莫名截断。

**落地方案**：
1. `openai_loop._predict_stream` 工具轮循环内，每轮用 `detect_content_loop` 检查最近 assistant 内容
2. 检测命中 → 向下一轮 messages 注入一条 user 提示："检测到重复响应，请更换策略避免重复无效路径"（OpenManus 措辞可直译）
3. 连续 2 次停滞 → 终止并向用户说明原因（而非静默截断）

### P4：Token 预算闸门

**OpenManus**（`app/llm.py:45-171, 229-265`）：
- `TokenCounter`：tiktoken 精确计数，含**图片 token**（按宽高分档计算）与**工具定义 token**（工具 schema 也占预算）
- `check_token_limit()`：请求前检查 `total_input_tokens + input_tokens <= max_input_tokens`，超限抛不重试异常

**Neurova 现状**（llm_client.py:598-613）：`count_tokens = len(text) * 1.5`（注释自认"实际应该使用 tiktoken"）；无请求前预算检查；上下文裁剪靠 memory 层的经验规则。

**落地方案**：
1. `llm_client.count_tokens` 换 tiktoken（venv 补装），保留估算作 fallback
2. `LLMConfig` 加 `max_input_tokens`；`chat/chat_stream` 请求前统计 messages + tools schema token，超限抛 `TokenLimitExceeded`（接 P2 的优雅终止）
3. `context_compressor` 的触发条件从经验规则改为 token 预算驱动

### P5：PlanningTool——"计划即工具"（补齐长任务能力）

**OpenManus**（`app/tool/planning.py` + `app/flow/planning.py`）：
- 计划是结构化数据：`steps` / `step_statuses`（not_started/in_progress/completed/blocked 枚举 + 状态符号 [✓][→][!][ ]）/ `step_notes`
- **计划由 LLM 经工具调用创建/更新**（7 个子命令：create/update/list/get/set_active/mark_step/delete）
- `PlanningFlow` 循环：取第一个非完成步 → 按步类型路由 executor（步文本里 `[AGENT_NAME]` 标记）→ 注入"当前计划状态+本步任务"提示 → 完成打标 → 全部完成后 `_finalize_plan` 总结
- 每步执行前把**计划全文状态**注入提示——executor 始终知道全局进度

**Neurova 现状**：scheduler 是定时任务（cron 语义）；swarm 多智能体无任务级分解-追踪；长任务只能靠单轮对话硬扛，中断即丢失进度。

**落地方案**：
1. 新增 `neurova/tools/planning_tool.py`：移植 PlanningTool 的 7 命令语义，但**计划持久化到 SQLite**（OpenManus 是进程内 dict，重启即失——Neurova 必须用自身强项反超）
2. 挂入 builtin_tools，LLM 即可在对话中创建/推进/查询计划；会话恢复时计划自动还原
3. 二期再接 PlanningFlow 式逐步执行循环（复用 swarm 路由）

### P6：沙箱执行后端（已完成 2026-08-29，含现状修正）

**现状修正**：初版报告称"Neurova 无沙箱"不准确。核实后 Neurova 已有：`neurova/sandbox/exec_sandbox.py`（内核级沙箱，Linux bubblewrap / macOS Seatbelt / Windows AppContainer 占位，四级强度）并接入治理闭环（SANDBOX 判定）；`execution_layers.DockerExecutor` 容器执行器。真实缺口是 **Windows AppContainer 为占位（本机即 Windows，治理 SANDBOX 判定实际裸跑）** 与 **默认执行路径未接入容器隔离**。

**已实施**：
- `exec_sandbox` 新增 `execute_in_sandbox_async`（治理判定 async 通道）与 `docker_available` 探测；`backend="docker"` 强制容器、`"auto"` 在需要隔离且 Docker 可用时优先容器（跨平台真隔离），否则回退平台后端；`tool_executor` 治理 SANDBOX 分支已切换
- `computer_use.shell` 支持 `runtime_type="docker"`（经 RuntimeFactory，与 skill_system 同源）
- 沙箱 argv 化改造：`wrap_argv` + `shell=False`（命令作为单个 argv，消除引号转义层与 shell=True 注入面）

**遗留**：OpenManus 的常驻容器形态（terminal/files/browser 复用同一容器、有状态延续）仍可借鉴——当前 Neurova 的 `docker run --rm` 为一次性容器，无状态但更干净。

### P6（原稿，留档）：Docker 沙箱执行后端

**OpenManus**（`app/sandbox/`，sandbox.py 462 行）：Docker 容器内执行 shell/文件操作/浏览器，带超时、输出限制、清理。而其 `BaseTool.cleanup()` 协议（toolcall.py:245-260，工具实现 cleanup 协程则 run 结束统一调用）保证资源回收。

### P7（低优）：BrowserContextHelper 模式

OpenManus（`app/agent/browser.py:19-80`）每步**主动**把浏览器状态（URL/标题/tab 数/上下滚动余量/截图）格式化进 next_step_prompt，而非等 agent 自己调工具查。Neurova 的 aria 快照体系刚建成，可在浏览器相关会话中把"最新快照摘要"自动注入下一轮提示，减少一次工具往返。

## 四、不建议照搬

- **Memory=list**：OpenManus 无记忆压缩/检索，长会话直接爆上下文——Neurova 记忆体系是代差优势
- **工具请求强制非流式**（llm.py 注释 "Always use non-streaming for tool requests"）：Neurova 全链路流式是核心体验
- **进程内计划存储**：Neurova 移植 PlanningTool 时必须换 SQLite
- **单 LLM 双实例**：Neurova 多供应商路由更完善

## 五、建议实施顺序

P3（半天，死代码激活）→ P2（1 天，错误分类+优雅终止）→ P1（1-2 天，状态机重构，改动面最大需回归）→ P4（半天）→ P5（2-3 天，含 SQLite 持久化）→ P6（视需求）。
每项按既定纪律：先写红测试，再实现，回归全绿后交付。
