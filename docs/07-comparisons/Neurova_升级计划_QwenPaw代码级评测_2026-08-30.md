# Neurova 升级计划 — 基于 QwenPaw 2.2.0-beta.3 代码级评测（v2）

> 评测日期：2026-08-30
> 评测方法：**纯代码级**（五路并行深度扫描 + MCP 专项复扫），只读 `.py/.ts/.vue/.toml/.yml/.json`，未参考任何文档。
> 对比对象：`E:/项目/QwenPaw-2.2.0-beta.3`（926 个 Python 文件）vs `E:/项目/Neurova/neurova`（681 个 Python 文件，约 14.8 万行）。
> 历史文档（`Neurova_vs_QwenPaw_对比分析.md` 等）为文档层面对比，本篇以其代码证据为准，替代结论。
> **执行层**：实施步骤（TDD 红测/文件/验证/回滚）见 [plans/neurova-upgrade-p0-p1-implementation-steps.md](plans/neurova-upgrade-p0-p1-implementation-steps.md)。

---

## 0. ⚠️ 复扫新发现的高危项（P0，立即处理）

**未认证 RCE：`neurova/api/endpoints/tool_layers.py`**
- `tool_layers.py:27` `router = APIRouter()` **无 `dependencies=[Depends(get_current_user)]`**，挂载点 `api/endpoints/__init__.py:278` 也未注入。
- `POST /api/v1/tool-layers/mcp-servers`（`tool_layers.py:122-148`）接受任意 `command + args + env` 并直接 stdio spawn → **未认证攻击者可在服务器上执行任意进程**。
- 同路由族还暴露内网 SSRF：sse/http 的 `url` 无私网/loopback 校验。
- 对照：`shared_config.py:18` 的另一套 CRUD 是有鉴权的（但存储分叉）。
- **修复**：路由器加鉴权依赖；stdio command 加白名单校验（或复用 governance 预检）；http url 接 `web_reach/reach.py` 已有的 `_assert_public_host`。

---

## 1. 总评分矩阵

| 维度 | QwenPaw | Neurova | 说明 |
|---|---|---|---|
| Agent 循环与工具编排 | 8.0 | 7.5 | QP：ToolCoordinator 超时转后台；NV：三通道并存、串行 |
| 上下文窗口工程 | **9.5** | 5 | QP 八阶段压力管线；NV 无溢出管理，最大差距 |
| 记忆系统 | 8.5 | 8 | QP 检索工程强（真向量+BM25 RRF）；NV 生命周期强（温度/睡眠/肌肉） |
| 技能/工具生态 | 8.5 | 6 | QP：SKILL.md hub/market+扫描器；NV：有注册表无生态 |
| **MCP 集成（复扫）** | **7.5** | **4.5** | 详见 §3 |
| LLM 供应商层 | 9 | 7 | QP：Retry→Fallback→RateLimit 三层装配；NV 双抽象未合一 |
| 循环门控/模式 | 8.5 | 5 | QP StopGate 三态 + 5 模式；NV 仅 auto-continue |
| 检查点/回滚 | **9** | 2 | QP 裸 git 快照三档恢复；NV 无 |
| 安全纵深 | 8.5 | 6.5 | QP 5 种真沙箱+AST 解析；NV Windows 占位、默认 NONE、**MCP RCE** |
| 测试工程 | 8.5 | 5 | QP 10672 真 e2e/契约；NV 8837 单测但 e2e/perf 空壳 |
| CI/CD | 8 | 4 | QP 31 workflows+CodeQL；NV 2 jobs |
| 可观测性 | 5 | 4 | 双弱 |
| 代码组织 | 7 | 4.5 | QP 核心拆分好；NV 上帝对象+275 单例 |
| 前端/多用户 | 7 | 7.5 | NV 多用户三级隔离是 QP 没有的 |
| **综合** | **7.8** | **5.8** | |

**定位差异**：QwenPaw 是单用户本地桌面 Agent（Tauri 壳）；Neurova 是多用户服务平台。QP 约一半核心设计可直接移植，另一半（单用户假设、desktop 治理）不适配。

---

## 2. QwenPaw 核心亮点（代码实证索引）

