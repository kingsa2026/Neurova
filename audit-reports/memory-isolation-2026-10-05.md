# 内存域身份旁路与越权面取证（2026-10-05）

只读取证，未改任何生产代码。对应 `audit-reports/simplification-audit-2026-10-05.md` §6-1，
本篇把那条的一句话结论拆成可核实的清单，并修正其中两处数字。

参考的仓内文档：
`docs/01-architecture/audit/three-tier-isolation-audit.md`（2026-08-30 审计原表）
`docs/01-architecture/audit/three-tier-isolation-fixes.md`（同日修复报告，P1-6 归属校验）
`docs/01-architecture/02-memory-system.md`

---

## 一、结论

审计报告 §6-1 写的是"JWT 解析失败静默回落 default"。方向对，但**它不是当前最硬的口子**。
实测下来真正的现行缺陷是另外三条：

1. `PUT /api/v1/memory/{id}` **没有任何归属校验**，另一个登录用户和**完全无凭证的请求**
   都能改写他人记忆。现行、可复现。
2. `DELETE /api/v1/memory/{id}` 调 `manager.forget(..., agent_wide=True)`，
   把三层隔离的第 2、3 层显式关掉。无凭证请求可对同 agent 内任意记忆执行"遗忘"。现行。
3. `GET /api/v1/memory/{id}` 没有鉴权依赖，读的是 `MemoryManager._storage`；
   而该实例**全仓零写入方**，所以今天恒 404。跨用户读取面今天是潜伏的，
   但同一行代码已经把"记忆详情/编辑回显"这个功能本身打死（前端点详情必 404）。

三层隔离机制本身是好的：`manager.get_memory()` 与 `forget()` 都带 P1-6 归属校验，
对照组实测 bob 用自己的作用域读 alice 的记忆得到 `None`。
问题出在**端点绕开了这两个收口**：PUT 走了没有校验的 `update_memory()`，
DELETE 走了 `agent_wide=True`，GET 走了 `storage.get()`。

---

## 二、图证（隔离数据根 + 真端点 + 只植入假数据）

方法：`NEUROVA_DATA_DIR` 指到临时目录（不触碰真实 `data/`，也不与本机 9527 实例共享），
用 `create_access_token` 签 alice / bob 两枚真 token，经生产 HTTP 路径建记忆、发变更，
再用带归属校验的 `manager.get_memory()` 在 alice 作用域读回效果。探针即用即删。

```
[0] POST /api/v1/memory data keys=['memory_id','timestamp']
[1] alice 建记忆            -> 200 id=mem_000003 读回='ALICE-原内容'
[2] bob   PUT 同一 id        -> 200 读回='TAMPERED-by-bob'      ← 跨用户改写成功
[3] 匿名  PUT 同一 id        -> 200 读回='TAMPERED-by-anon'     ← 无凭证改写成功
[4] 匿名  DELETE 同一 id     -> 200（soft 遗忘，记录仍在）
[5] 对照：bob 作用域 get_memory 读 alice 的 id -> None           ← 校验路径确实生效
[6] 对照：alice 作用域读同一条                  -> 'ALICE-第二条'
```

同一请求里的两份身份（旁路 vs 依赖）：

```
[D] payload 声明 = ['exp','iat','jti','role','sub','type','username']   ← 无 neuser_id 的存量 token
[D] 依赖口径   user_id=carol  neuser_id=carol      （auth.py:_user_identity 的 `or sub` 回退）
[D] 旁路口径   user_id=carol  neuser_id=default    （base.py:56 的 `payload.get("neuser_id", "default")`）
```

---

## 三、逐条落点

### 1. PUT 无归属校验（现行，高危）

`neurova/api/endpoints/memory/crud.py:313-341` → `manager.update_memory(memory_id, **payload)`。
`manager.py:1806-1812` 只做 `self._memories.get(memory_id)`，**既不校验 agent，也不校验
neuser/user**。P1-6 当年只补了 `get_memory()`(`:1786`) 与 `forget()`(`:1883`)，
`update_memory` 从未纳入——同批的兄弟方法漏一个。
随后的回显 `manager.storage.get(memory_id)`(`:334`) 恒 None，所以端点回的是
`data: null, "更新成功"`：改成功了，但调用方看不到改后的内容。

