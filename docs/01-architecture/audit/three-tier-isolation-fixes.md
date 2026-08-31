# 三层隔离审计修复报告

**对应审计**：[three-tier-isolation-audit.md](three-tier-isolation-audit.md)（2026-08-30）
**方法**：逐条核实 → 红灯测试（TDD）→ 修复 → 回归比对基线
**新测试**：23 个，全部通过（`tests/unit/api/test_memory_request_scope.py` 11、`test_jwt_identity_claims.py` 6、`test_mobile_pairing_isolation.py` 6）

---

## 一、核实结论与修复对照

### P0（数据安全）— 已修复

#### 1. `get_memory_manager` 并发污染 + 隔离注入从未生效（审计 #1、#2、Bug 6/7/8）

**核实结果：比审计更严重。** `MemoryManager.neuser_id/user_id` 是只读 property（无 setter）：

- `api/endpoints/memory/base.py` 的赋值被 `except AttributeError: pass` **静默吞掉**——隔离注入从未生效过；
- `api/deps.py` 的赋值会直接抛 AttributeError → HTTP 500；
- 即使可以赋值，共享单例上无锁修改仍是审计指出的并发竞态。

**修复**（根因层）：
- `memory_layer/manager.py` 新增 ContextVar 请求作用域：`set_request_scope()` / `request_scope()` 上下文管理器 + `_eff_neuser_id()/_eff_user_id()/_scoped_memories()`。作用域绑定请求任务/线程上下文，不修改单例状态，并发请求互不污染。
- 读路径统一按生效三元组过滤：`recall`（含原**完全不过滤**的 `use_semantic=False` 关键词路径）、`_semantic_recall`（补上漏掉的 neuser 层）、`get_memories`、`get_crystallized`、`get_stats`。
- 两个 `get_memory_manager` 实现（`base.py`/`deps.py`）改调 `set_request_scope`。

#### 2. JWT 无身份声明（审计 Bug 6/7、P0-2）

**核实属实**：login/refresh/register 只写 `sub/username/role`。

**修复**：三处签发点均写入 `neuser_id`/`user_id`（= 账号 id，即 `sub`）。`auth.py` 新增 `_user_identity()` helper，deps.py 与 auth.py 共 5 个 `get_current_user` 系列函数统一走它，返回值新增 `neuser_id`；存量无声明 Token 回退 `sub`。

#### 3. 会话隔离（审计 #3、#4、Bug 3/4/5）

**核实结果：部分过时。** `create_session` 现已写入 `user_id` 字段且 `list_sessions(agent_id, user_id)` 支持过滤（此前 chat-round-ops 工作已做）；真正的缺口是 **mobile WS 读取路径不过滤**。

**修复**：`mobile_pairing._handle_session_list` 改为 `list_sessions(agent_id, user_id)`（只返回本用户摘要而非全员完整对话）；`_handle_session_create` 绑定创建者 `user_id`。会话文件**路径分层**（`sessions/<agent>/<user>/`）未实施——属侵入性迁移，读取侧强制过滤已封住 API 层泄漏面，列为后续项。

#### 4. WS 仅初始 token 鉴权（审计 #5）

核实属实。**未修复**：per-message challenge 需要移动端协议配合，单独改后端会断掉现有客户端。缓解措施见 P1/P2（配对码枚举被限流封死 = token 获取主路径被切断）；列入后续项。

### P1（防御深度）— 已修复

- **DELETE 越权**（审计 #6）：`_delete_persisted_memory` 的 DELETE 强制附带生效三元组 WHERE；`forget()`/`get_memory()` 增加归属校验（不属于当前作用域视同不存在/拒删）。
- **配对码暴力枚举**（审计 #8）：`confirm_pairing` 增加每 IP 滑窗限流（5 分钟 5 次，超限 429）。
- **INSERT OR REPLACE 跨作用域覆盖**（审计 #7）：`_load_from_db` 计数器改为跨作用域取全局最大 `mem_` 序号，新作用域实例不再复用已存在的 id。
- **配对码 CSPRNG**（审计 #18）：`random.randint` → `secrets.randbelow`。

