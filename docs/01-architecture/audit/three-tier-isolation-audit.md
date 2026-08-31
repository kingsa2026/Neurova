# Neurova 三层隔离 / 多用户模块深度核查报告

**数据源**：`kingsa2026/Neurova@main`（HEAD `33d7329`，2026-08-28）
**核查方法**：`gh api` + `WebFetch` 拉 raw GitHub 源码，逐文件读取关键路径
**重点文件**：`isolation.py`、`mem_core.py`、`memory_layer/manager.py`、`context_pool.py`、`session_manager.py`、`api/deps.py`、`api/auth.py`、`security/rbac.py`、`channels/manager.py`、`mobile_pairing.py`、`collaboration_isolation.py`、`skill_system/skill_pool_manager.py`、`auth/user_model.py`、`auth/enhanced_user_model.py`

---

## 一、三层隔离的定义（`isolation.py`）

源文件：`neurova/cognitive_layers/memory_layer/isolation.py`

```python
@dataclass(frozen=True)
class IsolationContext:
    agent_id: str = "default"      # 第1层：Agent 隔离
    neuser_id: str = "default"     # 第2层：系统用户隔离
    user_id: str = "default"       # 第3层：对话用户隔离
    shared: bool = False
    share_group_ids: tuple = ()

    @property
    def key(self) -> str:
        return f"{self.agent_id}:{self.neuser_id}:{self.user_id}"
```

### ⚠️ 第一处隐患（已注释但值得提醒）

`from_legacy()` 类方法里写了：

> ```python
> # Bug 20 修复: owner 不应作为 agent_id 的 fallback
> # 旧版语义: owner 是数据归属者, 不是 agent_id; 强行 fallback 会污染隔离边界
> final_agent_id = agent_id or "default"
> final_user_id = user_id or owner or "default"
> ```

这条注释承认历史上犯过"把 owner 字段误当成 agent_id"的隔离错误 —— **隔离边界曾被污染**。

---

## 二、记忆层隔离（`MemoryManager` + `MemCore`）

### 2.1 表结构（`manager.py`）

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    ...
    agent_id    TEXT NOT NULL DEFAULT 'default',
    neuser_id   TEXT NOT NULL DEFAULT 'default',
    user_id     TEXT NOT NULL DEFAULT 'default',
    shared      INTEGER NOT NULL DEFAULT 0,
    ...
)
CREATE INDEX idx_mem_agent ON memories(agent_id)   -- ⚠️ 没有三层复合索引
-- 也没有 (neuser_id) / (user_id) 单独索引
```

**Bug 1**：唯一索引是 `agent_id` 单列，没有三层复合索引。隔离靠 WHERE 过滤，会扫表。

### 2.2 SELECT 隔离（已修复）

```sql
SELECT * FROM memories
WHERE agent_id = ? AND neuser_id = ? AND user_id = ?
ORDER BY created_at DESC
```

注释明确：

> ```python
> # Bug 4 修复: WHERE 子句原仅按 agent_id 过滤, 跨 neuser_id/user_id 加载记忆。
> # 现加上 AND neuser_id=? AND user_id=? 保证三层隔离。
> ```

✅ **已修复** —— 但 `_load_from_db` 只在初始化时调用一次，热路径查询不一定走这条路径。

### 2.3 ⚠️ Bug 2：DELETE 不校验三层隔离

```sql
DELETE FROM memories WHERE id = ?
```

`_delete_persisted_memory` 仅按 `id` 删除。**如果攻击者知道对方 memory 的 id，可以直接 DELETE 越权**。无 agent_id / neuser_id / user_id 校验。

### 2.4 ⚠️ Bug 3：INSERT OR REPLACE 按主键覆盖

```sql
INSERT OR REPLACE INTO memories (id, ..., agent_id, neuser_id, user_id, ...)
VALUES (?, ..., ?, ?, ?, ...)
```

`id` 是主键，`INSERT OR REPLACE` 不会校验三层元组是否匹配。**如果两个不同 (agent, neuser, user) 三元组生成的 id 冲突（UUID 极小概率，但 `id` 也可能是字符串时间戳等自定义格式），会发生跨用户覆盖。**

### 2.5 `_PersistDbStore` —— 三层隔离的 SQL 注入式强制

```python
conditions = "agent_id = :agent_id AND neuser_id = :neuser_id AND user_id = :user_id"
scoped = sql
if re.search(r"\bWHERE\b", scoped, re.IGNORECASE):
    scoped = re.sub(r"\bWHERE\b", f"WHERE {conditions} AND ", scoped, count=1, ...)
