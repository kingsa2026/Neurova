# 剩余 11 条修复交接文档（2026-10-31）

> 来源：全库体检 55 条（§6-448），已修 44 条，本文覆盖剩余 11 条。
> 修复纪律：`AGENTS.md` 修复教义第 1–7 条 + Qoder 记忆 `project-rulings-*` 的台账/受保护子集/形态集体系。
> 每条含：现状/根因/修法（可直接落代码）/红灯判据/影响面/实施者注意事项。

---

## 1. C1 · TurnRunState 迁移（P1，热路径状态机重构）

### 现状
三个"本轮"语义的状态挂在 per-agent 单例 `OpenAILoop` / `AnthropicLoop` 实例上，
同一 agent 并发两会话交叠时 B 入口清零/污染 A 的状态：

| 挂哪儿 | 什么 | 写点 | 读点 |
|---|---|---|---|
| `openai_loop.py:589` | `self._rounds = _StreamRounds()` | `:734`（每次 predict_step 入口整只替换） | `:613/:617/:645/:653` |
| `base.py:305` | `self._gate_runner = self._buildGateRunner()` | `:482 _ensure_gate_runner` | `base.py:106 evaluateLoopExit` |
| `openai_loop.py:270` | `self.agent._round_usage` | `base.py:660 _accumulateRoundUsage` | `base.py:664 TokenBudgetGate` |

Issue #268 已把 `TurnRunState` 迁到随调用链传递（`base.py:88`），但只迁了
`TurnRunState` 本身，上面三件漏了。

### 根因
`_predict_stream` 是 per-agent 单例上的 async 方法，两会话交叠时共享
`self` 的实例属性。

### 修法
把 `_rounds`、`_gate_runner`、`_round_usage` 全部并入 `TurnRunState`
（`neurova/agent/loops/base.py` 的 `TurnRunState` dataclass）：

```python
# base.py TurnRunState 增加：
@dataclass
class TurnRunState:
    ...
    rounds: Optional[Any] = None       # 替代 loop._rounds
    gateRunner: Optional[Any] = None   # 替代 loop._gate_runner
    roundUsage: Dict[str, Any] = field(default_factory=dict)  # 替代 agent._round_usage
```

然后：
1. `openai_loop.py:589` 删 `self._rounds = _StreamRounds()`，
   在 `_predict_stream` 开头 `state.rounds = _StreamRounds()`；
2. 所有 `self._rounds.xxx` 改 `state.rounds.xxx`；
3. `base.py:106` `gateRunnerForExit()` 改 `state.gateRunner`（兜底保留旧路径）；
4. `base.py:660` `self.agent._round_usage` 改 `state.roundUsage`；
5. `openai_loop.py:270-277` 入口清零改 `state.roundUsage = {}`。

### 判据
- 单测：造两个交叠 `_predict_stream` 调用（asyncio.gather），断言 A 的
  `rounds.lengthEmpty` 不被 B 入口清零；
- 回归：`tests/unit/agent/test_knowledge_retriever_adapter.py` +
  `test_tool_round_budget_single_source.py` 无新增失败。

### 影响面
`openai_loop.py`（~900 行）、`anthropic_loop.py`（~200 行）、`base.py`（~700 行）。
三个文件都在热路径尺寸门禁下（perf_gate），净 LOC 必须 ≤ 0 或用拆分补偿。

### ⚠ 实施者注意
- `openai_loop.py` 有尺寸棘轮（`tests/unit/agent/test_agent_core_size_ratchet.py`），
  新增逻辑不许回填 agent_core.py；
- 改完必须拿 `git diff --numstat` 与改动面对表（形态 410 同族）；
- 热路径循环文件改动后必须跑 `scripts/ci/perf_gate.py`。

---

## 2. R5 · OutboxHandler 四件（P1，分布式投递可靠性）

### 现状（`neurova/collaboration/outbox_handler.py`）

| 症状 | 位置 | 修前行为 |
|---|---|---|
| 失败态不落盘 | `:362-372 mark_failed` 只改内存 | 重启后 retry_count 回 0，毒事件无限重试 |
| 退避时间无人读 | `:369 scheduled_at` 写入后零消费 | 循环不判 `scheduled_at <= now`，退避形同虚设 |
| 死信留原文件 | `:409 _move_to_dead_letter` 只写副本 | 死信进 `dead_letter/` 但 `events/{id}.json` 原样留在 pending |
| 清理只删内存 | `:467 cleanup_old_events` 只删内存 dict | 已"清理"事件重启全量复活重投 |

### 修法
1. **mark_failed 落盘**：方法末尾调 `self._handler._save_event(self)`（或等价）；
2. **循环先判退避**：`process_pending_events` 的 for 循环里在调用 handler 前
   加 `if event.scheduled_at and event.scheduled_at > time.time(): continue`；
3. **死信移除原文件**：`_move_to_dead_letter` 末尾加
   `Path(event._file_path).unlink(missing_ok=True)`（需在 `_save_event` 后调）；
