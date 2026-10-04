# T-20 施工单 · `model_adapter/` 整块退役（前后端同批收口）

> 立项：2026-10-02 · 依据：工单集 §43.4 登记 + §44 清账表 · 归类：施工工单
> 裁决口径：**退役，不接线**；接线账单算完后其终态与退役同一（见 §1.3）。
> 本文是执行源，不是分析报告——每步都带判据、守卫对账与回退点。

---

## 0. 前置事实（全部实测，逐条可复跑）

| 事实 | 落点 |
|---|---|
| 整块 1209 行 / 4 文件 | `neurova/cognitive_layers/model_adapter/{__init__,base,builtin,registry}.py`（`wc -l` 36/271/641/261） |
| 五家厂商适配器**一调即炸** | 10 处转发行全带 `model=self.model_name`，而 `registry.py:251` 形参是 `model_name` ⇒ `TypeError: got multiple values for keyword argument 'model'` |
| 兜底适配器也炸 | `registry.py:64` 造 `LLMClient(config)` 后调 `client.generate(...)`，`LLMClient` 无此方法 ⇒ `AttributeError` |
| `litellm` 名存实亡 | 函数名仍叫 `_generate_with_litellm`，实现改走 `LLMClient`；`litellm` 在 `pyproject` 命中 0、本机 `find_spec=False` |
| 生产调用方为零 | `agent_core.py:906/907/911` 只有 import + 赋值；全仓无一处读 `agent.model_adapter` 跑方法 |
| 9 个能力字段里 4 个已有主 | `ProviderCompat.supports_tools:71 / supports_tool_choice:74`；`CAP_SUPPORTS_MULTIMODAL` 写侧 `provider_manager.py:1796` 读侧 `capability_state.py:258`；限额 `llm/capability_detector.py:252 apply_preset_defaults` + `llm_client.py:231 clamp_max_tokens` |
| 其余字段无读侧 | `supports_streaming`/`supports_json_mode`/`supports_parallel_function_calls` 只出现在**离线探测栈** `providers/capability_detector.py`，生产禁 import（守卫 `tests/unit/llm/test_capability_cache_single_source.py:47 FORBIDDEN_IN_PRODUCTION`） |
| 12 条族前缀不携带新事实 | 现役 `llm/capability_detector.py:120-126` 已有 `kimi-k2 / kimi-latest / kimi-vl / moonshot-v1-8k/32k/128k`，`:179/:186` 有 `hunyuan-image / hunyuan-video`，且带真实限额；适配器只有"整厂一族" |
| 两份"有哪些适配器"事实源 | 注册表 `list_adapters()`（15 条，同名成对=每类多模式注册，**非缺陷**）vs 端点内硬编码 `_ADAPTERS`（`api/endpoints/model_adapter.py`，105 行） |
| 前端有壳无消费 | `NeurUI/src/api/modules/model-adapter.ts`（48 行）+ `index.ts:31` barrel + `__tests__/api-modules.test.ts:139/144` 两条 vitest；**无任何 `.vue` 引用** ⇒ 零 locale 改动。<br>注：`grep` 命中的 `NeurUI/src/.mimosa/hook-state/**` 是工具会话快照，不作事实源 |
| 受影响的在册守卫 | `scripts/ci/protected_tests.txt` 收有：`test_audit_regressions.py`(第 4 行)、`test_agent_core_size_ratchet.py`(14)、`test_api_inventory_freshness_guard.py`(431)、`test_api_inventory_guard.py`(432) |
| API 台账是生成物 | `docs/09-dev-progress/api_inventory.md` 唯一写者 `scripts/generate_api_inventory.py`，判据单源在生成器内（`mountedRouterAudit`） |
| 台账守卫族**改前就红** | 2026-10-02 全量读数：`test_api_inventory_freshness_guard` 4 failed、`test_api_inventory_guard` 1 failed（预存红，非本单引入） |

---

## 1. 裁决边界

### 1.1 退役什么
`neurova/cognitive_layers/model_adapter/` 四件、`api/endpoints/model_adapter.py`、
`api/endpoints/__init__.py:276` 的挂载表行、`agent_core.py:906/907/911` 三行、
`test_audit_regressions.py` 的 `TestToolCallDefaultId` + `TestModelAdapterRegistry` 两类、
前端 `model-adapter.ts` + barrel 行 + 两条 vitest。

### 1.2 不搬任何东西
§0 已核：能力字段全部有主或无读侧，族前缀现役更细。**若将来真要逐模型声明
`json_mode` / 并行工具调用，来源只能是探测或回执学习**——§42 刚立过这个形状
（A2 实测：同厂商 10 个模型只有 1 个钉死、5 个不钉，任何按厂商手写的表都会写错）。