else:
    # ORDER BY / LIMIT 前插入 WHERE
    ...
```

✅ 这里做了一个聪明的"修补"：任何走 `_PersistDbStore.execute()` 的 SQL 都会被强制加上三层 WHERE。**这是当前最可靠的一道隔离屏障**（用于 MoE ExpertDrilldownRetriever 的 L0 下钻）。

### 2.6 MoE 路由器的三层注入（`mem_core.py`）

```python
store = self._build_moe_store()
# 构建时强制传入 (agent_id, neuser_id, user_id)
return _PersistDbStore(
    db_path=db_path,
    agent_id=getattr(manager, "_agent_id", "default"),
    neuser_id=getattr(manager, "_neuser_id", "default"),
    user_id=getattr(manager, "_user_id", "default"),
)
```

✅ MoE 路径隔离 OK。

---

## 三、会话层隔离（`SessionManager`）

源文件：`neurova/session_manager.py`

### 3.1 文件系统隔离（已实现）

```python
self._sessions_dir = Path("sessions")
def _get_session_dir(self, agent_id: str) -> Path:
    effective_agent_id = agent_id or "default"
    agent_dir = self._sessions_dir / effective_agent_id
    ...
```

**仅按 `agent_id` 分子目录**：

```
sessions/
├── default/
│   ├── session_abc_2026-08-30.json
│   └── ...
└── assistant_v2/
    └── session_xyz_2026-08-30.json
```

### ⚠️ Bug 3：会话只有 `agent_id` 一层隔离，没有 `neuser_id` / `user_id`

文件路径是 `sessions/<agent_id>/session_<session_id>_<date>.json`。**同一个 agent 下的所有 neuser / user 共享同一个目录**。意味着：

- 用户 A 创建 `session_abc` → 用户 B 通过 WS 拿到 session_id `abc` → 直接读取 A 的对话历史
- 没有任何机制把 session 限定到 user_id

### ⚠️ Bug 4：`SessionRecord` 数据结构里有 `user_id` 字段但写入时**未注入**

```python
@dataclass
class SessionRecord:
    agent_id: str
    session_id: str
    session_date: str
    messages: List[SessionMessage] = field(default_factory=list)
    ...
    user_id: str = ""        # ← 字段定义在，但 add_message 没写入
```

`add_message()` 写入 `agent_id` 但**不写 user_id**。这意味着即使加了 user_id 校验，也读不到归属。

### ⚠️ Bug 5：`mobile_pairing` 的 WS 直接拿到 `get_sessions(agent_id)` —— 无 user 过滤

```python
# neurova/api/endpoints/mobile_pairing.py: _handle_session_list
async def _handle_session_list(ws, data: dict):
    agent_id = data.get("agent_id", "default")
    sm = get_session_manager()
    sessions = sm.get_sessions(agent_id)   # ← 不传 user_id, 返回全部
```

**已配对的手机端可以拉取该 agent 下所有人的 session 列表**。配合 Bug 3，攻击者可枚举所有 session_id 然后 `get_session(agent_id, session_id)`。

### 3.2 Session 三锁（实现良好）

- `_file_locks`：每文件独立 `Lock`，DCL 双重检查（修复 TOCTOU）
- 线程锁：`with file_lock:` 包住 read-modify-write
- `fcntl.flock`：OS 级 advisory lock（Unix only）

✅ 这部分实现扎实。

---

## 四、API 层 user_id 注入（`api/deps.py` + `api/auth.py`）

### 4.1 JWT 携带的是什么

```python
# auth.py login endpoint
create_access_token(data={
    "sub": str(user["id"]),   # ← UserModel 的数字主键
    "username": user["username"],
    "role": user.get("role", "user"),
})
```

### 4.2 `get_memory_manager()` 依赖（**关键修复点**）

```python
def get_memory_manager(agent_id=None, user=None):
    agent = ...
    # 设置多用户隔离参数
    if user:
        agent.memory_manager.neuser_id = user.get("neuser_id", "default")
        agent.memory_manager.user_id = user.get("user_id", "default")
    else:
        agent.memory_manager.neuser_id = "default"
        agent.memory_manager.user_id   = "default"
    return agent.memory_manager