1. **上下文八阶段压力管线** `agents/context/scroll/manager.py`（2025 行）：wire-format 精确 token 计数 → 写穿 SQLite(WAL+FTS5) → 折叠已完成轮 tool result → 配对安全切分 → LLM 增量摘要 → 驱逐索引 → 活跃折叠 → 超限抛错重试。驱逐内容不丢（索引 stub + `recall_history()` 召回指令）；"已读才折叠" ack 集；400 溢出单次恢复重试。
2. **检查点 = 裸 Git 仓库** `checkpoints/`：`repository.py:262` write_workspace_tree + commit-tree；`refs/auto|snap|pre-restore`；三档恢复（对话/对话+记忆/对话+文件）；恢复前自动留档 + GC + quiesce。
3. **停止门控** `loop/gates/`：BYPASS/INTERRUPT_AND_CONTINUE/TERMINATE 三态；DoomLoopGate 滑动窗口相似度；Token/迭代/超时预算门；goal/mission/custom_loop（声明式编译）复用同基类。
4. **工具协调器** `tool_calls/_coordinator.py`：超时**不杀而 offload 后台**、立即给 LLM 返回提示；per-tool 超时注册表（shell 60s/grep 30s）。
5. **供应商三层装配** `agents/model_factory.py:2053-2165`：RetryChatModel（Retry-After、指数退避、供应商检疫、流式 idle 超时）→ FallbackChatModel（按错误类别切换）→ LLMRateLimiter；35 家供应商；流式 chunk 消毒 + 畸形 tool-call 修复。
6. **安全纵深**：4 平台 5 种真沙箱（Seatbelt/bwrap/Landlock/AppContainer×2）；tool_guard 三层（YAML 签名 + 双规范路径守护 + 手写 AST shell 逃逸解析）；技能安装强制扫描（中英双语 prompt-injection 签名 743 行 YAML）；**诚实机制** `report_unenforced_config()`——未强制的安全边界字段 WARNING 上报，约束绝不静默丢弃。
7. **测试/CI**：10672 测试函数、每渠道契约测试、8-shard 集成、31 workflows、py3.11/3.13 matrix、CodeQL 分阶段。

## 2b. Neurova 独有底牌（不可丢）

1. **记忆生命周期**：温度引擎（Ebbinghaus 分段+贝叶斯遗忘+固化，`temperature.py`）、五阶段睡眠+空闲整理链（`idle_tracker.py`）、肌肉记忆三层晋升（`muscle_memory.py`）——QP 只有 daily/digest/dream。
2. **多用户三级隔离**（ContextVar agent/neuser/user 贯穿 SQL 强制 WHERE）——QP 无用户概念。
3. **RSI/进化闭环**（13 文件 6600 行非骨架）+ 认知层四件套——QP 无。
4. **前端**：59 页面、11 语言键级一致性守护、58 个全类型化 API 模块、590 vitest 用例。

## 2c. Neurova 关键短板

1. 上下文窗口管理有骨架无闭环（活水池详见 §4.1：无溢出恢复、压缩是伪摘要/字符截断、驱逐台账内存态重启即丢、token 靠字符比例估算、模型预算表硬编码过时）；2. 无检查点；3. 工具执行三通道并存且全串行；4. 语义召回是假向量（`manager.py:730-776` 每次重建关键词索引；肌肉记忆"向量指纹"= MD5，而 `UnifiedVectorStore` 的 faiss/fastembed/ONNX 后端已存在未接入）；5. Windows 沙箱占位且默认 NONE；6. CI 仅 2 jobs、e2e/perf 空壳、依赖不锁版本；7. Agent 上帝对象（35 属性 + 275 单例 + 40+ property 反向代理）；8. 双 LLM 抽象未合一；9. MCP 层半成品（§3）。

---

## 3. MCP 专项复扫结果（QwenPaw 7.5 vs Neurova 4.5）

### 3.1 对比总表

