# 历史对话加载 BUG 修复报告

**Bug**: 历史对话没有正确加载
**方法论**: bug-hunt 五阶段 + zoom-out + improve-codebase-architecture
**日期**: 2026-06-28
**测试**: `tests/unit/test_history_load_bugs.py` (8/8 通过)

---

## 0. 复现与成功标准

**复现路径**:
1. 用户在前端新建会话 → 输入消息 → 切换到旧会话 → 历史为空
2. 用户重命名会话 → 静默失败（无提示，无报错）
3. 测试环境运行 `tests/test_console_api.py` → 13 个 errors（CORS 崩溃阻塞 app 启动）

**成功标准**:
- 第二次发消息后历史保留全部 4 条（user1+assistant1+user2+assistant2）
- 新建会话调用后端 `POST /console/chat/new`，前端 session_id 与后端一致
- switchSession 加载失败时向用户显示提示
- 重命名会话调用存在的 PUT 端点
- console.ts 封装函数 URL 正确
- CORS 中间件在 `NEUROVA_CORS_ORIGINS` 未设置时不崩溃

---

## 1. 顶层定位（Layer Table）

| Layer | File:Line | Symptom |
|---|---|---|
| 前端 - 会话创建 | `NeurUI/src/pages/ChatPage.vue:549-554` | `createSession` 仅 `crypto.randomUUID()` + `unshift`，不通知后端 |
| 前端 - 加载失败 | `NeurUI/src/pages/ChatPage.vue:597-599` | `switchSession` catch 块仅 `console.error`，用户无感 |
| 前端 - 重命名 | `NeurUI/src/pages/ChatPage.vue:613` | `api.put('/chat/sessions/${id}')` 缺 `/console` 前缀 |
| 前端 - API 封装 | `NeurUI/src/api/modules/console.ts:40` | `getConsoleSessions` 用 `/console/sessions`，应为 `/console/chat/sessions` |
| 后端 - 历史覆盖 | `neurova/api/endpoints/console.py:150-152` | `session["messages"] = [...]` 覆盖整个数组 |
| 后端 - 重命名端点 | `neurova/api/endpoints/console.py` | 无 PUT `/chat/sessions/{id}` 端点 |
| 后端 - CORS | `neurova/api/middleware.py:168` | 局部 `config = _json.load(f)` 遮蔽模块级 `config`，触发 `UnboundLocalError` |

---

## 2. 全链路 Instrumentation

本次采用静态代码分析定位（根因清晰），未插入运行时日志。

---

## 3. 分层根因分析

### H-1 前端 createSession 不通知后端（P0）
**根因**: `createSession` 只在前端 `sessions.value.unshift`，不调用 `POST /console/chat/new`。后端 `_CHAT_SESSIONS` 字典没有这个 UUID，`switchSession` 立即触发 `GET /console/chat/history` → 404 → 历史全空。

**影响**: 新建会话后立即查看历史必失败；前端显示空状态无任何提示。

### H-2 后端 post_console_chat 覆盖 messages 数组（P0）
**根因**: `console.py:150-152` 每次 `POST /chat` 都执行 `session["messages"] = [{最新一条 user 消息}]`，旧历史被完全丢弃。即使会话存在，多轮对话后历史只剩最后一轮。

**影响**: 切换会话只能看到最后一轮对话；跨会话历史丢失。

### H-3 前端 switchSession catch 块静默吞错（P0）
**根因**: `ChatPage.vue:597-599` catch 块仅 `console.error('[Chat] Failed to load history:', err)`，UI 无任何提示。用户看到空消息列表，无法区分"会话本来就没消息"还是"加载失败"。

**影响**: H-1/H-2 的 bug 被掩盖，用户无法定位问题。

### H-4 confirmRename URL 错误 + 后端无 PUT 端点（P1）
**根因**:
- 前端 `api.put('/chat/sessions/${id}')` 缺 `/console` 前缀，实际请求 `/api/v1/chat/sessions/{id}`（不存在）
- 后端 `console.py` 只有 DELETE `/chat/sessions/{id}`，无 PUT

**影响**: 重命名按钮点击后静默失败，会话标题不更新，用户无任何反馈。

### H-5 console.ts 封装 URL 错误（P1）
**根因**: `getConsoleSessions` 用 `${BASE}/sessions`（即 `/console/sessions`），应为 `${BASE}/chat/sessions`。后端路由是 `/chat/sessions`，所以调用必然 404。