```

### ⚠️ Bug 6：`get_current_user()` 返回的字典**没有 `neuser_id` 字段**

```python
# auth.py: get_current_user()
return {
    "user_id": payload.get("sub", "unknown"),
    "username": payload.get("username", "unknown"),
    "role": payload.get("role", "user"),
}
```

**JWT payload 里只有 `sub` (UserModel.id)，没有 `neuser_id`**。所以 `user.get("neuser_id", "default")` **永远回退到 `"default"`**。

### ⚠️ Bug 7：`UserModel.id` 与三层隔离的 `neuser_id` **不是同一概念**

- `UserModel.id`：JWT subject，全局唯一数字主键
- 三层隔离的 `neuser_id`：本意是"系统用户 ID"，隔离级别 2
- **整个项目里没有任何地方把 JWT `sub` 映射成 `neuser_id`**

**结论：`neuser_id` 隔离层事实上从未生效，永远是 `"default"`**。

### ⚠️ Bug 8：跨用户内存状态污染

```python
# api/deps.py: get_memory_manager
agent.memory_manager.neuser_id = user.get("neuser_id", "default")
```

**`agent.memory_manager` 是单例上的属性**（Agent 在 app_state 里复用）。如果两个并发请求 A、B 各自调用 `get_memory_manager`：

1. 请求 A 进来 → 设 `neuser_id = A`
2. 请求 B 进来 → 设 `neuser_id = B`（覆盖 A）
3. 请求 A 的后续查询走 B 的隔离上下文 → **数据泄漏给 B**

没有锁保护这个赋值。

---

## 五、渠道层隔离（`channels/manager.py`）

```python
# _on_channel_event
user_id = getattr(message, "sender_id", None) or "anonymous"
agent_id = "default"   # ← 硬编码 "default"
session = sync_manager.create_session(
    user_id=user_id,
    agent_id=agent_id,
    external_id=message.chat_id,
    metadata={"channel_type": message.channel_type},
)
```

### ⚠️ Bug 9：渠道 agent_id 硬编码 `"default"`

所有渠道（飞书、钉钉、Telegram、Discord 等）的消息都路由到 **同一个 agent**。**没有任何 per-user / per-channel 的 agent 路由**。

### ⚠️ Bug 10：渠道无 user 过滤

```python
async def send_message(self, channel_type, chat_id, content, ...):
    # 没有 allowed_users / user_id 参数
```

`send_message` 不带 `user_id`，无 ACL 控制。任何能调到这个方法的代码都能给任何 chat 发消息。

---

## 六、Mobile Pairing 隔离（`mobile_pairing.py`）

### ✅ 实现正确的部分

```python
_pairing_codes: Dict[str, Dict] = {}        # code -> pairing info (含 user_id)
_paired_devices: Dict[str, Dict] = {}       # pairing_id -> device info (含 user_id)
_user_devices: Dict[str, Set[str]] = {}     # user_id -> {pairing_id}
```

```python
@router.delete("/pairing/{pairing_id}")
async def revoke_pairing(pairing_id, user_id = Depends(_get_current_user_id)):
    device = _paired_devices.get(pairing_id)
    if device["user_id"] != user_id:        # ✅ 设备所有权校验
        raise HTTPException(403, "Not your device")
```

✅ revoke 路径校验了设备归属。

### ⚠️ Bug 11：`confirm_pairing` 的 `user_id` 是从配对码带过来的，不是从请求者

```python
@router.post("/pairing/confirm")
async def confirm_pairing(request, body: ConfirmPairingRequest):
    pairing = _pairing_codes.get(body.code)
    # ← 没有 user_id 校验
    pairing["status"] = "confirmed"
    ws_token = _generate_ws_token(pairing["user_id"], pairing["pairing_id"])
```

**确认配对是公开端点（无 JWT），靠配对码做认证**。`pairing["user_id"]` 是 PC 端 `generate_pairing` 时写入的，理论上只有 PC 端的用户能产生这个码。但：

1. 配对码 6 位 → 300s TTL 内可暴力枚举（约 10⁶ 组合 / 5 分钟 = 3333 QPS）
2. 拿到有效 code 后，攻击者可凭 code 取得 `ws_token`，**直接用受害者的 user_id 建立 WS**

WS handler 只校验 `?token` 的 HMAC 签名，**签名正确即信任 user_id**：

```python
elif token:
    token_info = _verify_ws_token(token)   # ← 只验签, 不验当前连接者
    user_id = token_info["user_id"]