| 能力 | QwenPaw | Neurova |
|---|---|---|
| 传输 | stdio + sse + streamable_http（手写客户端，协议深度罕见） | stdio + sse + http（官方 SDK 包装） |
| 重连/退避/熔断 | 指数退避 1→60s+抖动、熔断 5 次半开 300s 探测、专任务 lifecycle | **全缺**（零重连、零熔断、零健康探测） |
| 心跳/僵尸检测 | 无主动 ping，但 RPC watcher/drain/reaper 兜底 | 无 |
| OAuth | PKCE S256 + RFC 9728/8414/7591 发现 + token 加密落盘 + 到期前 300s 主动刷新（但有"刷新到不了已烘焙头部"缺陷） | **无**（仅静态 headers） |
| 工具桥接 | schema 兜底 + content blocks 归一化（图片/资源）+ 名字净化 | SDK inputSchema 直通 + `mcp.{server_id}.{tool}` 命名空间（已落地，有测试锁定） |
| 缓存 | 三层缓存 + 重连窗口降级返回 + 10s TTL | 连接期一次性快照，无 TTL、无 `tools/list_changed` |
| 治理 | 每工具 policy（特异性排序，deny>ask>allow）+ 审批闸 + STRICT 模式 | 四裁决存在但 MCP 参数键名白名单提取易绕过；路由路径绕过防火墙；治理缺失 fail-open |
| 服务端能力 | ACP server + per-session MCP 注入（原子换装/回滚） | 无 MCP server 暴露 |
| 配置 | Console 全 CRUD + 双时代迁移 | **两套 CRUD 分叉存储**，其一无鉴权（RCE） |
| 凭据 | 加密 YAML + repr 全打码（但 headers 烘焙后刷新失效） | env/headers 明文 JSON；env 掩码但 **headers 不掩码** |
| 隔离 | 按 workspace/session 隔离 | **全局单例跨用户共享**（防火墙用首个 user_id） |

### 3.2 Neurova MCP 缺口清单（按危害排序）

| # | 问题 | 位置 | 危害 |
|---|---|---|---|
| M1 | MCP 管理 POST 无鉴权 → 任意进程 spawn | `tool_layers.py:27,122-148` | **未认证 RCE** |
| M2 | stdio command/args/env 无白名单校验 | `mcp_config.py` | 同上（加鉴权后降为"配置者 RCE"，仍需收敛） |
| M3 | ToolRouter 主路径 `call_tool()` 绕过防火墙 | `tool_router.py:525-529` vs `mcp_client.py:314-342` | 防火墙形同虚设 |
| M4 | 治理预检只提取 `command/code/file_path/path` 四个键名 | `tool_executor.py:745-755` | MCP 工具换键名即静默放行；治理模块故障 fail-open（:739-740） |
| M5 | `get_mcp_client(user_id)` 单例跨用户共享会话 | `mcp_client.py:471-476` | 多用户隔离破坏（与 NV 核心卖点冲突） |
| M6 | 零重连/退避/熔断/健康探测 | `tool_layers/` 全目录 | server 崩溃后永久 disconnected，每次调用吃满 timeout_ms |
| M7 | 两套 CRUD 分叉存储（shared_config.json vs 内存 dict） | `shared_config.py:181-245` vs `tool_layers.py:108-197` | 配置不一致；POST 直入内存不走校验 |
| M8 | 工具同步 ToolEngine 为死代码（新建即弃实例） | `mcp_client.py:419-465` | API 侧永远看不到 MCP 工具 |
| M9 | neurflow 键名 bug：读 `server` 写的是 `server_id` | `adapters.py:314` vs `mcp_client.py:279` | 所有 MCP 节点 server 名恒为 "default"，无测试捕获 |
| M10 | env/headers 明文落盘；headers 不掩码 | `shared_config.py:33-40` | 凭据泄漏 |
| M11 | 遗留层三套死代码（mcp_manager/mcp_client_manager/schemas） | `execution_engine/` | 维护噪音 |
| M12 | 传 `streamable_http` 被 400 拒绝但文档这么写 | `tool_layers.py:55` vs `mcp_config.py:27` | 文档/实现不一致 |

### 3.3 从 QwenPaw 值得移植的 MCP 模式

1. **熔断+退避 lifecycle**（`mcp_stateful_client.py:221-368`）：单后台 task 管理 AsyncExitStack、1→60s 抖动退避、5 次熔断/300s 半开探测、断连窗口内 list_tools 降级返回缓存。
2. **调用不做同会话重试**（`:582-583`）——避免副作用重复，at-least-once 语义自觉。
3. **白名单要在暴露链执行**：QP 也没做好（白名单仅展示不执行），但方向正确——Neurova 修复 M3/M4 时应在 `list_capabilities`/`register_mcp_client` 处按配置过滤。
4. **同步教训**：QP 的"凭据烘焙进 headers 后刷新失效"（`mcp.py:68-98` + `:124-125`）是前车之鉴——Neurova 做 OAuth 时凭据解析必须发生在每次调用时，不能连接期一次性烘焙。

