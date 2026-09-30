# G4 修正方案 —— 工具取消、超时处置与进程生命周期

> ## ⚠️ 状态更新（2026-09-30 补入仓库 · 状态逐条核实至 `008a3e2a`）
>
> **本文是 G4 的立项与判据来源，并非现状描述。** 此前只以 Issue #288 附件形态存在；
> 本次补入仓库，闭合「对标文档 §5 G4 行 → 本文」的引用（补入前该引用悬空，
> 由 `tests/unit/test_active_layer_refs_guard.py` 拦下；生产代码里早已出现
> `G4-RC6` 这样的引用——文档不入库该引用即悬空）。
>
> 正文保留立项原文，六个根因的落地状态如下（逐条核实到求值点与默认装配点，非读提交标题）：
>
> | 缺口 | 现状 |
> |---|---|
> | RC-1 超时一刀切 | 已闭合：`TimeoutDisposition` 三态（`core/tool_capability.py:79`），分派在 `resolveTimeoutDisposition:154`（未声明一律 `BACKGROUND` ⇒ 不声明即与改前逐字节同行为），`KILL` 分支 `:243`；四类进程型工具声明 `KILL`（`builtin_tools.py:360` `computer_shell`、`:905` `git`、`:950` `run_code`、`:974` `exec_command`，**恰为本文 D-3 点名的四类**，每处注释都写了"为何放弃即须终止"） |
> | RC-2 `to_thread` 外部不可取消 | 已闭合：协作令牌 `core/cancel_token.py`。**本文的核心判断成立且被原样写进代码**——`tool_coordinator.py:225-230` 注释："外层取消对已进 `to_thread` 的调用无效…只有置位令牌才能让 worker 注册的进程杀灭回调真正发出…本层不吞取消"。杀灭回调生产注册三处（`shell_sessions.py:117`、`execution_layers/__init__.py:250`、`tool_executor.py:3864`） |
> | RC-3 进程树杀灭原语 | 已闭合：收口为模块级单源 `killProcessTree` / `spawnKwargsForKill`（`sandbox/exec_sandbox.py`），主工具路复用 |
> | RC-4 `kill_all` 零调用方 | 已闭合：接进 `api/app.py:1161`（`asyncio.wait_for(..., AGENT_SHUTDOWN_TIMEOUT)`），`:1152` 注释直引"实现完整、生产侧**零调用方**"；台账判据类由机器算为 `consumed` |
> | RC-5 取消计为工具失败 | 已闭合：单源判定 `is_policy_denial` 认 `cancelled`（`security/governance.py:64-76`），注明"与上述六键完全同构的**决策**" |
> | RC-6 取消终态不回反馈环 | 已闭合：`_observe_background` 取消分支补投 `_pending_hints`（`tool_coordinator.py:341` 起），注释标 **"断链修复（G4-RC6）"** |
>
> 落地提交 `e1959626`（Issue #288 / MR #291），另含两处本文未提的同类根修
> （N-1 `LocalExecutor.exec` 阻塞事件循环；N-2 进程未自成团时按组杀灭会命中宿主）。
>
> **决策点裁决**：D-1 引入令牌 ✅；D-2 默认保守 ✅；D-3 恰好四类 ✅；**D-4 用户停止也杀进程 ✅**；D-6 hint ✅。
>
> **三处实现优于本文，后来者勿照本文落点施工**：
>
> 1. **D-5 令牌载体**：本文说"进 `TurnRunState`"，实际走 `ContextVar`——与 G2 的目标写入同因：
>    取消要跨 `chat()` / 线程池边界，`TurnRunState` 传不过去。
>    **⇒ 两案在这条上犯的是同一个错：把"轮级生命周期"等同于"必须显式传参"。**
> 2. **`WriteScope` 缺省比本文更保守**：本文默认 `{SESSION}`，实现取 `{SHARED}`
>    （`tool_capability.py:76`，"状态不明即按会互相干扰处理"）⇒ 未声明工具默认既不可并行、
>    也不被误判为无作用域。
> 3. **收尸宽限期有单源**：本文只写"沿用同一数值来源"，实现落成 `exec_sandbox.KILL_GRACE_S`
>    为单源 + `KILL_GRACE_FALLBACK_S = 5.0` 仅作导入失败镜像（`tool_coordinator.py:25-27`），
>    并注释点明"数值单源在 `exec_sandbox`"。
>
> **口径更正**：G2 方案顶部状态表把本文这条记作"已闭合：`TimeoutDisposition.ABORT` 返回
> cancelled 形态"。这只说了一半——`ABORT` 不碰进程，**真正止住"子进程继续跑"的是 `KILL`
> 分支 + 进程树杀灭**（RC-3）。按那条口径去理解会以为进程问题已解决。
>
> **遗留未验项**：验收线 §8 第 1/2 条的活体证明（真起 `sleep 120` 后证进程树消失、用户停止同证）
> 未观测到证据。单测覆盖已有（`tests/unit/tools/test_tool_cancellation.py` 447 行），
> **但教义第 4 条不接受"单测全绿"替代活体**。
>
> 正文行号对准 `c55e1f37`，引用前请对准当前 `HEAD` 复核。