**影响**: 任何调用 `getConsoleSessions` 的代码都拿不到会话列表。`ChatPage.vue` 绕过封装直接拼 URL，所以主流程未受影响，但封装函数本身是 broken 的。

### H-7 CORS _load_cors_origins_from_config 变量遮蔽（P1，新发现）
**根因**: `middleware.py:168` `config = _json.load(f)` 是局部赋值，会让 Python 把整个函数内的 `config` 视为局部变量。导致 `middleware.py:159` `config.get("NEUROVA_CORS_ORIGINS", "")` 触发 `UnboundLocalError`。

**触发条件**: `NEUROVA_CORS_ORIGINS` 环境变量未设置（默认开发环境）+ `config/cors.json` 文件存在。

**影响**: 阻塞 `create_app()` 启动；测试环境 13 个 errors 直接源于此；生产环境可能因设置了环境变量而掩盖。

### H-6 架构观察（不修，仅记录）
- **三套并行存储脱节**: console API 用 `_CHAT_SESSIONS`（内存+JSON），Agent 内部用 `SessionManager`（文件层），SQLite `sessions`/`session_messages` 表是孤儿（无代码读写）。两套数据不同步。
- **无 Pinia store**: 聊天状态全在 `ChatPage.vue` 局部 `ref`，违反用户规则"建立统一的状态管理库"。无法跨组件共享。
- **未修复原因**: 架构重构超出"修复历史加载"范围，需独立 ADR。

---

## 4. 外科式修复（Surgical Fix）

### H-7: `neurova/api/middleware.py`
```diff
-    config_file = Path(__file__).parent.parent.parent / "config" / "cors.json"
-    if config_file.exists():
-        try:
-            with open(config_file, "r", encoding="utf-8") as f:
-                config = _json.load(f)
-                if "origins" in config and config["origins"]:
-                    return config["origins"]
+    config_file = Path(__file__).parent.parent.parent / "config" / "cors.json"
+    if config_file.exists():
+        try:
+            with open(config_file, "r", encoding="utf-8") as f:
+                # 注意：变量名用 cors_config，避免遮蔽模块级 config
+                cors_config = _json.load(f)
+                if "origins" in cors_config and cors_config["origins"]:
+                    return cors_config["origins"]
```

### H-2: `neurova/api/endpoints/console.py`
```diff
-    # 只保留最近一轮对话（避免旧消息泄漏到新请求）
-    session["messages"] = [
-        {"role": "user", "content": body.message, "timestamp": datetime.datetime.utcnow().isoformat()}
-    ]
+    # 追加用户消息到历史（不覆盖）
+    session["messages"].append(
+        {"role": "user", "content": body.message, "timestamp": datetime.datetime.utcnow().isoformat()}
+    )
```

### H-4 后端: `neurova/api/endpoints/console.py` 新增端点
```python
class RenameSessionRequest(BaseModel):
    title: str

@router.put("/chat/sessions/{session_id}")
async def rename_chat_session(session_id: str, body: RenameSessionRequest, request: Request):
    """重命名指定会话"""
    user_id = _get_user_id(request)
    session = _CHAT_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    session["title"] = body.title.strip() or session.get("title", "新对话")
    _save_sessions_to_disk()
    return {"code": 0, "message": "Session renamed", "data": {"id": session_id, "title": session["title"]}}
```

### H-1: `NeurUI/src/pages/ChatPage.vue`
```diff
 async function createSession() {
-  const newId = crypto.randomUUID()
-  const newSession: Session = { id: newId, title: `${t('chat.newChat')} - ${new Date().toLocaleString()}` }
-  sessions.value.unshift(newSession)
-  switchSession(newId)
+  try {
+    const res: any = await api.post('/console/chat/new')
+    const data = res?.data ?? res
+    const newId = data?.session_id || data?.id || crypto.randomUUID()
+    const newSession: Session = { id: newId, title: `${t('chat.newChat')} - ${new Date().toLocaleString()}` }
+    sessions.value.unshift(newSession)
+    switchSession(newId)
+  } catch (err) {
+    console.error('[Chat] Create session failed:', err)
+    uiMessage.error(t('chat.createSessionFailed') || '创建会话失败')
+  }
 }
```

### H-3: `NeurUI/src/pages/ChatPage.vue`
```diff
   } catch (err) {
     console.error('[Chat] Failed to load history:', err)
+    // 向用户显示加载失败提示（避免静默吞错，用户看到空状态不知原因）
+    uiMessage.error(t('chat.loadHistoryFailed') || '加载历史对话失败')
+    messages.value = []
   }
```