### 3.4 修正后的 MCP 评分

- QwenPaw：**7.5**（协议 7 / 可靠性 8 / 安全治理 7 / 生态 7.5）——三个实锤缺陷：凭据烘焙致 token 轮换失效、stdio 读超时声明未传参（`stateful:958-963`）、白名单不执行。
- Neurova：**4.5**（协议 6 / 可靠性 4 / 安全治理 3 / 生态 5）——8 月底改造在命名空间与失败可观测性上确实落地，但可靠性与安全闭环只完成一半，且存在 M1 高危项。

---

## 4. 升级计划

### P0 — 立即（本周）

| # | 事项 | 动作 | 预估 |
|---|---|---|---|
| P0-1 | **M1 RCE 修复** | `tool_layers.py:27` 路由器加 `dependencies=[Depends(get_current_user)]`；`mcp_config.py` 对 stdio command 做白名单/绝对路径校验；http url 接 `_assert_public_host` | 0.5 天 |
| P0-2 | M3+M4 治理穿透 | `call_tool` 路径接防火墙；`_governance_precheck` 对 MCP 工具改为全参数扫描或注册时标注敏感参数键；治理故障改 fail-closed（至少对 MCP 工具） | 1 天 |
| P0-3 | M5 用户隔离 | client 按 `(user_id, server_id)` 建 session 租约，或 per-user client 池；防火墙校验取当前请求 user_id | 1-2 天 |
| P0-4 | M7+M10+M12 配置收敛 | 两套 CRUD 合一到 tool-layers（带鉴权+校验），shared_config 做兼容读取；headers 掩码；`mcp_config.py` 接受 `streamable_http` 别名 | 1 天 |
| P0-5 | M8+M9 死路与键名 bug | 删除 `_sync_tools_to_engine` 死代码（或接真单例）；`adapters.py:314` 改读 `server_id` 并补一条回归测试 | 0.5 天 |
| P0-6 | CI 底座 | 加 ruff lint、pytest unit matrix (3.11/3.12)、coverage 门禁（fail_under=30 起）、前端 job（vue-tsc+vitest+eslint）、CodeQL（dry-run 起步）；`uv pip compile` 锁依赖 + pip-audit | 1-2 天 |

### P1 — 高优（2-6 周）

| # | 事项 | 动作 | 预估 |
|---|---|---|---|
| P1-1 | **上下文 Scroll 管线**（基于现有活水上下文池补齐，**不新建 context_engine**，详见 §4.1） | 四期：① 轮次化+配对完整性+溢出恢复 → ② 精确 token 计数+动态预算 → ③ 真 LLM 摘要+驱逐台账 SQLite 持久化 → ④ tool_result 生命周期+已读 ack 集 | 1200-1600 行，4 期 |
| P1-2 | **工具执行协调器** | 三通道并一（loop 原生/文本兜底/肌肉记忆走同一 entry）；`asyncio.gather` 并行独立调用；per-tool 超时注册表；超时 offload 后台不硬杀；删或收窄正则兜底 | 800-1200 行 |
| P1-3 | **MCP 可靠性**（对标 mcp_stateful_client.py） | 子进程退出监听+指数退避重连+熔断半开；连接期断线时 list_tools 降级返回缓存；call_tool 不做同会话重试；`tools/list_changed` 处理或 TTL 缓存 | 600-900 行 |
| P1-4 | **停止门控** | 新建 `neurova/agent/gates/`：DoomLoopGate（升级 `_auto_continue` 的 0.8 相似度检测+args-hash）、TokenBudgetGate、IterationGate；挂 `loops/base.py` 每轮后 | 600-900 行 |
| P1-5 | **检查点**（对标 checkpoints/） | 裸 git 仓库方案（零新依赖）：会话 JSON + 知识库文件快照；`refs/{auto,snap,pre-restore}`；三档恢复先做"对话"+"对话+文件"；记忆库二期 | 800-1200 行 |
| P1-6 | Tool Guard + 技能扫描 | 移植 YAML 危险命令签名库、shell 逃逸 AST 解析器（`$()`/引号状态机/-exec）、双语 prompt-injection 签名（接 NL 工具合成与技能安装） | 2000 行 |
| P1-7 | 沙箱诚实化 | Windows AppContainer 真实现或明确降级上报（抄 `report_unenforced_config()`）；bash/文件写默认 severity 提到 NETWORK_OFF；SSRF 抽成全局出网代理层 | 3-5 天 |
| P1-8 | 测试去水分 | e2e 层填真测试（后端拉起+API 探活+关键链路，模板：QP `test_hub_local_runtime.py`）；performance 层填真断言或删目录；前端 coverage 阈值 | 2-3 天 |