> 立项时间：2026-09-26 · 取证基线：`c55e1f37` · 关联缺口：对标文档 §5 G4
> 关联方案：G1 [`2026-09-26-tool-loop-iteration-repair-plan.md`](2026-09-26-tool-loop-iteration-repair-plan.md)、
> G3 [`2026-09-26-tool-batch-parallelism-repair-plan.md`](2026-09-26-tool-batch-parallelism-repair-plan.md)
> 关联台账：`scripts/ci/toolLoopDeadlines.txt`

---

## 0. 结论先行：这条被我判错了，方向是"低估了本仓已有的东西"

对标文档 §8 原话是 G4 "**唯一我确认必须新造底层能力的一条——不是接线问题**"。
**这句是错的。** 逐行核完后的实情：

| 我以为 | 实测 |
|--------|------|
| 没有取消通路 | **有，而且比参照侧多一层持久化**：`task_tracker.request_session_stop()` 取消 asyncio task（`console.py:1131`），`agent_run_store.request_cancel()` 把取消意图**落库** `cancel_requested` 列供执行侧/审计/重启对账（`agent_run_store.py:12,187,203`）。参照侧只有一只内存 `AbortSignal`。 |
| 没有进程树杀灭 | **有，而且是单源跨平台原语**：`exec_sandbox.ProcessSandbox._kill_process_tree:157`——POSIX 经 `start_new_session` 建组后进程组 SIGKILL（`:151-155`），Windows 走 `taskkill /T /F`，进程已退时退回直接 kill。`code_sandbox.py:375-377` 注释明写"与 exec_sandbox 同一姿态，**不另造一套**"。 |
| 没有会话终止 | **有**：`shell_sessions.ShellSession.terminate():142` 与 `kill_all():300`。 |

**所以 G4 不是"造能力"，是"三个已有原语没接到主工具路的超时/取消语义上"，外加两处语义漏判。**
成本量级从"新建底层"降到"接线 + 一处协作式协议"。这同时意味着本方案的**净新增 LOC 应显著低于直觉**。

---

## 1. 六个真实根因（逐条核实）

### RC-1 · "超时 → 转后台"是一刀切，且其成立理由只覆盖一半场景

`tool_coordinator.py:131-150`：

```python
"""带超时执行；超时不取消——同一任务继续在后台跑完，返回 background 信封。

语义：转后台的必须是**同一个**任务——工厂重建会让副作用工具双执行。
"""
task = asyncio.ensure_future(aw)
done, pending = await asyncio.wait({task}, timeout=effective)
if not pending:
    return task.result()
# 超时 → 转后台：同一任务继续（持有引用防 GC 静默吞掉）
```

