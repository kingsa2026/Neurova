# 源码审计修复计划（2026-09-10）

- **来源**：`docs/05-reports/源码全面审计_2026-09-10.md`（5 域扫描，约 62 条确认发现）
- **纪律**：全程执行 AGENTS.md 修复教义——根因处修复、禁 consumer-only guard、先红后绿 TDD、live-verify、净 LOC ≤ 0 默认、同一根因全命中点扫荡
- **状态标记**：⬜ 未开始 / 🔄 进行中 / ✅ 完成（含 live-verify）

---

## 批次 P0-A：安全收口（最优先）

**目标**：沙箱从"声明性"变"真实性"；审批链封洞。单人半天~一天。

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| A1 | 填充 `_ENFORCED_SANDBOX_BACKENDS`（用 exec_sandbox._detect_backend 真实探测表），让 enforce 开关真正生效 | `neurova/security/governance.py:29` | 开关=1 时 sandbox_required 工具走真沙箱而非全禁；测试先红后绿 |
| A2 | 删除 docker 假分支：RuntimeManager 无 create_runtime_class → 显式拒绝或警告降级，返回值不再谎报 runtime_type | `neurova/tool_executor.py:3263-3270` | docker 请求不再静默裸跑；错误信息如实 |
| A3 | 治理 fail-open 分级：只读白名单可放行，shell/run_code 类 fail-closed | `neurova/tool_executor.py:1236-1257` | 治理故障时危险工具 DENY；只读工具可用 |
| A4 | 自定义白名单 `re.match` → `re.fullmatch`（或字面命令） | `neurova/security/approval_manager.py:667-669` | `ls && rm -rf /` 不再前缀放行 |
| A5 | 批准重放保留 monotonic_guard 复核，仅豁免触发 ASK 的那条内容项 | `neurova/api/endpoints/governance.py:192` | 篡改 params 后重放被守卫拦截 |
| A6 | ApprovalManager 双实例统一单例；`check_command` 接入 shell 工具分发前置 | `agent_core.py:699`、`tool_executor.py:112-116` | 全库只有一个 ApprovalManager 实例；危险命令走审批 |
| A7 | 删除或鉴权休眠的 `create_approval_api_endpoints` | `approval_manager.py:1043-1118` | 无调用方的危险代码消灭 |
| A8 | /attachment 端点补鉴权（stub 期直接 401/501） | `chat.py:422-423` | 匿名请求 401 |

**净 LOC 预估**：A7/A2 为删除，预计净负。

## 批次 P0-B：并发正确性

**目标**：轮次状态与共享数据结构线程安全。一天。

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| B1 | `_current_user_input/_current_session_id/_current_user_id/_tool_messages_list` 全迁 ContextVar（与 set_request_user_id 同模式） | `agent_core.py:1907-1920,1895-1897`、`chat_pipeline.py:477-489` | 双用户并发同 agent 冒烟测试身份/工具消息不串 |
| B2 | `_recall_loop_guard` 按 session_id 分桶（ContextVar 或 dict[session_id]） | `tool_executor.py:2097-2105` | 并发会话 guard 不互相覆盖 |
| B3 | provider 读路径加锁返回快照副本 | `provider_manager.py:673-743` | 并发 add/remove + list 不再 RuntimeError |
| B4 | EnhancedContextBuilder 加 RLock；build_context 内置惰性维护调用；缓存键改 hash(query) | `enhanced_context_builder.py` | 缓存有界；并发 append 不丢消息 |
| B5 | rebuild_loop 原子换引用：请求侧一次性读局部变量，热切换 per-agent asyncio.Lock | `agent_core.py:1050-1062` | 切换期间并发请求用同一代际的 loop |
| B6 | tool_engine 惰性创建加锁 | `tool_executor.py:220-244` | 并发首调单实例 |

## 批次 P0-C：真流式接线（体感收益最大）

**目标**：首 token 延迟从"全响应时长"降到真实首包。一天~一天半。

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| C1 | `chat_stream` 改真流式：传 stream=True 走 `_call_loop_stream` 增量 yield，post-chat 后置到 done 事件前 | `agent_core.py:1720-1725`、`chat_pipeline.py:1729` | /chat/stream 首字节 < 2s（长回复场景） |
| C2 | chat_stream 补限流 acquire/release + 熔断检查 + 流内 429 report_429 | `multi_model_client.py:744-878` | 流式与 chat() 同限流语义；测试覆盖 |
| C3 | 重试单层化：SDK max_retries 置 0，重试语义收敛外层 RetryConfig | `llm_client.py:105,229,237` | 429 场景最多 3 次真实请求（非 9） |
| C4 | SSE 端点补 15s ping 心跳（对齐 console） | `chat.py:244-264` | 长回复期间网关不掐断 |
| C5 | 流式全量缓冲改条件累积（仅上游声明不回传 usage 时） | `multi_model_client.py:807-808` | 长响应内存不再翻倍 |