### §4.1 P1-1 展开方案 —— 基于现有活水上下文池（2026-08-30 修订）

**修订原因**：最初版 P1-1 计划"新建 `neurova/context_engine/` 照搬 QwenPaw scroll"。深入现有代码后发现 Neurova 已有一套架构定位相同的**活水上下文池**（4536 行），且"池=永久归档、容量控制只在视图层"的核心语义与 QP scroll 一致，驱逐台账（方案 P1-2.2）已有部分实现。正确做法是**在现有组件上补六块短板**，而不是并行建第二套上下文系统。

#### 现状盘点（代码实证）

| 组件 | 位置 | 现状 |
|---|---|---|
| ContextPool | `context_pool.py`（439 行） | 池=永久归档（`add_context` 不再按 max_size 驱逐，`context_pool.py:146-149` 注释明示）；`query()` 当前 session 优先；驱逐台账 `_eviction_ledger`（内存有界 500 条）+ `recall_evicted()`（`context_pool.py:244-278`）；三级隔离键 `user:agent:session`；RLock 并发保护 |
| 语义取水器 | `context/semantic_drawer.py`（213 行） | 视图层选择器：相关性门槛 0.55（向量+关键词统一刻度）、**整条选取不切片**、created_at 稳定排序保 LLM 前缀缓存（`:127`）、向量接 UnifiedVectorStore 降级关键词 |
| 压缩器 | `context/compressor.py`（77 行） | **伪实现**：`enable_summarization=False` 时硬截断，=True 时 `[摘要] content[:max//2]` 字符截断（`:53-71`）；`ContextFacade.compress_context` 也是 1 token≈4 chars 截断（`context_facade.py:195-241`） |
| Token 估算 | `context/token_estimator.py`（231 行） | 统一了 4 处不一致估算（做得好），但全是**字符比例估算**（中文 1.5/词 0.25），非 wire-format 精确计数 |
| 编排接线 | `context/orchestrator.py`（1010 行） | `build_context()` 把 user/memory/experience/emotion `add_context()` 进池 → `draw(need=user_input)` 调取（`:477`）；conversation_history 仅 fallback 且不更新（`:353`）；挂 `ContextFacade`（按 agent_id 单例，C-4 修复） |
| 注册表/设置 | `context_pool_registry.py`、`api/endpoints/context_pool_settings.py` | 按 (user,agent,session) get_or_create；pool-settings 已有 GET/PUT API + token-budget 查询 + test-budget 端点 |

#### 差距映射：QP 八阶段 ↔ 活水池

| QwenPaw 能力 | 活水池对应 | 缺口 |
|---|---|---|
| 精确 wire-format token 计数（`model.count_tokens`） | TokenEstimator 字符估算 | **精确策略缺失**；触发阈值/硬上限无计算（QP: trigger_ratio×context_size − output_reserve） |
| 八阶段压力管线（折叠→切分→摘要→索引→活跃折叠） | Drawer 整条选取 + Compressor 伪摘要 | **无摘要压缩**、无切分配对保护、无分阶段压力递进 |
| 配对安全切分 + 孤儿 tool_result 三重清理 | chunk 平铺无轮次概念 | **无 turn_id/配对完整性**；tool_result 生命周期无管理 |
| 溢出单次恢复重试（400→compress→rebuild） | 无 | **无溢出恢复链路**（`loops/openai_loop.py` 400 直接报错） |
| HistoryStore SQLite WAL+FTS5 + EvictionIndex 渲染 | `_eviction_ledger` 内存 list 500 条 | **重启即丢**；无 FTS5 检索；`recall_evicted` 仅子串匹配 |
| 模型上下文窗口基线（capability_baseline.py） | `get_token_budget_for_model` 硬编码字典（gpt-4 32k/claude-3 200k） | **过时**，未接 provider_manager 模型元数据 |

