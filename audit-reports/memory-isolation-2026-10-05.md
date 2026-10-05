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

> 该缺口已于同日按用户拍板闭合，见下面 §八。

---

## 八、凭证合一与密钥真相源收口（教义第 7 条流程记录，commit `c1c6c221`）

用户拍板：门改为 JWT 与密钥合一，真相源 = `APIKeyManager`。第 7 条要求"先比后合"，
按固定顺序留证。

**① 对比优劣**（仓内当时有三处承担"签发一枚可撤销 API 密钥"）：

- `agent_communication_api._api_keys` —— 进程内存字典；无验证消费方（那条分支被路由级
  门先拦）；字段是 `APIKeyManager` 的子集（`revoked` ≡ `not is_active`）；
  不可替代之处：**无**；重启即全体失效。
- `api_key_manager.APIKeyManager` —— JSON 落盘（`callerPath` 走数据根）、DCL + RLock
  单例、`atexit` flush、S-19 防抖落盘且有回归测试；方法面完整
  （generate/validate/get_user_keys/get_agent_keys/update/revoke/delete）。
- `openplatform_keys.py` —— 独立 JSON 落盘、原子写（temp + `os.replace`）、
  创建幂等（`creation_request_id` + 意图指纹）、撤销 tombstone 防同请求重放复活。

**② 取长补短**：`(1)` 并入 `(2)`——它没有 `(2)` 缺的能力，故不搬任何东西。
`(3)` **当时不动**：它带着 `(2)` 没有的三项能力（原子写 / 创建幂等 / 撤销 tombstone），
按第 7 条"不许不比较就删掉弱者"，它不是弱者；要三合一必须先把这三项补进选定的那份。
此前提当日登记在此。**该前提已在同日下班前完成——三项机制并入 `(2)`、`(3)` 的私有存储
退役，见 §九（commit `94af885f`）。**

**③ 接通**：门 `get_current_user_or_api_key`（`auth.py`，与
`get_current_user_or_service` 同族同规则：先 JWT，其次 `validate_key`，两者都不成立才
401，**不回落 default**）；本域 15 处端点与路由级门全改指它；api-keys 的签发/列表/更新/
撤销/删除与 `/routing/stats` 的密钥计数都改读真相源。

**④ 退役清理**：删 `_api_keys` / `_generate_api_key` / `_hash_api_key` 与随之无用的
`hashlib` 导入；docstring 不再声称"密钥目前不是可登录凭证"。

行为变化两条，都写进了代码注释：

- 密钥串不再有 `nk_` 前缀（管理器用 `secrets.token_urlsafe(36)`，key_id 前缀 `ak_`）；
  前端只按字段展示，不依赖前缀（grep `nk_` 于 NeurUI 零命中）。
- 未显式传 `expires_in_days` 的密钥按管理器的 `default_expiry_days=365` 过期，
  而旧内存表是"永不过期"。这是选定那份的既有策略，不是本批新加的约束。

证据：红灯 5 条（合一门不存在、`X-API-Key` 401、撤销后仍可用、单例重建后失效、
内存表仍在）；域内测试 27 passed；变异复验——把 `/routing/stats` 的读侧改回旧表即
`NameError` 让守卫变红（这条守卫正是我第一版漏改该处之后补的）；活体链路：

```
[1] JWT 签发 -> key_id=ak_faa72... expires_at=1822755742（365 天默认）
[2] 只用密钥握手 -> 200        [3] 只用密钥发消息 -> 200
    from_agent_id=['ext-agent-7'] user_id=['alice']   ← 密钥绑定的 agent 真正进入隔离键
[4] 只用密钥读路由统计 -> 200 api_keys=1               ← 读写同源
[5] api_keys.json 落盘 True   [6] 单例重建后同密钥仍 200（等价重启不失效）
[7] JWT 撤销 -> 200           [8] 撤销后用该密钥 -> 401 "Invalid, revoked or expired API key"
[9] 盘上状态 -> [{'id':'ak_faa72','is_active': False}]
```