## 批次 P1-D：记忆层写路径与检索（性能收益最大）

**目标**：写放大数量级下降；检索去 O(N)。两天。

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| D1 | persist.db 常驻连接（check_same_thread=False+锁）+ WAL + synchronous=NORMAL | `manager.py:282-495`、`mem_core.py:86` | journal_mode=modes 实测 WAL；写吞吐基准提升 |
| D2 | recall touch 批量化：top-N 温度更新单事务 | `manager.py:883-887` | 每轮 recall 事务数 10→1 |
| D3 | 依赖图写入合批（executemany） | `dependency_graph.py:188-234` | 每轮依赖提取事务数骤降 |
| D4 | MemoryWriteQueue flush 改单事务 executemany | `conversation_buffer.py:319-349` | 批量语义落到存储层 |
| D5 | 全表驻留改分区缓存/SQL 分页查询（先做分区：三级隔离各一 dict，后续按温度淘汰） | `manager.py:342-346,561-569` | 启动不再全表扫描；232 万行库可承载 |
| D6 | 关键词索引改事件驱动增量维护（订阅 MEMORY_CREATED/DELETED），消除"每查询重建 vs 永不更新"踩踏 | `manager.py:973`、`neurova_recall.py:986`、`semantic_search.py` | 新记忆即时可召回；recall 不再 O(N) 重建 |
| D7 | 温度通道改 SQL `ORDER BY temperature DESC LIMIT n`（索引已建） | `neurova_recall.py:947-988` | 温度通道去全量排序 |
| D8 | `_PersistDbStore` 参数化查询 + 常驻只读连接 | `mem_core.py:86-110` | 去 regex 注入隔离条件 |
| D9 | refresh_moe_index 走增量；超限记忆按温度滚动淘汰而非静默截断 | `mem_core.py:905-921,736-738` | 超上限记忆可被淘汰换入 |

## 批次 P1-E：事件循环同步 I/O 扫荡（机械性，收益面最广）

**目标**：统一 `asyncio.to_thread` 化。半天~一天，逐处可独立合入。

| # | 任务 | 关键文件 |
|---|------|----------|
| E1 | memory_search / file_read/write/delete/edit 工具 | `tool_executor.py:2150-2261` |
| E2 | session get_session/add_message 调用点 | `chat_pipeline.py:566`、`post_chat_pipeline.py:521-528` |
| E3 | neurflow async 端点包 to_thread；fire-and-forget 任务持引用+try/finally 落终态 | `neurflow_api.py:396,703`、`storage.py` |
| E4 | 渠道适配器共享连接池 + 发送路径 to_thread（基类注入，一次改 14 个适配器） | `channels/qqbot.py:198` 等 |
| E5 | usage 记账常驻连接 + to_thread 写入 | `core/usage_history.py:64-143` |
| E6 | 肌肉记忆 _save_all 落盘 to_thread + 提供 reset_streak 公有 API 替代私有字段穿透 | `agent_core.py:1766-1775` |
| E7 | auto_context_updater 触发去重（执行锁/任务队列），删死方法 _update_loop | `auto_context_updater.py:94,214` |

## 批次 P1-F：假接线收尾（"声明了但没接线"清单）

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| F1 | provider 健康链接线：_chat_single_attempt 成败分支回调 mark_provider_success/failure；删除或接线 auto_failover | `provider_manager.py:756-784` | 负载均衡数据真实更新 |
| F2 | LLMRouter 改 TTL 增量刷新，健康/延迟字段接 ModelClient 真实计数 | `llm_router.py:333-344` | 新增/下线 provider 进路由 |
| F3 | 删除第一版 `_resolve_available_fallback`，确认第二版语义并补注释 | `multi_model_client.py:880-965` | 单一定义；failover 语义明确 |
| F4 | 会话归属校验建索引式定位（id→agent/user 映射），废全库 glob | `session_manager.py:766-800`、`console.py:716` | delete/rename 单文件读取 |
| F5 | PostChatPipeline 分流：回复必需（save_session/save_memory/TTS）留内联，其余 create_task 后台化+去重节流 | `post_chat_pipeline.py:345-413` | 响应延迟不再线性叠加 15 步 |
| F6 | 会话历史恢复截断到最近 N 条；pool 视图加消息数/token 双预算 | `chat_pipeline.py:570-574`、`context/orchestrator.py:425-504` | 长会话 prompt 不再全量重放 |
| F7 | RSI apply_optimization 加 min/max 夹紧 + 审计日志；迭代移后台任务队列（closed_loop 只投递信号） | `rsi/orchestrator.py:184`、`closed_loop.py:528` | 参数漂移有界；请求路径无 RSI 毛刺 |