**"不重新执行工厂"这个理由是成立的**——重建确实会让写类工具双跑副作用，
而且 `:186-204` 还专门挂强引用防事件循环弱引用 GC 静默吞掉观察者（A-20）。这段代码是想清楚了的。

问题在于它把**同一个策略无差别施加于两类完全不同的工具**：

| 工具类 | "转后台"的实际含义 | 是否正确 |
|--------|------------------|---------|
| 纯 async/IO 型（检索、抓取、搜索） | 结果稍后回来，投 hint | ✅ 正确，且优于报错 |
| **进程型**（`run_code` / `git` / `exec_command` / `computer_shell`） | **子进程继续跑**，占 CPU、持文件锁与句柄、可能持续写盘；而界面已认为中止 | ❌ 错误 |

⇒ 缺的不是"要不要取消"的答案，而是**"这个工具被放弃时意味着什么"这一声明维度**——
与 G3 的一刀切并行是**同一个病形**（保守默认 + 缺声明轴）。

### RC-2 · `to_thread` 从外部**不可取消**（Python 结构约束，决定设计形态）

工具链大量把阻塞操作下沉线程池（实测 8+ 处）：`tool_executor.py:2656`（searxng）、
`:2667/:2777/:2830/:2921`（web fetch/search）、`:3368`（记忆检索）、`:3419`（file_read）、
`:3483/:3527`（parse）。`:2604` 注释立了规矩："阻塞式 HTTP 抓取 — **只允许**经 `asyncio.to_thread` 在线程池中调用"。

这条规矩是对的，但它带来一个后果：**`task.cancel()` 对已进入 `to_thread` 的调用无效**——
取消只会丢掉结果，线程照跑到自然结束。

⇒ **`console.py:1117` 那句"取消沿 await 点传播中断 LLM/工具执行"只在到达线程池边界之前成立。**
这是本方案最重要的一条认知：**取消必须协作式地下沉进 worker 内部**（worker 自查令牌、
或持有进程句柄可被外部杀），从外面套 `CancelledError` 是无效的。
任何"加个 try/except CancelledError 就算支持取消"的实现都是在制造假承诺。

### RC-3 · 进程树杀灭原语存在，但主路不吃它

`_kill_process_tree` 的全部调用方：

```
exec_sandbox.py:129  （超时分支）
exec_sandbox.py:142  （异常分支）
code_sandbox.py:377  （_killTree 转发）
```

**主工具路在不经沙箱时不经过它。** 即：`_execute_exec_command`（`tool_executor.py:4300`，
`exec_command` 常驻进程）、`_execute_git`、`run_code` 的平台直跑分支，
超时后没有任何一方去杀进程树。原语就位，接线缺失。

### RC-4 · 会话型工具的进程无人回收（`kill_all` 生产零调用方）

```
ShellSessionManager.kill_all()   shell_sessions.py:300  ← 实现完整
调用方：tests/unit/tools/test_shell_sessions.py:85,101   ← 只有测试
```

既没有应用关停钩子调它，也没有超时路径调它。⇒ `exec_command` 起的常驻 shell 进程
**随应用退出而泄漏**，且被超时的会话进程也永不被终止。
这正是 `AGENTS.md` 协作红线点名的"写了却无人读"断点形态——按教义第 5 条，
它应当作为一条**台账登记项**存在，而不是靠这次发现。

### RC-5 · 用户取消被计为"工具失败"（粘性污染）

`security/governance.py:48-66` 的 `is_policy_denial` 是单源判定，注释列明它存在的目的
就是"避免策略事件被误记为工具失败"，并已收编六种裁决形态：
`governance` / `pending_approval` / `param_guard` / `swarm_rejection` / `hook_blocked` / `metacog_advisory`。

**但 `cancelled` 不在其中。** 后果与它注释里提到的 `hook_blocked` 病症同型：
取消会以失败身份进入 `on_tool_executed` 的三处统计与熔断观察者，
并经 `creation_governance.py` 的 `MIN(success)` **把该工具的结构身份永久判失败**。
用户按几次停止，就能把一个好工具在治理面上钉死。