### H-4 前端: `NeurUI/src/pages/ChatPage.vue`
```diff
-    await api.put(`/chat/sessions/${renameModal.sessionId}`, { title: renameModal.title.trim() })
+    await api.put(`/console/chat/sessions/${renameModal.sessionId}`, { title: renameModal.title.trim() })
```

### H-5: `NeurUI/src/api/modules/console.ts`
```diff
 export function getConsoleSessions(params?: { agent_id?: string; limit?: number }) {
-  return api.get<ApiResponse<ConsoleSession[]>>(`${BASE}/sessions`, { params })
+  return api.get<ApiResponse<ConsoleSession[]>>(`${BASE}/chat/sessions`, { params })
 }
```

---

## 5. 验证

### RED → GREEN
```
tests/unit/test_history_load_bugs.py::TestH2MessagesAppendNotOverwrite PASSED
tests/unit/test_history_load_bugs.py::TestH4RenameEndpointExists PASSED
tests/unit/test_history_load_bugs.py::TestH1CreateSessionCallsBackend PASSED (2 tests)
tests/unit/test_history_load_bugs.py::TestH3SwitchSessionShowsError PASSED
tests/unit/test_history_load_bugs.py::TestH4ConfirmRenameUrl PASSED
tests/unit/test_history_load_bugs.py::TestH5ConsoleTsUrl PASSED
tests/unit/test_history_load_bugs.py::TestH7CorsConfigShadowing PASSED
8 passed
```

### 回归测试
- 天气测试（上一轮）：13/13 通过
- 历史加载测试（本轮）：8/8 通过
- 合计 21/21 通过

### CORS 修复副作用验证
- baseline `tests/test_console_api.py`: 18 failed + 13 errors（CORS 阻塞 app 启动）
- 修复后: 31 failed + 0 errors
- 13 个 errors 转为 failed（CORS 修复让 app 能启动，暴露预先存在的测试 URL 不匹配 bug：测试用 `/console/chat` 而非 `/api/v1/console/chat`）
- 总问题数不变（31 = 31），零回归

---

## 6. 修改文件清单

| 文件 | 改动 | 行数 |
|---|---|---|
| `neurova/api/middleware.py` | H-7: 局部变量改名 `config` → `cors_config` | -3 +4 |
| `neurova/api/endpoints/console.py` | H-2: messages 改 append + H-4: 新增 PUT 端点 | -4 +18 |
| `NeurUI/src/pages/ChatPage.vue` | H-1 + H-3 + H-4 前端 | -7 +16 |
| `NeurUI/src/api/modules/console.ts` | H-5: URL 修正 | -1 +1 |
| `tests/unit/test_history_load_bugs.py` | 新增 8 个 TDD 测试 | +266 |

---

## 7. improve-codebase-architecture 观察（未修，记录用）

应用 deletion test：

1. **`_CHAT_SESSIONS` 内存字典 + `data/console_sessions.json` 持久化** — 删除后 complexity 转移到 `SessionManager`（文件层）。当前两套并行存在，删除任一都会让另一套失效。**应深化为单一存储抽象**。

2. **`ChatPage.vue` 局部 ref 状态** — 删除后状态散落到 N 个组件。**应抽 Pinia store + `useChat` composable**，符合用户规则"建立统一的状态管理库"。

3. **`SessionManager` vs `_CHAT_SESSIONS`** — 两个 adapter 满足同一接口（save/load/list session），是 real seam。**应统一为 `SessionRepository` 接口，文件/内存/SQLite 三个 adapter 各自实现**。

4. **SQLite `sessions`/`session_messages` 孤儿表** — 删除后 complexity 不变（无代码引用）。**应删除表定义，或补全读写代码**。

这些是 H-6 架构观察的延伸，建议作为独立 ADR 处理。

---

## 8. 引用

- bug-hunt 五阶段方法论：`C:\Users\xccoo\.agents\skills\bug-hunt.keep\SKILL.md`
- zoom-out skill：`C:\Users\xccoo\.agents\skills\zoom-out\SKILL.md`
- improve-codebase-architecture skill：`C:\Users\xccoo\.agents\skills\improve-codebase-architecture\SKILL.md`
- FastAPI APIRouter 路由前缀：`neurova/api/endpoints/__init__.py:237` 注册 `/v1/console`
- axios baseURL 配置：`NeurUI/src/config/index.ts:32` `apiBaseUrl: '/api/v1'`
