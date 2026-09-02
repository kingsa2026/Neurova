# Bug Fix: 删除会话误弹"加载历史对话失败"提示

- **Bug ID**: chat.loadHistoryFailed
- **Date**: 2026-07-15
- **Status**: Fixed (架构深化 — `silent: boolean` → `SwitchResult` + `notifySwitchFailure`)
- **Skill**: bug-hunt (5 阶段方法论) + tdd (vertical slice RED→GREEN) + zoom-out + improve-codebase-architecture (deletion test + shallow/deep module)
- **Scope 扩展**: 本轮在原"删除场景"基础上,顺手修复了"未修的边界情况" (`loadSessions` auto-select + `createSession` post-create 历史加载失败误弹 toast) — 详见 §6 架构深化

## 0. 复现与界定

**症状**：用户点击删除当前激活会话后,前端弹出 `chat.loadHistoryFailed`（"加载历史对话失败"）toast,让用户误以为删除操作失败。实际上后端 DELETE 调用已成功,会话已被删除。

**成功标准**：删除会话后,若自动 switch 到剩余会话时历史加载失败,不应弹 error toast;只有删除操作本身失败才提示用户。

## 1. 顶向下定位 — 层级表

| 层级 | 文件:行号 | 角色 |
|------|----------|------|
| UI 触发 | `NeurUI/src/pages/ChatPage.vue:549` | `deleteSession(sessionId)` 委托给 useChat |
| Composable | `NeurUI/src/composables/useChat.ts:179-198` | `deleteSession` 删后自动 switchSession 加载剩余 |
| Composable | `NeurUI/src/composables/useChat.ts:155-159` | `switchSession` 加载历史失败时无条件 `options.onError?.(msg)` 弹 toast |
| API 客户端 | `NeurUI/src/api/modules/console.ts:44-46` | `deleteConsoleSession` DELETE 调用 |
| 后端端点 | `neurova/api/endpoints/console.py:243-257` | `delete_chat_session` (验证通过,非根因) |
| 后端端点 | `neurova/api/endpoints/console.py:198-212` | `get_chat_history` 找不到 session 返回 404 |

## 2. 全链路埋点

跳过 (Phase 1 静态代码已清晰显示根因: `switchSession` 错误处理不区分调用上下文)。

## 3. 分层根因分析

**根因链**:

1. **直接原因**: `switchSession` 在 catch 块 (line 155-159) 无条件调用 `options.onError?.(msg)` 弹 `chat.loadHistoryFailed` toast。
2. **结构原因**: `switchSession` 既被用户主动调用（点击切换会话）,也被 `deleteSession` (line 178) 作为副作用自动调用。两种场景错误语义不同:
   - 用户主动切换: 加载失败应提示错误（用户期待看到历史）
   - 自动副作用（删除后切换）: 加载失败应静默（用户的主要意图是删除,不是切换）
3. **设计气味**: `switchSession` 把"加载历史"和"切换会话"耦合在一起,但错误处理没有区分调用上下文。

## 4. 手术修复 + 验证

### 修复方案 — 架构深化 (silent boolean → SwitchResult)

原"加 `silent: boolean` 浅参数"方案在 §5 设计反思中被识别为 **shallow module smell**:
- 接口泄漏调用上下文 (boolean 标记调用方语义)
- 决策空间被压成二值 (silent=true/false)
- 编译器不强制下一个调用方传 silent (新增调用点可能漏传)
- deleteSession/loadSessions/createSession 三个调用方各自维护"该不该传 silent"的隐式契约

**深化重构**: 把错误策略从接口参数移到调用方,`switchSession` 只返回 `SwitchResult`,
是否弹 toast 由调用方 own (调 `notifySwitchFailure` helper 或静默消费)。

### 修复 diff

**`NeurUI/src/composables/useChat.ts`** — 新增 `SwitchResult` 类型 + `switchSession` 返回结果 (不弹 toast):

```typescript
// 接口契约: switchSession 不再决定错误策略, 仅返回 ok/error
export type SwitchResult = { ok: true } | { ok: false; error: unknown }

async function switchSession(sessionId: string): Promise<SwitchResult> {
  store.setCurrentSession(sessionId)
  store.clearMessages()
  switchingSession.value = true
  try {
    // ... history mapping logic 不变 ...
    store.setMessages(mapped)
    bus.emit('chat:session-switched', { sessionId })
    return { ok: true }
  } catch (err) {
    console.error('[Chat] Failed to load history:', err)
    store.clearMessages()
    return { ok: false, error: err }   // 不调 onError — 交给调用方
  } finally {
    switchingSession.value = false
  }
}
```