### RC-6 · 后台任务被取消时，事实进了台账、没进反馈环

`tool_coordinator.py:236-238`：

```python
except asyncio.CancelledError:
    entry["success"] = False
    entry["error"] = "cancelled"
```

对比成功分支（`:230` append hint）与 `except Exception` 分支（`:243-248` append hint + warn），
**取消分支既不投 `_pending_hints` 也不记日志**；`finally`（`:249-256`）只把 entry 移入
`_completed` 留存。于是：`get_background_status(task_id)` 查得到"cancelled"，
但下一轮 LLM 与用户**永远收不到这条终态**——一个已经转后台的工具被取消后凭空消失。

这是"写入 → 读取 → 反馈 → 再写入"四环里**第三环断裂**，按红线属必修项。

---

## 2. 本仓已有的优势面（勿在改造中丢掉）

| 优势 | 位置 | 参照侧有无 |
|------|------|-----------|
| **取消意图持久化**（`cancel_requested` 列，供重启对账与审计） | `agent_run_store.py:12,50,187,238` | **无**（只有内存 AbortSignal，进程重启即失忆） |
| 取消端点已补鉴权与会话归属校验 | `console.py:1120-1128`（审计 P0-3 修正） | — |
| "新会话首轮未落盘时不得打断停止按钮"的边界处理 | `console.py:1122-1127` | — |
| 跨平台进程树杀灭单源原语 | `exec_sandbox.py:151-162` | 有（POSIX PGID + Windows taskkill），但**无持久化取消** |
| 后台任务强引用防 GC 静默吞 | `tool_coordinator.py:186-204`（A-20） | — |

⇒ 结论：**取消的"意图层"本仓比参照侧完整，缺的是"执行层"的兑现。**
本方案不许在改造中绕过 `agent_run_store` 另起一套取消状态——那是教义第 6 条的当场违约。

---

## 3. 目标态

| 环节 | 现状 | 目标 |
|------|------|------|
| 取消传播 | 到 asyncio 边界即止 | **下沉进 worker**：协作令牌 + 可注册杀灭回调 |
| 超时处置 | 一律转后台 | 按工具声明分派：`kill` / `abort` / `background`（默认仍 `background`） |
| 进程树 | 仅沙箱路杀灭 | 主路 `run_code`/`git`/`exec_command`/`computer_shell` 复用**同一原语** |
| 会话生命周期 | `kill_all` 无人调 | 接进应用关停 + 接进超时 |
| 取消的统计身份 | 计为工具失败 | `is_policy_denial` 认 `cancelled` 为裁决 |
| 取消的反馈 | 静默消失 | 投 hint（或显式终态事件），LLM 与用户都看得见 |

---

## 4. 设计

### 4.1 协作式取消令牌（RC-2 的唯一解）

```python
# neurova/core/cancel_token.py（新，约 60 行）
class CancelToken:
    """轮级取消令牌。沿 await 点传播之外，给线程池 worker 一条自查通路。

    存在理由：asyncio 取消对已进入 to_thread 的调用无效（只丢结果不中止执行），
    而本仓阻塞操作按规矩一律下沉线程池（tool_executor.py:2604）。
    """
    def cancelled(self) -> bool: ...            # worker 轮询点
    def raiseIfCancelled(self) -> None: ...     # 长循环分片处
    def onCancel(self, action: Callable[[], None]) -> None:
        """注册杀灭回调（如 ProcessSandbox()._kill_process_tree）。
        置位时同步执行——回调是**唯一**被允许打断线程池里那次调用的手段。"""
```

**装配点**：令牌由轮创建者持有（与 G1 `TurnRunState` 同一生命周期，
**不得挂 loop 实例**——那会重演 G1 缺陷 A 的跨会话污染），
在咽喉 `_execute_single_tool_inner` 取出并传给执行体。