### 2. DELETE 用 agent_wide=True 关掉两层（现行）

`crud.py:351-365` → `manager.forget(memory_id, agent_wide=True)`。
`agent_wide` 的设计口径是"管理页"（`manager.py:1884` 注释），端点却无条件传 True，
于是 P1-6 的校验对普通用户端点等于不存在。默认 `soft=True`，效果是把他人记忆
标成 `LifecycleStage.FORGOTTEN` 并落库——记忆从检索里消失，但 API 回执说"记忆已删除"。

### 3. GET 读了一个没人写的存储（现行故障 + 潜伏的读取面）

`crud.py:229-234` 的 `get_memory` 端点**没有任何鉴权依赖**（同文件其余 10 个端点都有
`Depends(get_current_user_or_default)`）。它读 `manager.storage.get(memory_id)`，
而 `MemoryManager._storage` 只在 `manager.py:311` 被构造、被 `storage` property 暴露，
全仓没有任何写入方（`grep "self\._storage\." manager.py` 零命中；
`StorageModule` 无构造点；`conversation_buffer.py:376` 写的是另一个对象——痕迹库）。
`MemoryStorage.get`(`storage.py:402-405`) 是按 id 取值的扁平字典，无作用域过滤。

后果两件事：这条"记忆详情"路由对任何人生效地返回 404（图证 [1] 建成功后 [2] 立即 404，
上一轮矩阵实测）；同时它把"按 id 匿名读任意租户记录"这条路挖好了——
只要那个存储哪天被写入，它就是跨用户读取。修法上这两件是同一个动作：**改走
`manager.get_memory()`**，既恢复功能，又让归属校验生效。

### 4. 身份双源，口径还会分叉（第 6 条）

`base.py:38-61` `_get_user_ids_from_token(req)` 手工剥 `Bearer` 前缀、直调
`verify_access_token`，与声明依赖 `_user_identity()`(`auth.py:517-531`) 是**同一问题的两份答案**：
存量 token（无 `neuser_id` 声明）下依赖给 `sub`、旁路给 `"default"`（图证 [D]）。
真实用户的记忆因此被贴错第二层键。调用点 **29 处**（crud 1 / metacognition 12 /
profile 4 / tkg 4 / working_memory 8）。
上一轮审计报告 §6-1 写的"35 处"是原文出现数（29 调用 + 5 导入 + 1 定义），本篇更正。

并且：这些端点已经从依赖里拿到了 `user`，却又用旁路重解析一遍覆盖它
（如 `profile.py:127` 起、`crud.py:240`），依赖给的身份被丢弃。

### 5. 静默吞异常（第 2 条）

`base.py:58-59` `except Exception: pass  # Token 解析失败时使用默认值`。
异常被吞后直接落 default 租户，没有任何日志面。
注意：这条**不是**"过期/伪造 token 混进 default"的入口——
`get_current_user_or_default` 早在 S-10 就改成"有凭证但无效 → 401"(`auth.py:541-556`)，
所以带坏 token 的请求进不到端点。旁路的真问题是第 4 条那个口径分叉，以及
**无凭证请求**（设计允许，桌面首启用）在这里再落一次 default。

### 6. 完全没有鉴权依赖的端点（现行）

按脚本枚举"用了旁路但签名里没有 `Depends(get_current_user*`"的落点：
`crud.py:230 get_memory`、`working_memory.py:94 get_wm_context`、
`metacognition.py` 的 12 个（`:93 meta_optimize`、`:120 meta_evolve_skills`、
`:152`、`:179`、`:211`、`:236`、`:261`、`:286`、`:316`、`:347`、`:373 meta_generate_skill`、`:400`）。
其中 `meta_optimize` / `meta_evolve_skills` / `meta_generate_skill` 是**变更类**操作。
全局鉴权中间件默认 `off`（`global_auth.py:63`，`NEUROVA_GLOBAL_AUTH` 三态），
所以这些路径今天确实匿名可达。