**`NeurUI/src/composables/useChat.ts`** — 新增 `notifySwitchFailure` helper (错误策略外置):

```typescript
/**
 * 用户主动切换场景的错误策略: 历史加载失败时弹 toast.
 * 仅 ChatPage.switchSession wrapper (用户点击侧栏 session 项) 应调用.
 * 副作用调用 (loadSessions/createSession/deleteSession 内部自动切换) 不调,
 * 避免让用户误以为主操作失败.
 */
function notifySwitchFailure(result: SwitchResult): void {
  if (!result.ok) {
    const msg = options.errorMessage?.('chat.loadHistoryFailed', '加载历史对话失败') ?? '加载历史对话失败'
    options.onError?.(msg)
  }
}
```

**`NeurUI/src/composables/useChat.ts`** — 三个副作用调用方静默消费 `SwitchResult`:

```typescript
// loadSessions (line 77-82): 自动选第一个 session — 不调 notifySwitchFailure
if (store.sessions.length > 0 && !store.currentSessionId) {
  await switchSession(store.sessions[0].id)   // 失败结果静默丢弃
}

// createSession (line 104-108): 创建成功后自动切换 — 不调 notifySwitchFailure
store.addSession(newSession)
await switchSession(newId)                     // 创建已成功, 历史失败不应掩盖

// deleteSession (line 221-226): 删除后自动切换 — 不调 notifySwitchFailure
if (store.sessions.length > 0) {
  await switchSession(store.sessions[0].id)   // 失败结果静默丢弃
}
```

**`NeurUI/src/pages/ChatPage.vue`** — wrapper 调用 `notifySwitchFailure` (用户主动场景):

```typescript
async function switchSession(sessionId: string): Promise<void> {
  const result = await _switchSession(sessionId)
  _notifySwitchFailure(result)   // 用户主动切换 → 失败时弹 toast
  scrollToBottom()
}
```

### 验证 — TDD vertical slice (7 个 slice, RED→GREEN)

| Slice | 测试 | 契约 |
|-------|------|------|
| 1 | `returns { ok: true } on successful history load` | 成功路径返回 `{ ok: true }` |
| 2 | `returns { ok: false, error } and clears messages on API error (does NOT call onError — caller decides)` | 失败路径返回 error, **不**内部弹 toast |
| 3a | `notifySwitchFailure calls onError with i18n message when result is failure` | helper 失败时弹 toast |
| 3b | `notifySwitchFailure does NOT call onError when result is ok` | helper 成功时不弹 |
| 3c | `notifySwitchFailure falls back to hardcoded message when errorMessage option is absent` | 缺 i18n fallback |
| 4 | `auto-selecting first session on history load failure does NOT call onError (side-effect, silent)` | **遗留边界情况**: loadSessions auto-select 静默 |
| 5 | `does NOT call onError when post-create history load fails (creation succeeded, side-effect silent)` | **遗留边界情况**: createSession post-create 静默 |
| 6 | `deleteSession silent contract preserved` (原 slice, 保留) | 删除场景不弹 toast |

**哨兵翻转验证 (slice 4 — 遗留边界情况)**:
- 修复前 (RED): `expected "spy" to not be called with arguments: ['加载历史对话失败']` — loadSessions auto-select 历史失败时 spy 被调 1 次
- 修复后 (GREEN): 33/33 PASS

### 回归验证

```
Test Files  1 passed (1)
     Tests  33 passed (33)
```

零新回归 (26 原测试全保留 + 7 新 slice 通过)。TypeScript `vue-tsc` 用 `findstr /i "useChat ChatPage SwitchResult notifySwitchFailure"` 验证零新错误 (预存 50+ 错误均与本次修改无关)。

## 5. 设计反思

### 改动范围 (surgical changes — 架构深化版)

本轮深化重构动了 4 处 (useChat.ts 内 + ChatPage.vue wrapper):

1. `useChat.ts` — 新增 `SwitchResult` discriminated union 类型导出
2. `useChat.ts` — `switchSession` 签名从 `Promise<void>` 改为 `Promise<SwitchResult>`,catch 块移除 `onError` 调用
3. `useChat.ts` — 新增 `notifySwitchFailure` helper (错误策略外置) + 导出
4. `ChatPage.vue` — wrapper 改写为 `_switchSession` + `_notifySwitchFailure` 两步调用