A/B（stash 集 = 本批全部改动面）：`tests/unit/api` + `tests/integration`
122 failed / 2486 passed ↔ 同数，失败集合逐行一致。生产净 +34（复用既有管理器，
而非再造一份；去向见提交说明）。

---

## 九、身份批的续三件（同日完成，含密钥实现三合一）

| commit | 内容 | 现行缺陷面 |
|---|---|---|
| `cf684596` | `firewall.update_global_rules` / `update_user_rules` 未知键先验后写、点名拒绝；配置装载遇未知键改 WARNING 留痕；合法键名单源取 dataclass 字段 | §八末尾那条 |
| `7842ecb9` | 开放平台密钥归属改取路由级门的返回值——`request.state.user_id` **全仓无人写入**，导致所有用户的密钥同落 `anonymous` 桶：互相可见、按他人 key_id 即可撤销 | 与 `get_memory_manager` 身份旁落同根因 |
| `94af885f` | 开放平台私有密钥存储并入 `APIKeyManager`：原子写、创建幂等 + 意图指纹、撤销 tombstone 三项机制并入选定实现，七端点改指它，私有存储与三份辅助函数退役 | §八"三合一前提"闭环 |
| `04c4a42e` | 记忆增强端点身份改取路由级门的返回值，7 处变更调用收回归属校验，既有测试伪造 `request.state.user` 的中间件同批去除 | 本域同根因第三命中点（详见 §十） |

三处判据值得留字：

1. **兼容不是假设，是测出来的。** 并入后装载旧部署的扁平 `{key_id: {...}}` 时，
   老记录没有必填的 `agent_id` → 构造 TypeError → 被整段 `try` 吞成"零把密钥 +
   一行 ERROR"。这条先红（`扁平存量文件里的密钥被读丢了`），修法是补占位 +
   **逐条容错**：一条坏记录不得把整库读丢。
2. **合并顺手收紧了两处对外面**：响应不再直出 `key_hash`（旧实现整条记录原样吐），
   `key_prefix` 展示统一为管理器口径。都各有一条钉。
3. **`nrv_` 仍不是可登录凭证**——它现在与 agent 域共用同一份实现，接进门只是换个实例
   加一道门的事，但"哪些端点接受开放平台密钥"是产品口径，仍挂起（台账原话）。

未随批收紧、留档的一条同族：`memory_enhancement.py:110` 仍取
`getattr(request.state, "user", None)`（同样无人写入），故该模块作用域恒 default、
其 get/forget 一直是 agent-wide 口径。把身份接上去会让这些端点立刻开始拒绝跨用户操作，
属功能语义变更，需单独判定后再改（改法与 §九第 2 行同型）。
**→ 已于同日落地，见 §十（commit `04c4a42e`）；本段留作当时的判断记录。**

复验口径：开放平台两套 + 外部 Agent 两套 + 管理器 S-19 防抖回归 **37 passed**；
真 app 活体九步全绿（`nrv_` 前缀、幂等重放不再吐明文、两条账各自独立、
撤销后列表归零、同请求重放 409）；A/B `tests/unit/api`+`tests/integration`
122→123，唯一差集是 `test_media_frontend_contract` 那条预存顺序耦合 flake（单跑两次均绿）。

---

## 十、同根因第三命中点收口：记忆增强端点（commit `04c4a42e`）

§九 末段留档的那条"同族未收紧"已在本批落地，同根因链至此三命中点全部闭环
（`memory/` 域 → `agent_communication_api.py` → `openplatform_keys.py` → `memory_enhancement.py`）。