### 7. 顺带命中的两处（同文件同根因面）

- `base.py:33 resolve_user()` 零调用方（死码）。
- `profile.py:130/169` 与 `metacognition.py:329/412` 向 `get_memory_manager(agent_id, user)`
  传第三个位置参 → 必 TypeError，被外层 `except Exception` 折成 500（§6-6 已记，此处是命中点复算）。

---

## 四、修法建议（按第 1 条，根因处收口，不逐点补判空）

一个批次能同时关掉 1/2/3/4/5：

1. **删掉 `_get_user_ids_from_token` 整条旁路**，29 处调用点一律改用端点已从
   `Depends(get_current_user_or_default)` 拿到的 `user`；结构扫描实测 16 条路由无鉴权依赖
   （初稿"14"是一条不严谨正则的产物），其中走旁路的 13 条补上依赖，另 3 条不取租户数据。
   身份解析单源（第 6 条），分叉与静默吞异常一起消失。
2. **`manager.update_memory` 补归属校验**，与 `get_memory`/`forget` 同规则（P1-6 的补齐）。
3. **DELETE 端点不再传 `agent_wide=True`**；管理页口径若要保留，另开显式管理端点并加 role 门。
4. **GET 端点改走 `manager.get_memory()`**：功能恢复 + 校验生效 + 去掉匿名按 id 读的路子。
5. 无凭证回落 default 是**已知设计**（`three-tier-isolation-fixes.md:76` 明写"未认证路径仍可见"），
   本篇不判它违规，但要求它至少显式可观测（现在被 `pass` 吞了）。

红灯清单（先红后绿，逐条要贴失败原文）：

- bob 改 alice 记忆须失败；匿名改须失败。（现绿不成，会红在 200）
- bob 删 alice 记忆须失败；匿名删须失败。
- alice 自己 `GET /api/v1/memory/{id}` 须 200 且内容正确（现 404，红）。
- 同一请求内身份只有一个来源：无 `neuser_id` 声明的 token 下，作用域第二层须为 `sub`
  而非 `default`（现红，图证 [D]）。
- 存量 `tests/unit/api/test_memory_request_scope.py`（P1-6 那批 11 条）须仍全绿。

---

## 五、未覆盖与存疑

- 只测了 `crud.py` 的三条 by-id 路由与 metacognition 的依赖缺失面；
  `profile.py`/`tkg.py`/`working_memory.py` 的 29 个调用点未逐个跑效果，只做了静态与计数取证。
- 记忆实际落库的作用域键（`mem_` 行的 neuser/user 值）未从 SQLite 层直接读出核对。
- `global_auth` 切 `enforce` 后这些路径全部 401（上一批已实测），
  即：**本缺陷的实际暴露前提是默认 off**。是否把 memory 前缀纳入 enforce
  属产品/运维决策，未在本篇裁定。
- 探针跑在隔离数据根，未与用户正在运行的 9527 实例交互。

---

## 六、落地情况（第四节那一批已实施，commit `63e8ae8e`）

修法五项全部落地，生产净 **−64**：旁路 `_get_user_ids_from_token` 与死码 `resolve_user`
删除，29 处调用点改为端点既有的 `user`（`profile.py` 两处三位置参 TypeError 同批消失），
13 个缺依赖端点补上 `Depends(get_current_user_or_default)`，`update_memory` 补归属校验，
GET/PUT 读回改走 `manager.get_memory`，DELETE 不再传 `agent_wide=True`。

实施中新发现并登记两条（不在原清单）：

1. **`request.state.user` 全仓无人写入** —— `memory_enhancement.py:110` 的
   `_require_memory_manager` 正是从它取身份，于是该模块的作用域恒回落 default，
   它的 get/forget 一直是 agent-wide 口径。本批只把 4 处 `update_memory` 显式写成
   `agent_wide=True` 与既有口径对齐（不是放宽，是把事实写成事实源），
   真正的修法是给这些端点接上依赖——**留待下一批**。