**未改契约的部分**:
- 三个副作用调用方 (`loadSessions` / `createSession` / `deleteSession` 内部 `await switchSession(...)`) — 不再传 silent 参数,直接消费返回值
- Pinia store (`stores/chat.ts`) 接口未变
- 事件总线 (`bus/index.ts`) `chat:session-switched` 事件未变
- 后端 `delete_chat_session` / `get_chat_history` 端点 (验证通过,非根因)

### 不再存在"未修的边界情况"

上一轮报告 §5 末尾标注的"`loadSessions` auto-select 留作后续优化"已在本轮架构深化中顺带修复 — 见 §6 架构深化的 "deletion test" 小节。`createSession` post-create 历史失败同理。

## 6. 架构深化 (improve-codebase-architecture)

### 触发: shallow module smell

原方案"加 `silent: boolean` 浅参数"被识别为 shallow module smell:

| 反模式 | 症状 |
|--------|------|
| 接口泄漏调用上下文 | `silent: boolean` 标记调用方语义,接口变成"我知道我是谁"的开关 |
| 决策空间被压成二值 | silent=true/false 只有两种策略,无法表达"创建成功但历史失败时弹部分 toast"等中间状态 |
| 编译器不强制下一个调用方传 silent | 新增第 N 个调用点若漏传 `silent=true`,bug 静默回归 (无类型错误) |
| 隐式契约扩散 | `loadSessions` / `createSession` / `deleteSession` 三个调用方各自维护"该不该传 silent"的注释,知识散在 N 处 |

### Deletion test (improve-codebase-architecture)

> 删除一个模块后,复杂度是否集中 (好) 还是分散到 N 个调用方 (pass-through smell)?

**应用**: 想象删除 `switchSession` 的错误处理逻辑 (silent 分支):

- **silent 方案**: 复杂度散在 3 个调用方 (`loadSessions` / `createSession` / `deleteSession`),每个调用方有"该不该传 silent"的隐式注释 — **pass-through smell, 删除后复杂度分散**
- **SwitchResult 方案**: 复杂度集中在 1 个 `notifySwitchFailure` helper,3 个副作用调用方只剩一行 `await switchSession(...)`,错误策略独立可替换 — **删除 helper 只影响 ChatPage wrapper, 副作用调用方零影响**

### Shallow → Deep module 转换

| 维度 | silent (shallow) | SwitchResult (deep) |
|------|------------------|---------------------|
| 接口宽度 | `switchSession(id, silent?)` — 参数暴露调用上下文 | `switchSession(id) → SwitchResult` — 接口纯净 |
| 错误策略 | 焊死在 catch 块 (`if (!silent) onError`) | 外置到 `notifySwitchFailure`,调用方 own |
| 新增调用点 | 必须决定 silent=true/false (易漏传) | 默认静默,显式调 helper 才弹 toast (fail-safe) |
| 删除 helper | 影响所有调用方 (移除 silent 参数链) | 只影响 ChatPage wrapper (单一调用方) |
| 编译期保证 | 无 (silent 是 runtime 值) | SwitchResult 类型 + `result.ok` discriminated union (TS narrowing 强制) |

### Fail-safe 原则

新方案让"副作用调用方漏调 `notifySwitchFailure`"成为默认行为 (静默),而非"漏传 `silent=true`"导致 bug。
- **silent 方案的 fail mode**: 漏传 silent → 误弹 toast (用户感知 bug)
- **SwitchResult 方案的 fail mode**: 漏调 helper → 静默吞错 (console.error 仍在, 但用户看不到 toast)

后者可接受 (副作用场景本就应静默),前者不可接受 (用户误以为主操作失败)。

### 总结

深化重构把"`switchSession` 内部决定错误策略"改为"调用方决定错误策略",
符合 user rules 中"建立统一的函数调用库"的契约: composable 只暴露纯接口 + helper,
错误策略由 UI 包装层 (ChatPage) 决定,不泄漏到 composable 接口。

## References

- ADR 0008: SessionRepository 统一会话存储接口
- `docs/bugfix-history-load-bugs.md` §H-1: 前端/后端 session_id drift 问题
- bug-hunt skill: 5 阶段方法论 (Phase 0 复现 → Phase 1 层级表 → Phase 3 根因 → Phase 4 修复 → Phase 5 报告)
- tdd skill: vertical slice (一测一实现, RED→GREEN)
- zoom-out skill: 模块地图 (ChatPage → useChat → api/store/bus, 4 个 switchSession 调用点分类)
- improve-codebase-architecture skill: deletion test + shallow/deep module + 接口宽度