### P2 — 部分修复

- **三层复合索引**（审计 #11）：`_init_persistence_db` 新增 `idx_mem_3tier(agent_id, neuser_id, user_id)`。
- **WS 无连接上限**（审计 #12）：`MobileConnectionManager` 增加单用户上限（`MAX_CONNECTIONS_PER_USER=5`），超限拒绝握手（close 4008）。

### 核实属实但未修复（架构级，需设计决策/跨端配合）

| # | 审计编号 | 说明 |
|---|---|---|
| 1 | #10 渠道 agent_id 硬编码 | 加路由表是功能设计，非缺陷修补 |
| 2 | #14/#16 RBAC 形同摆设 | `RBACManager.has_permission` 全局零调用，权限走 JWT role if-else。激活需统一权限模型 |
| 3 | #13/#15 双用户模型、插件无租户 | UserModel/EnhancedUserModel 并存；PluginRegistry 无租户概念。统一是 1 周+ 的架构工作 |
| 4 | #5 WS 无再认证 | 见 P0-4 说明，需移动端协议配合 |
| 5 | #17 JWT secret 自动生成无告警 | 加日志/启动警告属运维策略 |
| 6 | #9 from_legacy 历史污染 | 已有 Bug 20 注释与修复，存量数据需数据迁移评估 |

### 核实中新发现（审计未覆盖）

- `api/endpoints/session_sync.py` 全部端点**无认证**，user_id 由客户端任意指定；
- `GET /chat/history` 按 agent 归属校验，但不校验 session 归属（同 agent 下可读他人会话）。

这两项建议列入下一轮审计修复。

---

## 二、行为变化说明（重要）

1. **登录用户的记忆作用域**：修复前所有用户实际共享构造时的 default 作用域；修复后持 JWT 的请求按 `(agent_id, sub, sub)` 隔离。**存量记忆（default 作用域）对登录用户不可见**——未认证路径（`get_current_user_or_default` 回退 default）仍可见。如需迁移存量数据，将 `memories` 表 default 行 UPDATE 为目标用户三元组即可。
2. **mobile WS `session:list` 契约变更**：返回摘要列表（原为完整会话含全部消息）且按用户过滤；`_handle_session_list/_create` 签名增加 `user_id` 参数。`test_mobile_pairing_p0.py` 中 4 个旧契约测试已同步更新为新契约。
3. 未认证/内部管线（chat pipeline、默认 agent）行为完全不变（作用域缺省回退构造参数）。

---

## 三、回归基线比对

| 套件 | 结果 | 基线比对 |
|---|---|---|
| 新增 3 个测试文件 | 23 passed | — |
| tests/unit/api | 105 failed / 486 passed | 105F 与预存基线一致，全部位于未触碰模块（communication_protocol/skill/semantic_search 等） |
| tests/unit/memory + cognitive_layers 等 | 1202 passed / 3 failed | 3 个失败在 HEAD 基线 worktree 复现，预存 |
| tests/unit/test_console_round_ops 等 session 套件 | 43 passed | — |
| tests/test_channels | 预存漂移失败 | `SessionManager(enable_persistence=...)`、`has_attachments` 等 API 漂移，与本次无关 |
| tests/test_api/test_memory_route_shadowing.py | passed | 路由遮蔽回归网完好 |

修复涉及文件：`neurova/cognitive_layers/memory_layer/manager.py`、`neurova/api/deps.py`、`neurova/api/auth.py`、`neurova/api/endpoints/auth.py`、`neurova/api/endpoints/memory/base.py`、`neurova/api/endpoints/mobile_pairing.py`、`tests/unit/api/test_mobile_pairing_p0.py`（契约更新）。

报告版本 v1.0 · 2026-08-30