2. **依赖参数名两套并存** —— 同包内 crud/metacognition/eki/emotion/pending/questions/
   visibility 用 `user`，tkg/profile/working_memory 用 `current_user`。统一成 `user`
   （包内多数）；改名前的第一次试跑就在 16 处踩出 `NameError: name 'user' is not defined`
   ——这个坑本身就是"同一个概念两个名字"的代价。

守卫改判一处（需要用户复核）：`tests/unit/api/test_memory_api_agent_wide.py` 原先把
"列表/统计/高温/固化/删除都透传 agent_wide=True"钉成契约，其理由是**可见性**
（登录用户 scope 不该把他人记忆从管理页抹掉）。删除不属于可见性理由能覆盖的范围，
故本批把读侧保持 agent-wide、删侧收回归属校验，并把该守卫改为
`test_delete_does_not_pass_agent_wide`。若产品确实要"管理页可跨用户删除"，
正确形态是另开带 role 门的显式端点。

复验口径：`tests/unit/api`+`tests/unit/cognitive_layers`+`tests/cognitive_layers`+
`tests/test_memory` 27 失败 ↔ 27 失败逐行一致；`tests/integration`+`tests/api`
新增失败 0（唯一差集是 `test_outbox_expired_event` 预存抖动反向翻转）；
内存相关单测 + 新集成用例 94 passed。活体矩阵（隔离数据根 + 真 create_app）：

```
[2] alice 本人 GET -> 200 content='ALICE-原内容'     （修复前：404）
[3] bob 跨用户 GET -> 404   [4] 匿名 GET -> 404
[5] bob PUT -> 404          [6] 匿名 PUT -> 404      （修复前：均 200 且内容真被改）
[7] alice 复读 content='ALICE-原内容'                （未被篡改）
[8] bob DELETE -> 404       [9] 匿名 DELETE -> 404   （修复前：均 200）
[11] alice 自己 PUT -> 200 data='ALICE-自己改的'      （修复前回显恒 null）
```

---

## 七、同根因第二命中点：外部 Agent 通信域（已扫荡，commit `806c6f38`）

教义第 5 条要求点名一条断链后扫同契约的全部落点。本域原登记的说法是
"`agent_communication_api.py` Bearer 解析异常被 `pass` 吞掉后一路落到 default 放行"——
**可达性说重了，此处更正**：该 router 有路由级 `APIRouter(dependencies=[Depends(get_current_user)])`，
实测无凭证与无效 token 都先被拦成 401。真正现行的是另一条同契约分叉：

- `HTTPBearer` 对 scheme 大小写不敏感，`bearer <jwt>` 能过门；
- 端点级第二份解析写 `authorization.startswith("Bearer ")`，认不下小写 → 落到
  `{"user_id": "default"}`；
- `auth["user_id"]` 是本域 api-keys / handshakes / external agents / messages 的**分区键**。

活体证据（隔离数据根 + 真 create_app）：小写 `bearer` 签发的密钥在正常 `Bearer` 列表里
不可见；单源化后同一探针两把密钥归到同一租户（`names=['k-a','k-b']`）。

处置：删掉端点级 `_verify_api_key_or_token`，10 个端点复用路由级那道门的解析结果
（FastAPI 按请求缓存，一处解析两处共享）；同批退役**不可达**的 api-key 认证分支
（门先拦 401，且 `X-API-Key` 在本域零消费者——NeurUI 那处是 provider 出网配置、
`channels/websocket.py` 是渠道自有鉴权头）与无人读取的 `auth_type` 字段。生产净 −23，
A/B `tests/unit/api`+`tests/integration` 失败集合 137↔137 逐行一致。

**留待产品裁的一条能力缺口**：`nk_` 密钥仍被签发/列举/吊销，但**不是可登录凭证**。
若要外部 Agent 拿密钥登录，正确做法是改路由级那道门（"JWT 或 密钥"合一），
而不是在本域再开第二条解析路径。本批把这一点写进模块 docstring，
不再让"JWT Token或API Key"悬空承诺。