### 1.3 为什么"接线"的终态等于退役
接线的 8 项必修（kwarg 撞车、缺方法、凭据源、能力表双源、prompt 形状、工具解析形状不同、
第四份名单、前端三处）修完后，这块不再拥有能力表、transport、prompt 形状、工具解析，
端点名单改为派生——剩下的唯一实体是那 12 条正则，而它们没有新事实（§0）。
所以接线 = 用 8 项同批修复去买一个空壳。

---

## 2. 施工顺序（每步给判据与回退点）

**S0 · 先写反向守卫并实证它红**（教义第 3 条：删除类改动也要先红后绿）
新判据 `tests/unit/llm/test_no_parallel_vendor_capability_surface.py`，四条否定式断言：
① `neurova/cognitive_layers/model_adapter/` 目录不存在；
② 挂载表不含 `/v1/model-adapter`（按 `api/endpoints/__init__.py` 的表逐行读，不按文档）；
③ 生产源码里 `AdapterCapabilities` / `BaseModelAdapter` 命中数为 0；
④ 现役族表能答出适配器答得出的东西——**本行读数已实测**（2026-10-02 本机）：
`infer_capabilities()` 给
`kimi-k2 → ['text','tool_use']`、`moonshot-v1-128k → ['text','tool_use']`、
`hunyuan-image → ['image_generation']`、`deepseek-chat → ['text','tool_use']`、
`glm-5 → ['text','reasoning','tool_use']`、`claude-sonnet-4 → ['text','vision','tool_use']`，
六族全部落到具体能力而非兜底 `['text']`。
（**这条防"退役把能力面删薄了"**——判据断言的是替代源真的更宽，不是断言"删了没事"。）
预期：①②③ 三条红、④ 绿（④ 已预验为绿，落进判据是防它将来被改坏）。回退点：本步只加文件，删之即回。

**S1 · 取台账预存红的失败名集合**
`-m pytest tests/unit/test_api_inventory_freshness_guard.py tests/unit/test_api_inventory_guard.py -q -rf`
存下逐条失败名。**停手条件**：若这批的红名在 S2 之后不减反增，必须先解释清楚再继续。

**S2 · 重生成 API 台账**（严禁手改生成物）
`.venv/Scripts/python.exe scripts/generate_api_inventory.py`，然后 S1 那两个守卫复跑，
按**失败名集合**比：路由退役应让"表与注册表差集"类红名减少或不变，不该新增。

**S3 · 删后端四件 + 三行赋值**
`git rm -r neurova/cognitive_layers/model_adapter`，删 `agent_core.py:906/907/911`。
同批：`agent_core.py` 尺寸棘轮基线按其自带机制更新（`test_agent_core_size_ratchet.py` 读 BASELINE 文件、
history 追加、指标只降不升）——不更新就当场红，红是对的，别绕。

**S4 · 删端点与挂载行**
`git rm neurova/api/endpoints/model_adapter.py`，删 `api/endpoints/__init__.py:276` 那一行。
执行前先核实挂载**只由该表驱动**：`grep -rn "model_adapter" neurova/api/ neurova/main.py app.py`，
若另有 `include_router` 直挂点，同批删；不同批就留下断点（教义第 5 条）。

**S5 · 切测试的两类，文件留在 CI 清单**
`test_audit_regressions.py` 只删 `TestToolCallDefaultId`(13-38) 与
`TestModelAdapterRegistry`(39-69)，其余类保留（它还钉着别的审计回归）。
判据：该文件逐文件单跑必须仍全绿——它在 `protected_tests.txt:4`，红了就等于把在册守卫做坏。

**S6 · 前端三处同批**
删 `model-adapter.ts`、`index.ts:31` 的 barrel 导出行、`api-modules.test.ts` 里
`describe('model-adapter API')` 整块。验证：`npm run test`（基线 211 passed / 5 failed 预存，按名对账）
+ `npx vue-tsc --noEmit`。

**S7 · 文档分类处理**（改什么、不改什么，都写明理由）
改（声明"现状目录树"的结构性文档）：`docs/01-architecture/07-implementation-plan.md:36`、
`docs/01-architecture/08-project-structure.md:49` 与 `:210`、`docs/CONTEXT.md:124`。
**不改**（带日期的历史快照，改写等于篡改留痕）：`docs/02-api/API_REFERENCE.md`（自述"最后更新 2026-06-07 /
端点模块 75 个"）、`docs/02-api/api_architecture_analysis.md`（自述"生成时间 2026-06-06"）、
`docs/s08_route_auth_baseline_2026-09-11.txt`、`docs/05-reports/code-audit-report-2026-08-28.md`、
`docs/深度Bug扫描报告_2026-09-11.md`、`docs/11-legacy/*`、`docs/*.html` 图谱、
`docs/空数据页面与保存落盘排查_2026-09-12.md`（那条"model-adapter 静态目录·无消费者"的登记正是本单的入口，保留）。