```

### ⚠️ Bug 12：WS 拿到 user_id 后, chat 直接走 `agent.chat(user_id=...)`

```python
async def _handle_chat_send(ws, data: dict, user_id: str):
    ...
    await agent.chat(content=..., session_id=..., user_id=user_id)
    # ← user_id 是从 WS token 解出来的, agent 信任它
```

**整个 WS 会话期间所有 `chat:send`、`session:list`、`session:create` 都用 token 里嵌的 user_id，无再认证**。Token 泄漏（HTTP 引用、access log、URL 复制）= 24h 完全控制权。

### ⚠️ Bug 13：WS 连接池 `_user_connections` 全局单例 + 无容量限制

```python
class MobileConnectionManager:
    _instance: Optional["MobileConnectionManager"] = None
    ...
    async def connect(self, websocket, user_id, connection_id):
        await websocket.accept()
        self._connections[connection_id] = websocket
```

- `_instance` 是**进程级单例**，多用户部署时所有用户的 WS 共享同一 dict
- 没有 max connection 限制，**DoS 友好**：恶意客户端可无限握手撑爆内存
- 没有 per-user 连接数限制，**单用户可绑定 N 个设备**（这可能是 feature，但应有显式上限）

---

## 七、Skill / Plugin 多用户隔离

### ✅ Skill Pool v2.0 隔离实现良好（`skill_pool_manager.py`）

```python
class SkillVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"
```

- 文件布局：`<data_dir>/skills/public/metadata.json` + `<data_dir>/skills/private/<user_id>/metadata.json`
- 每次 write 都校验 `owner_user_id == user_id`
- `share_private_skill` 把 visibility 升到 SHARED 并 append `shared_with`
- `push_skill_to_agent` 在 `pushed_to_agents: List[str]` 里追加

### ⚠️ Bug 14：Plugin 系统无用户隔离（`plugins/plugin_manager.py`）

按 `plugin_manager.py` 的代码组织：
- `_load_plugin_module`：`importlib.util.spec_from_file_location(name="neurova_plugin_{name}")`
- `_find_module_class`：返回第一个有 `__init__` 和 `on_enable` 的类

**没有任何 user_id / role / 租户概念**。插件加载到进程级 PluginRegistry，**所有用户共享同一份插件清单**。一旦某个用户上传恶意插件，全员受影响。

---

## 八、RBAC 系统（`security/rbac.py`）

### ✅ 26 权限 / 5 角色实现完整

```python
ROLE_PERMISSIONS = {
    "admin":     {p.value for p in Permission},  # 26 全部
    "operator":  {13 个权限},
    "developer": {10 个权限},
    "viewer":    {9 个权限},
    "guest":     {2 个权限},
}
```

- SQLite 存储（`~/.neurova/rbac.db`）
- 角色 / 用户角色映射 / 权限变更请求三表
- `_invalidate_cache` 模式 + 双层 cache（`_roles_cache` / `_user_roles_cache`）

### ⚠️ Bug 15：RBAC 与三层隔离**未整合**

- RBAC 是"全局 5 角色"，不管 agent_id / neuser_id / user_id
- RBAC 的 `user_id` 是 RBAC 自己的 user_id，**不是三层隔离的 user_id**

实际查询：

```python
# deps.py: require_role()
def check_role(user = Depends(get_current_user)):
    user_role = user.get("role", "user")   # ← JWT 的 role
    if user_role != required_role and user_role != "admin":
        raise HTTPException(403)
```

**整个项目用 JWT 里的 `role` 做权限校验，根本没有调 `RBACManager.has_permission()`**。

**RBAC 模块形同摆设**。

### ⚠️ Bug 16：两套并行的用户系统

| 系统 | 用户字段 | 存储 | 用途 |
|---|---|---|---|
| `UserModel` (sqlite `data/users.db`) | `id`, `username`, `password_hash`, `role` | SQLite | JWT subject |
| `EnhancedUserModel` (JSON files) | `id`, `username`, `email`, `group_type`, `quota` | JSON 文件 + RLock | **功能不重叠的另存一份** |

两个用户模型共存，**不互通**：
- `EnhancedUserModel` 有 `email`、`display_name`、`bio`、`avatar_url`、`quota`，但 `UserModel` 没有
- `EnhancedUserModel` 有 PBKDF2 100k iterations + lockout + login logs，但 `UserModel` 用 bcrypt + 5 attempts 锁定
- 登录流程只用 `UserModel`，`EnhancedUserModel` 是**孤立实现**

---

## 九、Collaboration 隔离（`collaboration_isolation.py`）

### ✅ 实现良好的部分

```python
class MemberRole(str, Enum):
    OWNER / ADMIN / EDITOR / VIEWER / GUEST