**现行面（复算过，不是引用旧行号）**：`_require_memory_manager()` 读
`getattr(request.state, "user", None)`，而该字段全仓无写入方——本批现复算
`grep -rn 'state.user' neurova/` 除本模块 docstring 外零命中、
`grep -rn 'state.user =' neurova/` 零命中。作用域因此恒回落 default，六条端点的
**变更**调用又全部显式带 `agent_wide=True`（把三层隔离的第 2、3 层关掉），于是任何
登录用户按 memory_id 都能软删/硬删/改写他人记忆。

**它为什么长期不现形**：既有 `tests/unit/api/test_memory_enhancement_real_manager.py`
的 fixture 挂了 `@app.middleware("http")` 自己往 `request.state.user` 塞值。
测试替生产把那个没人写的字段补上，绿灯因此自证的是"伪造身份下的行为"。
本批删除该伪造，并在守卫里钉住它不得复活（`test_existingFixtureForgeryIsGone`）。
这是教义第 3 条"禁止绕过生产装配点"的一个具体形态：**伪造身份字段 = 绕过身份来源**。

**改法与判据**（与 §六、§九第 2 行同型，不新造口径）：

| 面 | 处置 |
|---|---|
| 身份 | 改取路由级 `Depends(get_current_user)` 的返回值；六条端点各补该依赖参数 |
| 变更（7 处） | forget 软删 ×2、forget 硬删 ×1、update_memory ×4（strengthen / batch / import-merge / import-overwrite）收回归属校验 |
| 读（3 处） | 存在性预检 `get_memory`、`get_stats`、`get_memories` 保持 agent-wide |
| 取不到 manager | 仍显式 503，不回落任何进程内副本 |

读侧保留 agent-wide 的理由与 §六 那条"可见性不外溢成处置权"完全一致，未放宽也未收紧。

**证据**：红灯 4 条（生产文件单独 stash、只留新测试，`4 failed, 2 passed`；
第 5 条红对着未改的既有测试文件跑出）→ 绿灯两文件 13 passed，连同 memory 域三条守卫共 33 passed。
活体走的是真 uvicorn + 真 `create_app` + 真 JWT + 隔离 `NEUROVA_DATA_DIR`：
修复前 bob 跨用户 forget 返回 200 且 alice 复读 `stage=forgotten`（记忆真被他人销毁）、
批量返回 "Processed 1 memories, 0 errors"；修复后 404 / 401 / 批量 0 条，
alice 本人 strengthen 与 forget 仍 200 且落库可见。
A/B：`tests/unit/api` 15 failed ↔ 15 failed 逐行一致（passed 2036→2042 即本批 6 条守卫），
`tests/integration` ERROR 集 15↔15 一致，FAILED 唯一差集为预存墙钟抖动
`test_outbox_expired_event`（单跑 1 passed）。新增失败 0。
守卫已入 `scripts/ci/protected_tests.txt`（转绿后方入，逐文件单跑 6 passed）。

**两点判据值得留字**：

1. **路由级门已存在 ≠ 端点拿得到身份**。`APIRouter(dependencies=[Depends(get_current_user)])`
   只执行不返回，端点若要身份必须自己声明同名依赖（FastAPI 每请求缓存依赖结果，
   不会双跑）。前两批的归属旁落都是栽在"门在、值没接过来"，而不是"没有门"。
2. **反证守卫要钉代码形态，不钉词**。本模块与测试的注释里都会写出那个字段名
   （为了说明它为什么不能用），`assert "state.user" not in src` 会自己把自己钉红；
   改钉 `getattr(request.state, "user"` 与 `request.state.user =` 两种代码形态后
   才既咬得住复活、又不被 prose 触发。

**同批未做、留档**：本批只把本守卫入 CI 子集；§六/§七/§八/§九 落地的
`test_memory_update_ownership.py`、`test_memory_route_authorization.py`、
`test_agent_communication_identity.py`、`test_openplatform_key_ownership.py`
仍在子集外（都逐文件单跑全绿）。是否整批收编属 CI 时长口径，未擅自扩大。