**取消源唯一**：`task_tracker.request_session_stop()` 置位令牌，
`agent_run_store.request_cancel()` 继续落库。**不新增第二个取消入口。**

### 4.2 超时处置声明（RC-1，复用 G3 的声明模块）

```python
class TimeoutDisposition(str, Enum):
    BACKGROUND = "background"   # 现状默认：同一任务转后台
    ABORT      = "abort"        # 可打断的 async 工具：取消任务
    KILL       = "kill"         # 进程型：置令牌→触发杀灭回调→等收尸→报超时

# ToolCapability（G3 §6.1）新增一个 facet：
timeoutDisposition: TimeoutDisposition = TimeoutDisposition.BACKGROUND
```

三态默认 `BACKGROUND` ⇒ **不声明即与今日逐字节同行为**，改造可零风险铺。

调度侧改造（`run_with_timeout`）：

```python
if not pending:
    return task.result()
if disposition is TimeoutDisposition.KILL:
    token.cancel()                       # 触发注册的 _kill_process_tree
    await asyncio.wait({task}, timeout=KILL_GRACE_S)   # 收尸窗口，有界
    return {"status": "cancelled", "cancelled": True, "tool_name": ..., "reason": "timeout"}
if disposition is TimeoutDisposition.ABORT:
    task.cancel(); ... 同上返回 cancelled 形态
# BACKGROUND：走现有转后台 + 观察者（原逻辑一行不改，含 A-20 强引用）
```

> **`KILL_GRACE_S` 必须存在且有界**：`_kill_process_tree` 之后需要一个收尸窗口，
> 否则僵尸进程未回收。`exec_sandbox.py:131` 现用 `communicate(timeout=5)` 就是这个姿势，
> 沿用同一数值来源，不新造第二个宽限期常量。

### 4.3 返回形态统一为 `cancelled`（RC-5/RC-6 同时修）

新增一个顶层键 `cancelled: True`，并**扩展单源判定而非另立判定**：

```python
# governance.py is_policy_denial —— 在既有六键枚举里追加
or result.get("cancelled")
```

理由与它注释里 `hook_blocked` / `swarm_rejection` 完全同构：**取消是裁决，不是后端故障**。
不加这一键，用户按停止按钮就能经 `creation_governance.py` 的 `MIN(success)` 把工具永久钉死。

### 4.4 会话进程生命周期（RC-3/RC-4）

1. `exec_command` 起进程时，把 `session.terminate`（或更好的 `_kill_process_tree`）
   **注册为令牌的 `onCancel` 回调**——原语已在，只是此前没人把句柄交出去。
2. `kill_all()` 接进应用关停（`api/app.py` 的 lifespan，与既有资源回收同批），
   消除"实现完整、生产零调用"的断点。
3. 该登记项进 `toolLoopDeadlines.txt`：判据类应为 `consumed`（接完即转），
   台账与实测不符即红。

### 4.5 取消的可见性（RC-6）

`_observe_background` 的 `except asyncio.CancelledError` 分支补投 hint：

```python
except asyncio.CancelledError:
    entry["success"] = False
    entry["error"] = "cancelled"
    self._pending_hints.append({"task_id": task_id, "tool_name": tool_name,
                                "cancelled": True})   # 断链修复：终态必须回到反馈环
    logger.info("后台工具 %s (%s) 已取消", tool_name, task_id)
```

---

## 5. 决策点