#### 四期实施方案（全部落在现有组件上）

**第①期：轮次化 + 溢出恢复（止血，最高优先）**
- `ContextInput.metadata` 增加可选 `turn_id` / `pairs_with`（tool_call_id 关联）；orchestrator 写入 CONVERSATION/TOOL_CALL chunk 时打标。
- 新增 `Orchestrator.validate_pairing(view)`：draw 调取后的视图做配对完整性校验——孤儿 tool_result 丢弃或补占位，user/assistant 断链修复（对标 QP split 后清理语义）。
- 溢出恢复：`loops/openai_loop.py` 的 400 context-length 错误分支改为调用 `orchestrator.recover_from_overflow(session)`——按 Drawer 逐条降级（先剔低分非对话 chunk → 再折叠最旧轮次 → 重建消息重试一次）。QP 的"只重试一次"语义照搬，防循环。
- 约束：不改 `add_context` 永久归档语义；不改隔离键。

**第②期：精确 token 计数 + 动态预算**
- TokenEstimator 加 `EXACT` 策略：优先走 provider 的 count_tokens 接口（QP 用 `agent.model.count_tokens(**prepare_model_input)` 同款思路），退路 tiktoken，再退字符估算。挂点：Drawer 预算计算与 orchestrator 触发阈值。
- 删 `get_token_budget_for_model` 硬编码表，改从 provider_manager 的 ModelInfo/context_windows 元数据取，取不到回落现有 API 默认值；`context_pool_settings.py` 的 token-budget 端点返回值来源同步切换（响应形状不变，前端零改动）。
- 触发阈值可配置化：`pool-settings` PUT 增加 `trigger_ratio`（默认 0.85）与 `output_reserve`（默认 4096）。

**第③期：真摘要压缩 + 台账持久化**
- 替换 Compressor 伪摘要：新增 `SummarizingCompressor`——对被折叠的已完成轮次批量调用 LLM 生成/增量更新 `ContinuationSummary`（QP `scroll/manager.py:563-570` 语义：60s 超时、失败保留旧摘要、summary 走 secret redaction）；摘要结果作为高优先级 chunk 回写池（来源枚举新增 `SUMMARY`），原 chunk 保留在池（归档无损语义不破坏——压缩只影响视图组装）。
- `_eviction_ledger` 从内存 list 换 SQLite：WAL + FTS5 表（列含 user_id/agent_id/session_id/turn_id/content/evicted_at），`recall_evicted()` 接口签名不变、实现改 SQL 检索；**多用户分区沿用 `_PersistDbStore` 强制 WHERE 模式**（mem_core.py:88-97）。`recall_history` 注册为 agent 工具（对标 QP recall_tool），命名走 ToolRouter 既有注册链。
- 体积控制：FTS 台账按 keep_days/keep_count GC（QP policy.py 同款参数）。

**第④期：tool_result 生命周期 + 已读 ack 集**
- TOOL_CALL chunk 增加 `seen_confirmed` 标志（"已被成功模型请求读过"）；只有已确认的 tool result 才进入第③期折叠候选——防止模型还没看到的工具结果被折叠导致幻觉（QP `_seen_tool_result_ids` ack 语义，`scroll/manager.py:121,275-282`）。
- 分层剪枝钩子：draw 视图超预算时按优先级序列折叠（旧轮 tool result → 老记忆 chunk → 低分经验），对标 QP ToolResultPruningMiddleware 的分层语义。

#### 验收口径

- 长会话压测（100+ 轮含工具调用）不出现 400 溢出，或溢出后自动恢复成功率 100%（单次重试语义）。
- 视图 token 与真实请求 token 偏差 ≤5%（EXACT 策略生效后）。
- 重启后 `recall_evicted`/`recall_history` 可召回重启前被折叠内容（FTS 检索命中）。
- 现有 context pool 测试与 `pool-settings` API 契约零破坏（前端零改动）。

### P2 — 架构还债（随迭代）