class ProjectVisibility(str, Enum):
    PRIVATE / TEAM / PUBLIC
```

- `ProjectMember.can_edit()` 返回 OWNER/ADMIN/EDITOR
- `_user_projects: Dict[str, Set[str]]` 二次索引
- `remove_member` / `update_member_role` 拒绝移除 OWNER 防锁死

✅ 这部分是 Neurova 实现最严谨的多用户模型。

---

## 十、问题汇总（按严重度）

| # | 严重度 | 位置 | 问题 | 攻击场景 |
|---|---|---|---|---|
| 1 | 🔴 P0 | `api/deps.py:get_memory_manager` | **无锁修改共享单例的 `neuser_id`/`user_id`** | 并发请求互相污染隔离上下文，跨用户读到对方记忆 |
| 2 | 🔴 P0 | `auth.py:get_current_user` | **JWT payload 无 `neuser_id` 字段** | `neuser_id` 隔离层事实上从未生效 |
| 3 | 🔴 P0 | `session_manager.py` | **session 只按 agent_id 分目录，不带 user_id** | 同 agent 下任何用户可读全 session |
| 4 | 🔴 P0 | `mobile_pairing.py:_handle_session_list` | **WS 内 session:list 不带 user 过滤** | 已配对手机可拉取该 agent 全员 session |
| 5 | 🔴 P0 | `mobile_pairing.py:_handle_*` | **WS 仅靠初始 token 鉴权，期间不再认证** | Token 泄漏 = 24h 完全控制受害者的 agent |
| 6 | 🟠 P1 | `manager.py:_delete_persisted_memory` | DELETE 仅按 `id`，无三层校验 | 知道对方 memory_id 可越权删除 |
| 7 | 🟠 P1 | `manager.py:_persist_memory` | INSERT OR REPLACE 按主键覆盖 | 三元组不同的两条记忆 id 冲突时跨用户覆盖 |
| 8 | 🟠 P1 | `mobile_pairing.py:confirm_pairing` | 6 位配对码 5 分钟 TTL 无速率限制 | 10⁶ / 300s = 3333 QPS 可枚举 |
| 9 | 🟠 P1 | `isolation.py:from_legacy` | 历史 Bug 20 注释承认 owner 曾被误用为 agent_id | 旧数据可能已污染隔离边界 |
| 10 | 🟠 P1 | `channels/manager.py` | 所有渠道 `agent_id="default"` 硬编码 | 无 per-channel/per-user agent 路由 |
| 11 | 🟡 P2 | `manager.py` schema | 仅 `idx_mem_agent` 单列索引，无三层复合索引 | 大数据量下隔离查询全表扫 |
| 12 | 🟡 P2 | `MobileConnectionManager` | 无 per-user 连接数限制，无全局连接上限 | 单客户端可耗尽内存 |
| 13 | 🟡 P2 | `plugins/plugin_manager.py` | 无 user_id / tenant 隔离 | 恶意插件全员受影响 |
| 14 | 🟡 P2 | `security/rbac.py` | 整个项目无调用 `RBACManager.has_permission` | RBAC 26 权限形同摆设 |
| 15 | 🟡 P2 | 双 UserModel | `UserModel` + `EnhancedUserModel` 并存不互通 | 用户信息不一致、登录审计断层 |
| 16 | 🟡 P2 | `auth.py` | JWT `role` 仅用作 if-else，不走 RBAC | admin / user 是字符串，不是权限模型 |
| 17 | 🟢 P3 | `auth.py:_load_or_create_secret_key` | JWT secret 三级 fallback（env → .jwt_secret → auto），但自动生成时无任何告警 | 容器重启后密钥轮换导致旧 token 失效，无审计 |
| 18 | 🟢 P3 | `mobile_pairing.py` | 配对码用 `random.randint`（非 `secrets`） | 理论上可预测 |

---

## 十一、修复建议（按 ROI 排序）

### P0 — 必修（数据安全）

#### 1. JWT payload 增加 `neuser_id` 字段（30 分钟）

- `auth.py:login` 端点登录成功后从 `EnhancedUserModel.get_user_by_id` 取 neuser_id，写入 `sub` claim 旁
- `auth.py:get_current_user` 在返回值里附 `neuser_id`
- 这是修复 Bug 1/2 的前置条件

#### 2. `get_memory_manager` 加锁 + per-request 隔离上下文快照（半天）

- 改为返回 `IsolationContext` 快照而不是修改共享单例
- `MemoryManager` 内部用 `threading.local()` 存 per-thread isolation
- 或者：每次请求 new 一个 `MemoryManager` 实例（agent_id 不变，neuser_id / user_id 变）

#### 3. Session 加 user_id 路径层（1 天）

- 路径改为 `sessions/<agent_id>/<neuser_id>/<user_id>/session_*.json`
- 兼容老路径：扫描时 fallback 到原位置并 lazy migrate
- `SessionRecord.user_id` 字段必须在 `add_message` 里强制写入

#### 4. `mobile_pairing` WS 增加 per-message 鉴权 challenge（半天）

- WS 升级后每次 chat:send 携带 `seq + nonce`，服务端校验递增
- 或者：WS 连接后 5 分钟不发消息即主动断开，要求重连

### P1 — 应修（防御深度）

#### 5. `mobile_pairing.py:confirm_pairing` 加速率限制（2 小时）

- 同 IP 5 分钟内最多 5 次 confirm 尝试
- 失败累计超过阈值锁定该 IP 30 分钟

#### 6. `mobile_pairing.py:_generate_pairing_code` 改用 `secrets`（5 分钟）

```python
import secrets
code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
```

#### 7. `manager.py` 增加三层复合索引 + DELETE/UPDATE 加 WHERE 三元组（半天）

```sql
CREATE INDEX idx_mem_3tier ON memories(agent_id, neuser_id, user_id)
DELETE FROM memories WHERE id=? AND agent_id=? AND neuser_id=? AND user_id=?
```

#### 8. `channels/manager.py` 增加 per-channel agent 路由表（1 天）

- 加 `channel_agent_routing: Dict[channel_type, agent_id]`
- 加 `channel_user_acl: Dict[channel_type, Set[user_id]]`

### P2 — 宜修（架构整理）

#### 9. 统一 `UserModel` 与 `EnhancedUserModel`（1 周）

- 选 `EnhancedUserModel` 作主（功能更全：email/quota/login logs）
- 弃用 `UserModel`，保留 `authenticate_user` 的 SQLite fast path 但走 EnhancedUserModel

#### 10. 真正激活 RBAC（半天）

- 把 JWT `role` 替换为从 `RBACManager.get_user_permissions(user_id)` 查
- 改写 `deps.require_role` 走 RBAC

#### 11. Plugin 系统加租户隔离（3 天）

- `PluginRegistry` 加 `_tenant_plugins: Dict[tenant_id, Dict[str, PluginRecord]]`
- `_load_plugin_module` 接受 `tenant_id` 参数

---

## 十二、结论

**Neurova 三层隔离架构的设计是扎实的**：
- `IsolationContext` 不可变 dataclass + `.key` 三元组拼接
- `_PersistDbStore` 用正则注入 WHERE 强制三层隔离（最优雅的一道屏障）
- Skill Pool 的 `owner_user_id` 检查每次 write 都跑
- Collaboration 是目前隔离最严谨的子系统

**但实施严重落后于设计**：
- `neuser_id` 第二层隔离从 JWT 路径到 API 依赖到 manager 注入全是断的，**事实上是死层**
- `get_memory_manager` 的并发赋值是经典竞态，**单实例部署都可能跨用户泄漏**
- 会话层只有 agent_id 一层，user_id 字段写了 dataclass 却从不写入
- WS 用 token 一次性绑定 user_id 后续不再认证，泄漏即沦陷
- RBAC 完整实现但全局零调用

**优先级最高的三件事**（组合起来 1.5 天内可完成）：
1. JWT payload 加 `neuser_id` 字段 + 修复 `get_current_user` 返回值（30 分钟）
2. `get_memory_manager` 改为返回 snapshot，不修改共享单例（半天）
3. SessionManager 加 `user_id` 路径层 + `add_message` 强制写入 user_id（半天）

完成后能消除全部 P0 数据泄漏路径，**不破坏现有 API 契约**。

---

报告版本 v1.0 · 2026-08-30