| # | 决策 | 我的推荐 | 代价 |
|---|------|---------|------|
| **D-1** | 是否引入 `CancelToken`（协作协议） | **引入** | 约 60 LOC + 所有长跑 worker 需加自查点；**不做则 RC-2 无解**，取消承诺仍是假的 |
| **D-2** | 默认处置取 `BACKGROUND`（保守）还是 `KILL`（激进） | **BACKGROUND** | 保守=行为零变更、可灰度；激进=立刻止住进程泄漏，但会改变现有工具超时语义，风险面大 |
| **D-3** | 哪些工具先声明 `KILL` | **仅四类进程型**：`run_code` / `git` / `exec_command` / `computer_shell` | 每条声明必须附"为何可安全杀"的依据行；`orchestrate_tools`/`spawn_subagent` 暂不动（内层自有生命周期） |
| **D-4** | 用户主动停止是否也杀进程 | **是**（同一令牌路径） | 用户点"停止"后进程仍在跑，是 RC-1 同一病灶；但需在提示文案上区分"超时取消"与"用户取消" |
| **D-5** | 令牌放哪 | **进 G1 的 `TurnRunState`**，不进 loop 实例 | 依赖 G1-A 先行；否则重演跨会话污染 |
| **D-6** | 是否给 LLM 一条"工具已被取消"的显式提示语 | **给**，走 §4.5 hint | 不给则模型对着缺失结果继续编（与 G5 病症同源） |

> D-2/D-5 我取保守，但 **D-1 不能省**——它是这条缺口真正的技术难点，
> 绕开它做出来的"取消"只在没进线程池的工具上生效，属于半接路径（比不接更糟，因为它会让人以为已接）。

---

## 6. 红→绿测试（`tests/unit/tools/`、`tests/unit/agent/`，全部 `test_` 前缀）

转绿前不得进 `scripts/ci/protected_tests.txt`。

### 6.1 现状钉桩（证明故障真实）

| 用例 | 断言 |
|------|------|
| `test_toThreadWorkSurvivesTaskCancellation` | **本方案最重要的一条**：`to_thread` 内的可观测标记（如写入共享对象的计数）在 `task.cancel()` 后**仍在增长**——直接证明"从外面取消无效"，为 D-1 立据 |
| `testTimedOutProcessKeepsRunning` | 起一个 `sleep` 长进程的工具超时后，进程句柄仍存活（钉 RC-1/RC-3） |
| `testKillAllHasNoProductionCaller` | 静态：`kill_all` 在 `neurova/` 内 0 调用（钉 RC-4；§4.4 接完后本用例**改判为 ≥1 并反转注释**） |
| `testCancelledBackgroundToolEmitsNoHint` | 取消后台任务 ⇒ `_pending_hints` 无该条（钉 RC-6） |
| `testCancellationCountsAsToolFailure` | `is_policy_denial({"cancelled": True, ...})` 现为 `False`（钉 RC-5） |

### 6.2 目标行为

| 用例 | 断言 |
|------|------|
| `testCancelTokenTriggersRegisteredKillAction` | 置位令牌 ⇒ 注册的杀灭回调被调用（用真实 Popen 起 `sleep`，断言进程真的没了） |
| `testKillDispositionReapsWithinGrace` | `KILL` 分支在 `KILL_GRACE_S` 内返回 `cancelled` 形态，不留僵尸（`waitpid`/返回码可读） |
| `testProcessToolsDeclaredKill` | `run_code`/`git`/`exec_command`/`computer_shell` 四项声明为 `KILL`，且逐项带依据 |
| `testUndeclaredToolStillGoesBackground` | **等价性守卫**：未声明工具的超时行为与改前逐字节一致（RC-1 的保守默认不许漂移） |
| `testCancelledIsPolicyDenial` | `is_policy_denial` 认 `cancelled` ⇒ 不计入工具故障、不粘进 `MIN(success)` |
| `testCancelledHintReachesFeedbackLoop` | 取消的后台工具在下一轮被 `pop_pending_hints()` 取到 |
| `testKillProcessTreeNotReimplemented` | 静态：全仓 `taskkill` / `start_new_session` 字样仍只在 `exec_sandbox.py`——**防止第二条杀灭路诞生**（教义第 6 条自证） |
| `testCancelTokenLivesWithTurnState` | 令牌不挂 loop/agent 实例属性（与 G1 §8.1 同族守卫） |

**禁止写法**：不得用 `MagicMock` 充当 `Popen` 来证明"进程被杀"——必须真起进程真断言存活，
否则测的是调用次数而不是取消效果。

---