## 批次 P1-G：前端性能

| # | 任务 | 关键文件 | 验收 |
|---|------|----------|------|
| G1 | 流式渲染：chunk 进非响应式缓冲 + rAF 节流刷入；非流式消息按内容 hash 缓存渲染 | `ChatPage.vue:1463,210`、`utils/markdown.ts` | 长回复流式不再每 token 全文重解析 |
| G2 | i18n 改动态 import（仅 zh-CN 静态 fallback） | `i18n/index.ts:2-32` | 主 chunk 缩减 ~3 万行 |
| G3 | Canvas 轮询加 disposed 守卫 | `CanvasDesignerPage.vue:2107-2129` | 卸载后停止轮询 |
| G4 | computed 内写 ref 收敛到 watch；watch 尾消息长度替代全量 reduce | `ChatPage.vue:696,2173` | 流式期间 diff 面缩小 |
| G5 | store 层加 TTL 缓存 + in-flight Promise 复用 | `useChatModels.ts:93`、`stores/agents.ts:144` | 页面切换零重复请求 |
| G6 | SSE 401/403 走统一分支（清 token+跳登录），不再塞消息正文 | `ChatPage.vue:1237-1313` | 会话过期行为与 axios 层一致 |
| G7 | 模型/Agent 列表无缓存去重 | `useChatModels.ts:93`、`stores/agents.ts:144` | 页面切换零重复请求 |
| G8 | antd 按需引入（unplugin-vue-components） | `main.ts` | vendor-ant chunk 显著缩减 |
| G9 | scrollToBottom 改 stick-to-bottom 判定 + rAF 合并 | `ChatPage.vue:1280,1949` | 去强制同步布局 |

## 批次 P2-H：结构性（低优先，可分多轮）

| # | 任务 | 说明 |
|---|------|------|
| H1 | memory_layer 拆分（120 文件/43733 行）：按检索/存储/分类/召回子域拆包 | 大工程，先出拆分设计稿 |
| H2 | 情感 8 份重复收敛 EmotionHubEngine 单一入口 | 删 7 份副本 |
| H3 | e2e 补齐：治理-审批-重放、RSI 闭环、沙箱、工具循环四条链；performance 换真实负载基准 | e2e:unit 当前 1:500 |
| H4 | 删 exec_sandbox.py:183 AppContainerSandbox 死 stub；manager.py:2298 STUB 段处理 | 死代码清理 |
| H5 | 裸 `except Exception: pass` 统一改 `logger.debug(..., exc_info=True)`；set_request_user_id 失败至少 warning | `chat_pipeline.py:1660,369,2115` |
| H6 | /test 诊断端点 debug 门控；app 单例锁外读收口 | `app.py:1018-1066` |
| H7 | AGENTS.md 勘误：evolution/ "partially skeletal" 口径更新为"已全真实现" | 文档 |

---

## 执行顺序与依赖

```
P0-A 安全 → P0-B 并发 → P0-C 流式 → P1-D 记忆 → P1-E 扫荡 → P1-F 假接线 → P1-G 前端 → P2-H 结构
```

- A 与 B 无依赖可并行；C 依赖 B5（热切换锁）完成
- E 逐处独立可穿插；F4/F5/F6 依赖 E2 落地
- G 独立于后端，可并行推进
- 每批次完成标准：先红后绿用例 + 受影响套件回归零新增 + live-verify + 提交说明列净 LOC 去向

## 预估总盘

| 批次 | 规模 | 风险 |
|------|------|------|
| P0-A | ~1 天 | 中（沙箱后端探测跨平台） |
| P0-B | ~1 天 | 中（ContextVar 迁移触及管道多处） |
| P0-C | ~1.5 天 | 中高（流式重构牵动前端消费） |
| P1-D | ~2 天 | 中（记忆行为等价性须基准守护） |
| P1-E | ~1 天 | 低（机械改造） |
| P1-F | ~1.5 天 | 中 |
| P1-G | ~1.5 天 | 中（G1 流式缓冲牵动渲染层） |
| P2-H | 多轮 | 低（均为独立清理） |