4. **cleanup 同步删文件**：`cleanup_old_events` 里同样 unlink。

### 判据
- 单测：mark_failed × max_retries → 文件从 `events/` 消失、出现在 `dead_letter/`；
- 重启（新建 handler 实例指向同 dir）→ 死信不再重投；
- 正常事件重试 → `scheduled_at` 被设置且循环 skip 未到期的事件。

### 影响面
`neurova/collaboration/outbox_handler.py` 单文件，消费方 `skill_transfers.py`
与 `notifications.py`（经 `reset_skill_transfer_store` / `reset_notification_manager` 间接）。

### ⚠ 实施者注意
- `_save_event` 的写入目标目录在 `__init__` 里由 `events_dir` 参数决定；
- 测试须用 `tmp_path` 做隔离目录（仓内无专门测试文件，需新建）。

---

## 3. 治理端点租户过滤不一致（P2，跨租户越权）

### 现状
`knowledge_sharing.py` 的 list 端点按租户过滤（`:88`），但同一文件的
resolve/restore 路由与 repository 层的三个方法不过滤：

| 方法 | 位置 | 问题 |
|---|---|---|
| `repository.resolve_conflict` | `:2119` | 无 tenant_id 参数 |
| `repository.restore_knowledge` | `:1743` | 无 tenant_id 参数 |
| `repository.pending_submissions` | `:1160` | 无 tenant_id 参数 |
| `knowledge_sharing.py` 路由 | `:143-155` | 调用时也不传租户 |

### 修法
1. `resolve_conflict` / `restore_knowledge` / `pending_submissions` 各加
   `tenant_id: str = "default"` 参数；
2. 方法体内校验 `conflict_id` / `knowledge_id` 对应记录的 `tenant_id` 与
   参数一致，不一致按不存在处理（404）；
3. 端点层从 `current_user.get("tenant_id")` 取值传入。

### 判据
- 单测：租户 A 的管理员调 resolve/restore 传租户 B 的 conflict_id → 404；
- 回归：`tests/unit/knowledge/test_conflict_visibility.py` +
  `test_conflict_source_019b4.py` 无新增失败。

### 影响面
`repository.py`（3 方法签名变更）、`knowledge_sharing.py`（3 路由）、
`test_conflict_*.py`（夹具可能需补 tenant_id）。

### ⚠ 实施者注意
- `resolve_conflict` 内部调 `_syncEntryGovernance()` + `_save()`（批 D1 补的），
  签名变更后确认这两处也走租户路径；
- `_tombstones` dict 的 key 是 knowledge_id，无租户维度——需在 value 里查
  `rec.get("agent_id")` 对应条目的 tenant（或给 tombstone 加 tenant 字段）。

---

## 4. EntryLedger 无 tenantId（P2，治理行恒落 default 租户）

### 现状
`admission.py:67-79` 的 `EntryLedger.AdmissionRequest` 构造不带 `tenantId`，
所有条目治理行恒落 `default` 租户（v20 租户分区对叙述事实名存实亡）。

### 修法
`EntryLedger` 的 `AdmissionRequest(...)` 调用补 `tenantId=item.get("tenant_id") or "default"`，
其中 `item` 是被投影的条目 dict（`create_knowledge` 传入）。

### 判据
- 单测：非 default 租户的条目 create_knowledge → `knowledge_assertions` 表
  该行的 `tenant_id` 不是 'default'。

### 影响面
`admission.py EntryLedger`（1 处构造）+ `repository.py create_knowledge`
（传入条目需带 tenant_id）。

---

## 5. 守卫多主体完整实现（P2，本会话 W2 的改进项）

### 现状
`answer_fact_guard.py:168-190` 已聚合全部命中主体的事实值（批 W2 落地），
但 `contradicted` 的 `subject_key` 归属仍是 `matchedSubjects[0]`——
双主体句中被误判的第二个主体的 key 不准确。

### 修法
在 `contradicted.append` 的时候，遍历 `matchedSubjects` 找到**持有与 claim
冲突数值**的那个主体的 key（即 `_numericFactValues` 含其他数值的主体），
而不是固定取 `[0]`。

### 判据
- 单测：两个主体各有不同的数值事实，答案的数字与主体 B 的值冲突但与
  A 无关 → `contradicted[0]["subject_key"]` 应为 B 的 key。

### 影响面
`answer_fact_guard.py` 单文件；`test_answerFactGuard.py` 补一格。

---

## 6. EventBus `_queue_loop` 在无事件循环场景的行为（P2）

### 现状
`event_bus.py:94` 的 `_queue_loop = loop` 在 `start()` 里登记，
`start()` 本身被 `asyncio.get_event_loop()` 包在 try 里——无事件循环时
`_queue_loop` 为 None，`publish()` 走 `self._async_queue.put_nowait((sub, event))`
（直接投递，可能丢唤醒）。

### 修法
在 `publish()` 的 `else` 分支（无 _queue_loop 时）加 debug 日志：
`logger.debug("EventBus: async subscriber present but no event loop — event dropped")`。
同时检查 `_process_async_queue` 是否有 fallback 消费路径。