## 7. 规模

| 切片 | 新增 | 删除 | 净 |
|------|------|------|-----|
| `CancelToken` | 60 | — | +60 |
| `TimeoutDisposition` + `run_with_timeout` 三分派 | 45 | — | +45 |
| 四类进程工具接 `onCancel` | 50 | −10（各自的散落脚本超时） | +40 |
| `kill_all` 接 lifespan | 8 | — | +8 |
| `is_policy_denial` 追加键 + hint 补投 | 12 | — | +12 |
| worker 自查点（`raiseIfCancelled`） | 20 | — | +20 |
| 合计 | | | **约 +185** |
| 测试另计 | ~350 | | 不计入门禁 |

**主动没做**：不新写进程杀灭逻辑（复用原语，省 ≈−70）、不新增第二个取消端点、
不把令牌挂 loop 实例（避免又造一处 G1 缺陷 A 同型污染）。

**运行成本增量：0 次 LLM 调用。**

---

## 8. 验收线

1. **活体（教义第 4 条）**：`exec_command` 跑 `sleep 120`，把该工具超时降到 5s 并声明 `KILL`；
   触发超时后用系统工具（Windows `tasklist` / POSIX `ps -o pid,pgid`）证明**进程树已消失**，
   而非"结果回来了但进程还在"。命令与输出原文进提交说明。
2. **用户停止路径同证**：D-4 落地后，前端点停止 ⇒ 同一证法。
3. **等价性**：未声明工具集合在改前/改后跑同一组超时用例，行为逐条一致（`testUndeclaredToolStillGoesBackground` 的活体版）。
4. **反馈闭环**：取消一个后台工具，下一轮 LLM 上下文里能观测到该终态（对应 RC-6）。
5. **统计身份**：连续取消同一工具 3 次后，`creation_governance` 侧该工具粘性**未被判失败**（对应 RC-5）。
6. **台账**：`kill_all` 由 `no_consumer` 转 `consumed`（机器算，非人改）；
   `KILL_GRACE_S`/超时相关阈值入册，阈值可达性机器算为 `single_source`。

---

## 9. 风险与回退

| 风险 | 处置 |
|------|------|
| 杀进程树误伤共享宿主（桌面 guest、浏览器） | D-3 只放四类工具；`SHARED_DEVICE` 类工具在 G3 里已被判为不可并行，本方案同样**不给 `KILL`**，改由 supervisor 自身管生命周期（`camofox_supervisor` 已有 `_taskkill_all:448`） |
| 收尸窗口内进程未退 ⇒ 返回时仍持锁 | `KILL_GRACE_S` 有界 + 超时后如实标注"已发杀灭，未确认退出"，**不谎报已终止**（教义第 2 条诚实形态） |
| worker 自查点漏加 ⇒ 该工具上取消仍无效 | §6.2 `testCancelTokenTriggersRegisteredKillAction` 对每个声明 `KILL` 的工具逐一参数化跑，漏一个红一个 |
| 与 G1/G3 冲突（都改 `base.py`/咽喉/声明模块） | 顺序：G1-A → G3-M1 → **G4**。令牌进 `TurnRunState`（D-5），处置 facet 进 G3 的 `ToolCapability`（§4.2）——**不另开声明文件** |
| 长期留存 `BACKGROUND`/`KILL` 双策略造成认知负担 | 三态是**必要区分**（放弃语义真的不同），非兼容垫片；D-2 的保守默认会在 M 期内被逐步声明取代 |

---

*本文所有行号对准 `c55e1f37`，复验命令：*
*`sed -n '131,204p' neurova/agent/tool_coordinator.py`、*
*`grep -n "_kill_process_tree" -A 12 neurova/sandbox/exec_sandbox.py`、*
*`grep -rn "kill_all" --include=*.py neurova/ tests/`、*
*`sed -n '48,70p' neurova/security/governance.py`、*
*`grep -n "CancelledError" -A 3 neurova/agent/tool_coordinator.py`。*