| # | 事项 | 动作 |
|---|---|---|
| P2-1 | 记忆检索真实性 | `_semantic_recall` 接 `UnifiedVectorStore`（faiss→fastembed→ONNX 链已有）；混合 RRF（向量 0.7+BM25 0.3）；肌肉记忆 MD5 换真 embedding；关键词索引持久化；向量空间指纹（换模型自动标记重建） |
| P2-2 | LLM 层合一 | 以 `providers/types.py` 契约合并两套抽象；抄 Retry→Fallback→RateLimit 三层装配；逐步换原生 async SDK |
| P2-3 | 拆上帝对象 | agent_ref property 代理收窄成显式接口；275 个 `get_*` 单例收敛进容器注册表；渐进做，不大爆炸重写 |
| P2-4 | 可观测性 | structlog 替换 stdlib formatter；清 121 处 print；prometheus_client 替换手拼 /metrics；抄 `TokenRecordingModelWrapper`（热路径同步 enqueue+后台 flush）做 per-turn token 对账；补成本核算（模型定价目录→成本汇总） |
| P2-5 | 循环模式 | goal/mission/custom_loop 模式系统（P1-4 门控就位后再做）；`_reload_driver_best_effort` 类死代码清理 |
| P2-6 | MCP OAuth | 授权码流 + PKCE + 到期前主动刷新；**凭据解析必须在每次调用时**（QP 烘焙教训）；token 加密落盘复用现有 `secret_store.py` AES-256-GCM |
| P2-7 | 遗留清理 | 删 `execution_engine/mcp_manager.py`、`mcp_client_manager.py`（零消费方）、`tool_layers/schemas.py` 未接部分；`tokenizer/`（QP 侧 12MB 死资产引以为戒） |

### 里程碑

```
第 1 周      P0 全部（安全止血 + CI 底座）          → 高危清零，门禁生效
第 2-3 周    P1-1 上下文管线①② + P1-2 协调器       → 长会话可用，工具并行
第 4-5 周    P1-1③④ + P1-3 MCP 可靠性 + P1-4 门控  → 执行架构对齐 QP
第 6-8 周    P1-5 检查点 + P1-6/7/8                 → 安全纵深补齐
之后按迭代   P2 各项（每项独立可交付）
```

### 核心判断

Neurova 不需要重写。执行架构层"补三块板"（**上下文管线、检查点、门控**），MCP 层补可靠性与安全闭环，同时把独有优势（记忆生命周期、RSI、多用户隔离）的工程实现补真（假向量、假 e2e、单例穿透）。QP 基于 agentscope 的架构形态（Protocol 注入+事件流）不可照搬，但算法与语义（八阶段管线、裸 git 快照、gate 三态决策、熔断退避、超时转后台）全部可直接移植。

---

## 附录：证据文件索引

- QwenPaw：`src/qwenpaw/agents/context/scroll/manager.py`、`checkpoints/{repository,service,restore,policy}.py`、`loop/gates/{base,handler,runner,doom_loop}.py`、`tool_calls/{_coordinator,_middleware,_hooks}.py`、`agents/model_factory.py`、`sandbox/`、`security/{tool_guard,skill_scanner}/`、`drivers/handlers/{mcp,mcp_stateful_client,mcp_streamable_http}.py`、`drivers/credentials/`、`app/routers/mcp_oauth.py`、`agents/acp/{server,session_mcp}.py`
- Neurova：`agent_core.py`、`agent/chat_pipeline.py`、`tool_executor.py`、`agent/loops/{base,openai_loop}.py`、`cognitive_layers/memory_layer/{manager,temperature,sleep}.py`、`muscle_memory.py`、**`context_pool.py`、`context/{context_facade,orchestrator,semantic_drawer,compressor,token_estimator,pool_models}.py`、`context_pool_registry.py`、`api/endpoints/context_pool_settings.py`**、`llm/{provider_manager,multi_model_client}.py`、`api/{auth,deps}.py`、`api/endpoints/tool_layers.py`、`api/endpoints/shared_config.py`、`tool_layers/{mcp_client,mcp_config,mcp_bootstrap,tool_router}.py`、`execution_engine/{mcp_manager,mcp_client_manager}.py`、`web_reach/reach.py`、`sandbox/exec_sandbox.py`、`NeurUI/src/`
- 测试基线：Neurova tests/unit 8837 函数 / e2e 0 / performance 0；QwenPaw tests 10672 函数 / e2e+契约齐全