### 判据
- 无事件循环时 publish → debug 日志可见（不静默丢）。

---

## 7. HealthCheck interval 仍无周期调度（P2）

### 现状
`health_checker.py:67` 的 `interval` 参数存了但全仓零消费——检查只在
`/health/detailed` 端点被请求时按需跑（无后台周期任务）。

### 修法
在 app lifespan 启动时注册一个 `asyncio.create_task` 周期任务，
按每个 check 的 `interval` 调用 `run_check(name)` 并缓存结果；
`/health/detailed` 读缓存而非现场跑。

### 判据
- interval=5 的 check 在 5s 后缓存有值（不等请求）。

### ⚠ 实施者注意
- 这是行为变更：修前每次请求都现场跑（最新），修后读缓存（可能滞后）。
  需要在 `/health/detailed` 的响应里加 `"cached": true/false` 字段透明化。

---

## 8. 前端主题守卫盲区（P2，CSS 硬编码色值穿透 .vue 文件）

### 现状
`NeurUI/src/styles/__tests__/themes.test.ts:22-26` 只扫
`src/styles/variables.css` 和 `src/styles/global.css` 两个文件，
20+ 个页面组件的 `<style scoped>` 与 JS 内联色全部绕过判据。

### 已知违规实例
- `DashboardPage.vue:237-263`：ECharts 轴/图例文字钉 `#94a3b8`，
  系列色取 cosmic 暗色系——切浅色主题后图表文字对比度不足；
- `ChatPage.vue:3324`：`color:#d2994a`、`:3061` `#fff`。

### 修法
两步：
1. **先修现有违规**：DashboardPage/ChatPage 等把硬编码色改为
   `var(--nr-xxx)` 令牌引用；
2. **再加守卫**：扩展 `themes.test.ts` 或新建测试，
   `glob.sync('src/**/*.vue')` 逐文件读正文，
   `/<style[^>]*>[\s\S]*?(#[0-9a-fA-F]{3,8}\b)/` 检查是否存在
   非白名单色值（白名单 = variables.css 定义的令牌值 + `transparent` +
   `currentColor`）。

### 判据
- 新守卫测试：当前 0 违规（先修完再入库，不许"红着入库"）；
- 变异探针：在任意 `.vue` 的 `<style>` 里加 `color: #123456` → 恰该守卫红。

### ⚠ 实施者注意
- ECharts 的色值在 JS 对象里不走 CSS 变量——需要用
  `getComputedStyle(document.documentElement).getPropertyValue('--nr-xxx')`
  在运行时取值，或维护一份 ECharts 专用主题映射；
- 修改量可能很大（20+ 文件），建议按页面分批。

---

## 9. 结晶器 confirm_pending + _store_candidate 双写已修确认

✅ 已修（`2ab14586`）：
- `_enqueue_candidate` 同 key 去重（合并 sample_count）；
- `_store_candidate` 补 pattern_key 查重（遍历 `engine.iter_nodes()`）。

**残余**：`_store_candidate` 的查重用 `engine.iter_nodes()` 遍历全节点——
语料大时 O(n)。如果后续发现性能问题，改为在 engine 层加
`hasNodeWithContent(key)` 索引查询。暂不阻塞。

---

## 10. C1 附注 · `_round_usage` 的原子性（与 C1 同批修）

`base.py:660-667` 的 `_accumulateRoundUsage` 做读-改-写：
```python
prev = getattr(self.agent, "_round_usage", None) or {}
self.agent._round_usage = { ... }
```
两步之间无锁。C1 把它迁到 `state.roundUsage` 后自然解决（state 是
调用链局部对象，不跨会话共享）——不需要额外加锁。

---

## 11. safe_paths O_NOFOLLOW 已修确认

✅ 已修（`5c61fd41`）：读分支和写分支都有 O_NOFOLLOW。
原报告"只堵了读一半"已过时。

---

## 12. 上传上限已修确认

✅ 已修（`956f2f1a`）：console_files.py:43 + skill_pool_api.py:956
两处均加 100MB 钳制。

---

## 推荐实施顺序

| 序 | 项 | 预估 | 风险 |
|---|---|---|---|
| 1 | R5 outbox | 2h | 低（单文件，无跨文件依赖） |
| 2 | 治理租户过滤 | 2h | 中（签名变更 + tombstone 租户维度） |
| 3 | 守卫多主体完整 | 1h | 低（单文件） |
| 4 | EventBus 无循环 debug 日志 | 15min | 低 |
| 5 | HealthCheck 周期调度 | 2h | 中（行为变更：缓存 vs 现场） |
| 6 | EntryLedger tenantId | 30min | 低 |
| 7 | 前端主题守卫 | 4h+ | 中（修 20+ 文件的硬编码色） |
| 8 | C1 TurnRunState | 4h+ | 高（热路径三文件状态机重构） |

序 8 建议在有完整精力时做（AGENTS.md 修复教义第 3 条：不许"跑不起来就算过"）。