**S8 · S0 判据转绿并登记进 CI**
`git add` 新判据 → 追加 `scripts/ci/protected_tests.txt` → 同批跑登记三道守卫
（跟踪态守卫 / `test_clock_caliber_ledger` / `test_ci_wallclock_assertion_ledger`；
本判据不含计时符号，预期第二道只需确认不红，读数照写）。

**S9 · 全量归因 + live-verify**（不以单测全绿替代，教义第 4 条）
① `tests/unit` 分块跑，按**失败名集合**与 S0 前基线逐名比对，差集必须为空或逐条给出理由；
② 真后端（:9527，凭据由人当场给、不落盘）起来后：
   `GET /api/v1/model-adapter` 应回 **404**（路由确实没了，而不是 200 空壳）；
   主聊天链路跑**一轮真调用**（含一次工具轮）确认退役没碰坏装配面；
   抽一个 kimi/moonshot 系模型看 `detect_model_capabilities` 在 UI 侧仍给出具体能力；
③ 净 LOC 用 difflib 对 `git show HEAD:` 逐文件三分实测，写进提交说明。

---

## 3. 落账清单（执行时逐条勾）

- [x] S0 判据新增，改前 3 红 1 绿的读数原文留存（3 failed + 6 passed；§44.1）
- [x] S1 台账预存红名单留存（实测为 ∅：工单立项时的 5 条预存红已被 c84d9fda 根修；§44.1）
- [x] `neurova/cognitive_layers/model_adapter/` 四件已 `git rm`
- [x] `agent_core.py` 三行赋值已删（装配段整块 −13 行）；尺寸棘轮基线已按其机制更新并复跑（17 passed）
- [x] `api/endpoints/model_adapter.py` 已 `git rm`；挂载表行已删；直挂点核查读数=仅表驱动
- [x] `test_audit_regressions.py` 两类已删、文件仍逐文件全绿（15 passed）、仍在 `protected_tests.txt:4`
- [x] 前端 `model-adapter.ts` / barrel 行 / vitest 块三处已删；`npm run test` 与 `vue-tsc` 对基线（失败 2 条 A/B 实证预存；vue-tsc 零报错）
- [x] `docs/09-dev-progress/api_inventory.md` 由生成器重生成（删除后 `--write`，−4/+2），未手改
- [x] 结构性文档 4 处已改；7 份日期快照未动（列名留证）
- [x] `protected_tests.txt` 已登记 S0 判据；登记三道守卫合跑读数原文留存（57 passed）
- [x] `tests/unit` 失败名集合差为空（T-20 引入的 3 类红全部闭环后与 HEAD 态逐名相同；skills/computer_use 未跑完的理由见 §44.2）
- [ ] 活体三条读数留存（404 / 主链路一轮 / 族推断仍具体）——**2/3**：404 三条与族推断读数已留 §44.3；主链路真调用待凭据由人当场给
- [x] 工单集 §44 记裁决与执行结果；本单净 LOC 逐条去向写进提交说明
- [x] 探针与还原备份活到提交之后才删（记忆 feedback-keep-restore-backups-until-commit）

## 4. 停手条件

| 现象 | 动作 |
|---|---|
| S0 判据 ④（替代源更宽）在改前就红 | 停 —— 说明现役族表其实**覆盖不到**某族，此时"退役"会真丢东西，改判为"搬该族再退役" |
| S2 之后台账守卫失败名集合新增 | 停，先解释每一条，不许"顺手把守卫改松" |
| `agent_core` 棘轮要求升基线（变大） | 停 —— 删除不该变大，说明删错了方向 |
| 任一 `.vue` 或 store 实际引用 `modelAdapter` | 停，前端面比 §0 读到的大，重估 |
| 全量差集非空且无法逐条归因 | 不提交，回报待拍 |

## 5. 预期量（落笔即声明为"未实测的目标值"）

删除面实测在案：1209（后端块）+ 105（端点）+ 48（前端 module）+ 约 57（测试两类）+ 约 12（barrel/vitest 行）
≈ **−1400 行**；新增面：S0 判据一个文件（测试，不计入生产 LOC）。
生产净 LOC 预期为负——为正时按教义第 2 条逐条列去向。实际数字以 S9③ 的 difflib 三分实测为准，
本节的估算**不作为已测读数引用**。
