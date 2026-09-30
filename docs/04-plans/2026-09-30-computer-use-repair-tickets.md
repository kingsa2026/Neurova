# 电脑操控（Computer Use）面修正工单集

> 立项时间：2026-09-30 · 取证基线：`008a3e2a` · 归类：施工工单（非研究参考）
> 上游取证：对标文档 [`../08-research/zcode_vs_neurova_tool_loop_comparison_2026-09-26.md`](../08-research/zcode_vs_neurova_tool_loop_comparison_2026-09-26.md)
> 关联工单集：G1 [`2026-09-26-tool-loop-iteration-repair-plan.md`](2026-09-26-tool-loop-iteration-repair-plan.md)、
> G3 [`2026-09-26-tool-batch-parallelism-repair-plan.md`](2026-09-26-tool-batch-parallelism-repair-plan.md)、
> G4 [`2026-09-26-tool-cancellation-repair-plan.md`](2026-09-26-tool-cancellation-repair-plan.md)
> 本文所有"对照侧"断言只作**该能力可实现**的证据，**不作设计标准**；按 `AGENTS.md` 原创性条款独立设计。

---

## 0. 给执行者（NPC）的硬约定

开工前按顺序读：`AGENTS.md`（修复教义 1–6 + 协作红线）→ 本文件 → 所指源码。

1. **一条工单一个 commit**，单任务单 commit；`git commit --only -- <显式路径>`，**严禁 `git add -A`**（工作树常含他人在途改动）。
2. **先红后绿**：每条工单第 1 个 commit 只交红灯，并附"它真的红"的 pytest 输出原文；绿灯实现随后。红灯文件**在转绿前不得进** `scripts/ci/protected_tests.txt`。
3. **跑测试必须用项目解释器**：`.venv/Scripts/python.exe -m pytest`（Windows）。用全局 python、或设 `PYTHONIOENCODING=utf-8`，都会**伪造出一大片假红**（后者会打掉子进程 stdout）。
4. **不要跑全量 pytest**：会被两个用例打死进程。按目录分块跑取摘要，且必须 deselect 开浏览器的那个 `start_script` 用例。
5. **docs 守卫族在基线上本来就红**（`test_docs_name_collision_guard` / `test_legacy_ref_ledger_guard` / `test_docs_index_hand_copied_counts` 等，基线 `da843611` 实测 8 failed / 8 errors）。**比的是失败名集合，不是总数**——别把预存红算成自己引入的。
6. **教义第 5 条放大视角**：每条工单都列了「同根因扫荡」，命中点必须一并处理或**显式登记进台账**，不许静默遗留。
7. **净新增 LOC 默认 ≤ 0**。为正在本集各工单的 LOC 表里逐条列了去向；若你的实现超出，须在 commit 正文说明差在哪。测试代码不计入。
8. **禁止写法**（教义第 3 条点名项，本域尤易踩）：不得用 `MagicMock` 冒充 `BrowserResult`/UIA 元素对象；不得恒真断言；不得手工把 `generation`/`agent_id` 传进去绕过生产装配点——**判据必须从装配点起**。
9. **遇到标了 🔒 的决策点：停下来问，不要自行拍板。** 尤其 T-08/T-09，未经授权不得开工。
10. **行号会漂**：每条改法前先用附录 A 的命令复核当前 `HEAD`。**依据求值点与默认装配点，不依据提交标题。**

---

## 1. 工单总表

> ⚠️ 本表 2026-09-30 重排：原先**没有状态列**，我把进度塞进"需决策"格，
> 造成 T-02/T-03/T-05 明明已入库却显示 `—`、同一格承载两种语义。现拆出独立"状态"列，
> 并补上此前只活在散文里、表内无行的 T-10/T-11/T-12（票号悬空）。

| 工单 | 一句话 | 阻塞 | LOC | 风险 | 需决策 | 状态（入库/活体） |
|---|---|---|---|---|---|---|
| **T-01** | 占位端点报成功 + 前端封装必然 422 | — | ≈ **−30** | 低 | 无（T-01b 已闭合） | 入库 `793dc63e`；活体 §2.6 ✅ |
| **T-02** | 桌面/浏览器工具三张名字清单无一致性守卫 | — | +90（全在测试） | 零（纯守卫） | — | 入库 `b88f36c2`；纯守卫无活体要求 |
| **T-03** | 快照新鲜度两后端语义分叉（5 vs 1） | T-02 | ≈ +25 | 中 | — | 入库 `5e603c84`；活体 ✅（§13.2：generation 2 到 3，旧值复点被拒） |
| **T-04** | "只写不读"族：`max_marks`、1200 节点承诺、observe 不吃 generation | T-02 | ≈ **−20** | 低 | 无 | 入库 `26da655b`；活体 §5.6 ✅ |
| **T-05** | SOM 标记态挂实例：并发会话互相覆盖 | T-02 | +40 | 中 | — | 入库 `34f61007`；活体 ✅（§13.3：真实截屏+真实检测器，平移 3px 逼出 24 个同 id 撞号，各会话解到自己坐标；变异对照=单槽覆盖时 A 实发 B 的坐标） |
| **T-06** | 快照被硬切时不报丢失量、不接分片续读补救 | 30% 页触发，触发时九成可交互元素不可见 | +30→+214 | 中 | 无 | 入库 `056db20b`；活体 §7.5 ✅ |
| **T-06b** | 节点/深度预算静默裁剪 + camofox 整条绕过字符预算 | 同一根因三条出口 | +57 | 低 | 无 | 入库 `cf6ac06b`；活体 §5.7 ✅ |
| **T-07** | 能力可用性是硬编码布尔，非带 owner 的三态探测 | — | +150 | 中 | 🔒 D-3 | 未开工；**现场证据已量到**（§13.3：`.env` 设了 URL ⇒ `_camofox_enabled=True`，而 `:9377` 实测超时；今天不出故障只因 playwright 恰在选路首位，一旦缺 playwright 就会推进 supervisor 的 autostart=True 拉起分支） |
| **T-08** | 浏览器无稳定动作句柄，每步重快照 | T-03 | +200 | **高（改 provider 可见契约）** | 🔒 D-1、D-2 | 未开工（D-6 的歧义分支卡在此：候选列得出、动不了） |
| **T-09** | 截图从不进模型上下文 | — | +120 | **高（改感知模式）** | 🔒 D-4 | 未开工 |
| **T-10** | 语义目标解析（§13 D-6 第一片） | 唯一命中才动作 | +100 | 中 | 无 | 入库 `96eb6e58`；活体 §13.1 ✅（**仅进程内，socket 层未验**） |
| **T-11** | 撤 `smart-click` 的 501 + 前端载荷对齐 `{target}` | T-10 | 含上 | 低 | `smart-type` 归属待定 | **部分**：click 已接；`smart_type` 等 4 面仍诚实 501 |
| **T-12** | 空快照被当成功快照（`success=True` + 空正文），致 502 分支不可达 | T-06b | +29 | 低 | 无 | 入库；代码与判据已落地（10 例，含两后端 parity 与 502 可达性）；**502 分支活体 ✅**、**camofox 那条口在真 HTTP 传输 + 契约桩上 ✅**（§13.3，正对照 159 字符 / 空正文回 `snapshot-empty` 且拒绝路径不再按旧事实动作）；Playwright 侧原"空正文"形态 5 个候选态均未复现。唯一未证：真实容器自身的字段与错误形态（装它需授权第三方全局包） |
| **T-13** | "取不到事实"在产出侧是内部英文裸串（18 处、3 种措辞），模型拿到只能瞎猜 | T-12 | ≈ +6（净） | 低 | 无 | 本轮落地；判据 7 例（含两后端**整句相等**parity + AST 反证回潮）；活体 ✅（§13.3：502 detail 现为 `no-active-tab: …——请先 browser_navigate …`） |
| **T-14** | 浏览器/爬虫集成测试 26 例常驻红：断言的是从未实现的设计 | — | −260 ～ +400（取决于处置） | 中（含合规面） | 🔒 **D-7** | 未处置；**全集已量出并复算**（§14，含 D-5 复核补的 1 例）。CI 不跑这族文件，红只在本地全量出现，却次次要人肉解释 |
| **T-15** | 子进程文本读取不落 encoding ⇒ 机器 ANSI 码页决定成败，文档守卫族整族假红 | — | 已修 13 处 + 棘轮；余 97 处待清 | 中 | 无 | **本轮落地**（§15）：`neurova.core.proc_text.runText/decodeChild` 单源入口，**生产码 12 处全部改走它**（docker_builder 6、camofox_supervisor 3、env_check 2、exec_sandbox 1）+ 文档扫描器 1 处；棘轮基线 109→**97**，`neurova/` 另设**零基线档**。本机实测该守卫族 **13 FAILED + 6 ERROR → 30 passed**；沙箱活体证明 UTF-8 输出不再被吞成空串 |
| **T-16** | 沙箱后端漏实现 `enforced()` ⇒ Windows 上代码执行工具直接崩，Linux CI 看不见 | T-15 | +28（含判据） | 低 | 无 | **本轮落地**（§16）：`AppContainerSandbox`、`RestrictedTokenSandbox` 两个后端补齐契约（扫荡时抓到第二个，只修被点名的那个会留崩链）；接口完整性判据 4 例（自动发现后端 + 正对照）；`resolveBackend` 的 reason 文案同批改回"跟着值走"。沙箱块 **9 failed → 56 passed**，真机活体 `exit_code=0 / backend=appcontainer / enforced=true` |

**批次实况**：`T-02 → T-01 → T-03 → T-04 → T-05 → T-06 → T-06b → T-10/T-11(部分) → T-13` 已走完；
**剩余**：T-12 的"真实容器自身字段形态"（需授权装第三方全局包）→ 决策后 `T-08` → 回补 T-11 的歧义分支
（候选列得出、动不了，卡在 🔒 D-1/D-2）→ `T-07`（🔒 D-3，含 manager 层两处英文抛出收口）→ `T-09`（🔒 D-4）
→ `T-14`（🔒 D-7：退役这族测试还是把契约补回来）。
自主可完成的面至此**全部收口**。

**T-02 必须最先**：它是守卫，T-03/T-04/T-05 都在改这三张表覆盖的面；先有守卫，后面的改动才会被拦住而不是被绕过。

---

## 2. T-01 · 占位端点报成功，且有一个前端封装必然 422

### 现象（三条均已亲验）

1. **六个端点以成功响应体面掩盖"能力不存在"**（`neurova/api/endpoints/computer.py`）：
   `:475` `visual-parse`、`:486` `smart-click`、`:497` `smart-type`、`:681` 链接抽取、`:694` JS 执行、`:792` scrape——
   一律 `"code": 0` + `"message": "...(placeholder)"`。其中 `smart-click`/`smart-type` 还回 `{"found": False}`。
   **`found: False` 与"我试过了、目标元素不在"在语义上不可区分。** `AGENTS.md` 教义第 2 条要求诚实形态暴露（显式 4xx/5xx、`not_supported`、点名失败原因）——当前形态属反面。
2. **前后端契约不匹配，调用必失败**：`NeurUI/src/api/modules/computer.ts:56-58` 的 `smartClick(agentId, x, y)` 发 `{agent_id, x, y}`；
   后端 `SmartClickRequest`（`computer.py:100-103`）字段是 **`target: str`（必填）** 与 `screenshot`，**没有 `x`/`y`**。
   Pydantic 缺必填字段 ⇒ **恒 422**。`visualParse`（`:61-63`）发 `{agent_id}`，后端字段全可选 ⇒ 能通，但通到的是占位。
3. **有消费方，但其唯一效果是报错**（⚠️ 本条原写"无任何组件调用方"，**是错的**，
   2026-09-30 复核纠正）：`NeurUI/src/pages/AgentComputerPage.vue` 上确有按钮
   （`@click="visualParse"`，该页在 `src/router/index.ts:213` 注册可达），处理函数是
   `message.info(JSON.stringify(res?.data ?? res))`——而端点恒 501，所以它今天唯一能给的
   就是一个错误提示。原判错误的成因很具体：那次检索用了 `| head -8`，`.vue` 的命中
   被自己截断吃掉了。**教训：建立"不存在"这类全称结论的检索，一律不得截断输出。**
   文案铺满 11 份 locale（如 `NeurUI/src/i18n/locales/de-DE.ts:1806-1807`）。

### 判据（红灯，先写）

`tests/unit/api/test_computer_placeholder_honesty.py`：

- `test_placeholderEndpointsDoNotReportSuccess` —— 逐个打这六个端点，断言响应**不满足** `code == 0 且无 not_supported 标记`。
- `test_smartClickRefusalIsDistinguishableFromMiss` —— 断言"能力未实现"与"目标未找到"是**两个不同的可判定值**，不许同词。
- `test_smartClickFrontendContractMatchesBackendModel` —— 静态判据：`computer.ts` 里 `smart-click` 的 post 体字段集合，必须与 `SmartClickRequest` 的必填字段集合一致（比对字段名，不比值）。

### 改法（择一并说明理由，不许混用）

- **默认取"诚实化"**：响应体加显式 `status: "not_supported"` 且 `code` 走非 0 的业务错码；`message` 保留点名。
  对 `smart-click`/`smart-type`：**同时**修 `computer.ts` 的字段（`{agent_id,x,y}` → 与后端契约一致），或直接删该封装（见下）。
- **删面**：若确认无消费方，`smartClick`/`visualParse` 两个 api 封装与其端点一并退役；i18n 文案按同批改（见扫荡）。

### 同根因扫荡（教义第 5 条）

- 全仓 grep `"message": .*placeholder` 与 `found": False`，**不限于 `computer.py`**——命中点全部列出并逐条给处置。
- **i18n 是 11 语言同批**（`src/i18n/locale-consistency.test.ts` 会守）：删文案必须 11 份一起删，删不掉就留着别动。
- 前端封装退役需确认 `NeurUI` 侧无动态字符串调用（`grep -rn "\['smartClick'\]\|smartClick("`）。
- 退役端点须登记进台账口径（若已有 `toolLoopDeadlines` 之外的 API 面台账，按其格式；无则在 commit 正文点名）。

### 验收 & LOC

- 活体（教义第 4 条）：起真后端，`curl` 打这三个端点，**响应原文进 commit**；再从前端函数路径打一次 `smart-click`，证明 422 已消除（或该路径已不存在）。
- 前端：`npm run test` + `npx vue-tsc --noEmit` + `npm run lint`。
- 净 LOC：删六处占位体 ≈ −60，加 `not_supported` 形态 +20，测试 +90 → **生产侧约 −30**。

### 2.6 活体补验（2026-09-30，真后端 `localhost:9527`，凭 admin 登录后打真端点）

六个改诚实拒绝的端点**全部返回 501 且理由具名**，响应原文：

```
POST /api/v1/computer/visual-parse          -> 501 {"detail":"视觉解析（UI 元素检测）未实现（原以 code 0 + elements 恒空 形态谎报成功）"}
POST /api/v1/computer/smart-click           -> 501 {"detail":"语义目标智能点击未实现（原以 code 0 + found 恒 False 形态谎报成功）"}
POST /api/v1/computer/smart-type            -> 501 {"detail":"语义目标智能输入未实现（原以 code 0 + found 恒 False 形态谎报成功）"}
POST /api/v1/computer/browser/extract-links -> 501 {"detail":"浏览器链接抽取未实现（原以 code 0 + links 恒空 形态谎报成功）"}
POST /api/v1/computer/browser/execute-js    -> 501 {"detail":"浏览器 JS 执行未实现（原以 code 0 + 已报 "JS executed" 形态谎报成功）"}
POST /api/v1/computer/browser/scrape        -> 501 {"detail":"网页结构化抓取未实现（原以 code 0 + 已报 "Scrape complete" 形态谎报成功）"}
```

登录端点回 `access_token/refresh_token/expires_in/token_type`（口令不入库不入文档）。
`/api/v1/computer/status` 无 token 时回 401，证实这组端点确在鉴权后、打到的是真装配。

**未达成项（不许含糊）**：验收要求"从前端函数路径打一次 `smart-click`，证明 422 已消除（或该路径已不存在）"。
两条都不成立——按 `NeurUI/src/api/modules/computer.ts:56-58` 的原样载荷再打一次：

```
POST /api/v1/computer/smart-click {"agent_id":"agent_a","x":10,"y":20}
  -> 422 {"detail":[{"type":"missing","loc":["body","target"],"msg":"Field required",...}]}
```

且 `smartClick`/`visualParse` 现经全仓检索：`smartClick` **只有定义行 + 11 份 locale，无组件调用方**；
`visualParse` 则**有**一个页面上的按钮在调（见 §2 现象第 3 条的纠正），只是端点恒 501 使该按钮
只能报错。检索已排除 `.mimosa` 快照目录（那里全是插件基线，会造成假命中），
且**不再用 `head` 截断**——上一版就是截断导致的误判。即 §2 现象第 3 条仍然成立，
它归 **T-01b** 的 🔒 决定：退役封装连同 locale 同批改，还是把载荷改成 `target` 语义面。
后端侧的谎报已闭环，前端侧的死面未动。

---

## 3. T-02 · 三张名字清单无一致性守卫（纯守卫，零行为变更）

### 现象

同一族工具有三处并行的名字定义，彼此无机械对账：

| 清单 | 位置 | 用途 |
|---|---|---|
| `COMPUTER_USE_TOOLS` | `neurova/tool_executor.py:59-82` | 判定是否走 `normalize_computer_params`（`:1982`）、审计（`:1995`）、事件面（`:4869`） |
| `_COMPUTER_TOOL_PARAM_KEYS` | `:112-133` | 每工具参数白名单 |
| `_builtin_dispatch` | `:291-310` | 工具名 → 方法名 |

已有守卫只覆盖一条轴：`tests/unit/computer_use/test_action_refresh_declaration.py:129` 断言 `interactive_desktop` 派生名 ⊆ `COMPUTER_USE_TOOLS`。**三表互校无人管**——加一个 `computer_*` 工具而漏填其一，当前不会红。

### 判据

`tests/unit/computer_use/test_computer_tool_faces_reconcile.py`：

- `test_computerUseToolsAllHaveParamKeys` —— `COMPUTER_USE_TOOLS` ⊆ `_COMPUTER_TOOL_PARAM_KEYS.keys()`。
- `test_computerUseToolsAllDispatchable` —— 三者 ⊆ `_builtin_dispatch`（能声明就必须能派生）。
- `test_paramKeysNotOrphaned` —— 反向：`_COMPUTER_TOOL_PARAM_KEYS` 的键 ⊆ `COMPUTER_USE_TOOLS ∪ browser_* 面`（不留只在一处出现的孤儿）。
- `test_computerToolSchemasDeclareCapability` —— 桌面/浏览器工具须在能力声明里有条目（对齐 G3 的 `core/tool_capability.py`），**未声明即红**。
- **反向控制**：故意往 `COMPUTER_USE_TOOLS` 塞一个假名，判据必须红；否则上面四条是在空转通过（沿用 `test_context_deadline_disposal.py` 的反向控制纪律）。

### 改法

**本单不改生产代码**。若判据当场抓到真实不一致，那是一条独立缺陷——单独开工单修，**不要在本 commit 里顺手改**（否则守卫的红灯会被实现变更掩盖）。

### 验收 & LOC

- `.venv/Scripts/python.exe -m pytest tests/unit/computer_use -q`，**跑测合入前后失败名集合逐条比对**。
- 净 LOC：生产 **0**；测试 +90。这正是本单排在最前的理由——零风险换一张拦后续所有改动的网。

---

## 4. T-03 · 快照新鲜度两后端语义分叉

### 现象（亲验，数字准确）

`generation` 是"这份快照事实还新不新"的唯一凭据，入口都查它，但**只有 camofox 会让它在交互后失效**：

- **Playwright 侧推进点：仅 1 处** —— `neurova/computer_use/browser_manager.py:546`（navigate）。
  `click_role`（`:464-498`）、`fill_role`（`:500-514`）**只查不推**，且把当前值原样回给调用方 ⇒ 模型拿着旧 `generation` 在 DOM 已被自己改动的页面上继续按 role 操作，**照样通过**。
- **camofox 侧推进点：5 处** —— `camofox_server_backend.py:229`、`:396`（注释明写"交互使快照事实失效"）、`:422`、`:562`、`:591`。

⇒ 同一个工具（`browser_click_role`）在两个后端下**新鲜度语义不同**。这不是风格差，是判据差。

### 判据（红灯）

`tests/unit/computer_use/test_snapshot_freshness_parity.py`：

- `test_generationTrajectoryIdenticalAcrossBackends` —— **参数化两个后端**，喂同一条动作序列（navigate → snapshot → click_role → click_role），断言每次响应携带的 `generation` 序列**逐个相等**。这是本单的示踪弹：现在必红（Playwright 给 `[1,1,1,1]`，camofox 给 `[1,1,2,3]` 形态）。
- `test_staleGenerationRejectedAfterDomMutatingAction` —— 快照后执行一次会改 DOM 的动作，再用旧 generation 调 `*_role`，须返回 stale 且带 `current_generation`（`browser_manager.py:348-355`/`:405-409` 已有该形态，断言两后端都走到）。
- **反向控制**：把推进点全注释掉，第二条必须还红（防判据退化为"永远不等就永远通过"）。

### 改法

1. 先定语义并写进 docstring：**哪些动作算"使快照事实失效"**。基线取 camofox 现行为（navigate + 会改 DOM 的交互），并在注释里写明"改此集合须同步两后端"。
2. 在 Playwright 侧对应分支补推进（`:464-514` 一族），**复用** `:546` 的同一推进表达，不新造第二个自增点。
3. 若发现某动作两后端事实上影响不同（例如 camofox 无法感知某类局部刷新），**如实记录在判据的 skip 理由里**，不许悄悄放宽断言。

### 同根因扫荡

`grep -rn '"generation"' neurova/computer_use/` 列出全部读写点，逐个判"读而未失效 / 写而不对称"。桌面侧同类问题是 `desktop_uia.py:147`、`:203` 在 click/set_value 后自增——**桌面与浏览器的失效集合应取自同一处定义**，否则本单修完只是把分叉搬了个家（🔒 见 D-5）。

### 验收 & LOC

- 活体：真起 Playwright 后端，跑"快照 → 点一个会改写列表的按钮 → 用旧 generation 再点"，须看到 stale 拒绝；证据（截图或响应原文）进 commit。
- 净 LOC：生产 ≈ +25，测试 ≈ +130。

---

## 5. T-04 · "只写不读"族三条（一次扫荡收干净）

三条同属 `AGENTS.md` 协作红线明令禁止的"只写不读的配置 / 只写不读的字段"，合并成一单以便一次扫荡。

| # | 断点 | 亲验证据 |
|---|---|---|
| a | **`max_marks` 是死参数** | 声明在 `neurova/builtin_tools.py:303`、放行在 `tool_executor.py:121`，**全仓再无读取点**；`mark_screenshot` 调用时不传（`:4761`），唯一真值是 `computer_use/som.py:26` 的 `_MAX_MARKS = 60`。模型传什么都被无声忽略 |
| b | **`browser_dom_snapshot` 的"默认 1200 节点"是文档假象** | 承诺在 `builtin_tools.py:438`、`:443`；实际 `_trim_snapshot_tree`（`browser_manager.py:772-798`）收到 `None` 时**什么都不做**，两个后端都没有 1200 这个默认值；真正咬人的是 8000 字符硬截断（`tool_executor.py:5035-5038`） |
| c | **`computer_dom_snapshot` 不接受 `generation`** | 其参数键集合（`tool_executor.py:118`）里没有 `generation` ⇒ **观察这一步无法做新鲜度校验**，模型只能靠"下一次点击会不会被拒"倒推自己看的快照过期了 |

### 判据

`tests/unit/computer_use/test_computer_config_is_read.py`（三条各自红）：

- `test_maxMarksActuallyBoundsMarks` —— 传 `max_marks=3`，返回的 `marks` 长度必须 ≤ 3。现状红（恒 60）。
- `test_domSnapshotDefaultMatchesDocumentedBound` —— 不传 `max_nodes` 时，实际节点上限必须等于描述里写的数；**二者不一致即红**（现状：描述 1200，实际无默认）。
- `test_observeToolsAcceptGenerationForStalenessCheck` —— 断言所有"产出可被后续动作引用的快照"的观察工具，参数面含 `generation`。

### 改法（每条给两个选项，取其一并在 commit 说明为何）

- **a**：① 接住——`mark_screenshot` 收 `max_marks`，与 `_MAX_MARKS` 构成"默认 + 上限夹紧"，夹紧后回显 `max_marks_applied`；或 ② 删——从 schema 与放行表移除，让 `normalize_computer_params` 的未知键拒绝（`tool_executor.py:156-158`）生效。**②更省，且本仓纪律是"不留只写不读的配置"**；除非有真实需求要模型控标数，取 ②。
- **b**：**承诺与实现对齐**——把 1200 真做成默认（在 `_trim_snapshot_tree` 的缺省路径上），或把描述改成实话（"默认不限，受 8000 字符截断约束"）。**不许保留"文档说有限、代码不管"** 这个中间态。
- **c**：给 `computer_dom_snapshot` 增加 `generation` 入参并**只用于回显对比、不改自增语义**（避免与 T-03 的失效集合打架）。注意：`generation` 语义要与 `desktop_uia.py:280-285` 的过期提示同一形态。

### 同根因扫荡

`grep -rn '"[a-z_]*": {"type"' neurova/builtin_tools.py` 与放行表、执行体做**三方对账**，把所有"声明了但没人读"的参数一次列全（不限本域），结果登记进台账或写入 commit 正文的待办块——**不许只修这三条就收工**。

### 验收 & LOC

- 净 LOC 预期为**负**：a 取删则 −8；b 取实话则 −2；c 加参 +18；测试 +120。
- 活体：真跑一次 `computer_som_snapshot` 与 `browser_dom_snapshot`，把响应里边界生效的证据进 commit。

### 5.6 活体补验（2026-09-30，真 Chromium + 真宿主桌面，走生产入口不 monkeypatch）

**① 幻影旋钮已被大声拒绝**（取 a 案 ②：删面），`normalize_computer_params` 现读数：

```
computer_som_snapshot  {"max_marks": 30}            -> 拒绝 ValueError: 未知参数 ['max_marks']（computer_som_snapshot 只接受 []）
computer_som_snapshot  {"max_nodes": 12}            -> 拒绝 ValueError: 未知参数 ['max_nodes']（computer_som_snapshot 只接受 []）
browser_dom_snapshot   {"max_marks": 30}            -> 拒绝 ValueError: 未知参数 ['max_marks']（browser_dom_snapshot 只接受 ['generation','max_depth','max_nodes']）
browser_dom_snapshot   {"max_nodes":15,"max_depth":3} -> 通过
```

拒绝消息把"该工具到底接受哪些参数"一起报出来，模型可自纠；不是静默丢键。

**② 边界确实在裁**（`browser_dom_snapshot`，MDN 一页，经 `_execute_browser_dom_snapshot`）：

```
（不给预算）                     -> 7908 chars / 191 行  最大深度=10  truncated=True   folded=568
{"max_nodes": 15}               ->  390 chars /  15 行  最大深度=5   truncated=None   folded=None
{"max_depth": 2}                ->  127 chars /   9 行  最大深度=2   truncated=None   folded=None
{"max_nodes":15,"max_depth":2}  ->  127 chars /   9 行  最大深度=2   truncated=None   folded=None
```

**③ 真桌面 SOM 出编号**：`success=True count=60`，marks 样例
`[{"id":64241,"center":[998,338],"label":"region56"}, ...]`；响应里已不含被删参数名。

**④ 活体量出来的新缺陷（已修为 T-06b，见下）**：显式给 `max_nodes`/`max_depth` 时结果被裁掉
176 行、深度从 10 压到 2，而响应里 `truncated`/`foldedActionableCount` **全是 None**——
预算裁剪这一路不做任何上报。这不是新病，`browser_manager.py` 的 `dom_snapshot` 文档串里
当时承认根因：`BrowserResult` 没有承载字段、`_trim_snapshot_tree` 的第二个返回值在调用点被丢弃。

### 5.7 T-06b 落地状态（2026-09-30）

量出 ④ 之后逐条深挖，发现它不是"少报一个字段"，而是**三条独立缺陷同一根因**
（感知预算的执行与上报没有单源）：

| 缺陷 | Playwright 后端 | camofox 后端 |
|---|---|---|
| 预算裁剪上报 | 第二返回值**直接丢弃** | 只并入一个布尔，且藏在 `data` 里 |
| 上报形状 | 无 | `data["truncated"]`（dict 载荷） |
| 字符预算是否生效 | 生效 | **整条绕过**——执行器只处理 `isinstance(data, str)` |

第三条不是死路：camofox 在启用时是**首选路由**（`browser_manager.py` 里选路判定先于
playwright），所以启用它的部署从未对 aria 快照应用过字符预算。

**改法**：`applySnapshotBudget()` 成为两后端共用的唯一裁剪+读数入口
（`_trim_snapshot_tree` 现仅剩它一个调用方，双头消除）；`BrowserResult` 新增
`truncated`/`hiddenNodes`/`hiddenActionable` 承载，`to_dict()` **未裁剪时不留字段**（零值
挂满每次快照是噪声不是信息）；执行器两种载荷形状都过字符预算。可交互项计数与字符折叠
共用同一份 role 口径，不另造第二套。

**活体复验（真 Chromium，同一页同一组参数，与 §5.6 前后对照）**：

```
（修前）{"max_nodes": 15}   -> 390 chars/15 行  truncated=None  folded=None
（修后）{}                  -> 7908 chars/191 行 深度=10 | truncated=True  hiddenNodes=None  folded=568
（修后）{"max_nodes": 15}   ->  390 chars/15 行 深度=5  | truncated=True  hiddenNodes=3076  hiddenActionable=614
（修后）{"max_depth": 2}    ->  127 chars/9 行  深度=2  | truncated=True  hiddenNodes=3082  hiddenActionable=616
```

不给预算那行 `hiddenNodes` 缺席是正确的——字符预算折叠走的是 `folded*` 那组字段；
两条预算各报各的，不互相顶替。

**判据**（`tests/unit/computer_use/test_snapshot_budget_honesty.py` 9 例）：读数与夹具已知量
逐数对齐；两后端承载字段与键集合一致；未裁剪不留噪声字段；camofox 的 dict 载荷也必须过字符预算。
两条承重路径各做过变异：把 Playwright 的读数改回丢弃 → 2 条 parity 判据转红；
把执行器改回只认 str → camofox 折叠判据转红。

净 LOC：生产 +57（`browser_manager.py` +44 承载与单源入口、`camofox_server_backend.py` +4 改接入口、
`tool_executor.py` +9 双形状）、测试 +210 行。`tests/unit/computer_use/` 现 **453 passed / 2 skipped**。


---

## 6. T-05 · SOM 标记态挂实例，并发会话互相覆盖

### 现象（亲验）

`self._last_som_id2xy` 是 `ToolExecutor` 实例上的裸属性：写入在 `tool_executor.py:4764`、读取在 `:4792`（`getattr(self, "_last_som_id2xy", None) or {}`）。
**无锁、无会话键、无代际**。两个并发会话各自 `computer_som_snapshot` 后，后者的 `id2xy` 覆盖前者 ⇒ 前者的 `computer_click_mark(index)` 会按**别人那张图的坐标**点击。SOM id 本身是确定性的（`som.py:30-33`，`md5(量化中心+label) % 100000 + 1`，跨进程可复现），所以**两个会话可能拿到相同 id 却指向不同元素**——这不是"点了没反应"，是"点错了还报成功"。

> 这与 G1 已修的"轮次态挂 per-agent 单例"是**同一个病形**（跨会话共享可变实例态）。G1 已建 `neurova/agent/loops/turn_run_state.py`，本单是其收口面在电脑操控域的延伸。

### 判据

`tests/unit/computer_use/test_som_marks_are_session_scoped.py`：

- `test_concurrentSessionsDoNotCrossInvalidateMarks` —— 交叠驱动两个会话：A 快照 → B 快照 → A 用其 id 点击，断言 A 用的是**自己那张快照**的坐标。现状必红。
- `test_staleMarkYieldsHonestRefusalNotWrongClick` —— 标记所属快照已不属于本会话时，须返回结构化拒绝（复用 `action_result.py` 的 `REFUSAL_CODES` 词汇表，**不新造第二种拒绝形态**），且**不得发出点击**。
- `test_markStateNotInstanceAttribute` —— 静态断言 `ToolExecutor` 上不再存在 `_last_som_id2xy` 这类无键裸属性（同族守卫见 G1 §8.1）。

### 同根因扫荡（这条最重要）

`grep -rn "self\._last_\|self\._current_" neurova/tool_executor.py` —— 电脑操控域同类"单槽实例态"很可能不止 SOM 一处（UIA 会话表 `desktop_uia.py:58` 是 dict 且有 `RLock`，但键是 `win:{title}`/`__foreground__`，**跨用户共享、进程级单例、无 TTL**，见 `:579-588`——一并列出评估）。命中点逐个给处置或登记台账。

### 验收 & LOC

- 活体：两会话并发各做一次 SOM 快照与点击，验证坐标归属正确（真桌面可退化为沙箱/guest 桌面，但要真链路）。
- 净 LOC：生产 ≈ +40（含会话键与锁），测试 ≈ +120。

---

## 7. T-06 · 撤案并因：原判据不成立，真缺陷是"截断量不报、补救不接"

> **本节 2026-09-30 整体重写。** 原版把 T-06 立成"结果 dict 键序未参与设计，
> 于是 url/title 被截在尾部"——该前提经读码**证伪**，且"改折叠"这一替代方案
> 经真机量测**否证**。下面先记错误，再记量出来的东西。

### 7.1 原前提为什么不成立

8000 字符硬切只作用在两处，且作用对象是**字符串字段** `result["data"]`，不是整个结果 dict：
`_execute_browser_extract_text`（保留头部 + `…[已截断]` + `result["truncated"]=True`）、
`_execute_browser_dom_snapshot`（同一形态）。因此：

- **键序与截断无关**——`url`/`title`/`generation`/`duration_ms` 是兄弟键，不进 `data` 字符串，
  永远不会被这一刀切掉。"先被截掉的是页面是什么"是错的。
- **`truncated` 已经在报**，不存在"一个面替另一个面发声"的双面缺口。
- 全仓 `8000` 命中只有这两处（另两处 `:2969/:2971` 是别家的 `max_chars` 参数）。
  **桌面 `computer_dom_snapshot` 不吃字符硬切**，它走 `DEFAULT_MAX_NODES=400` 节点预算并自带
  `truncated`/`max_nodes` 字段。所以本单的作用面比原方案窄一半。

### 7.2 量测：触发频率与截断比例

**先找历史样本，结论是没有。** `data/context_ledger/*.db` 的 `evicted_chunks` 是唯一落盘的
工具结果正文，`source='tool_call'` 共 **87 条**；按 agent 分 `default` 74 / `a-tool` 7 / `a1` 6，
后两类正文是"这是内容"式占位夹具。`default` 那 74 条按形态归类后
（date/time、`exit_code`+`duration_ms` 的 run_code、`category`+`count`+`limit` 的检索、
`content`+`lines` 的文件读…）**没有一条是感知类快照**；其中超 8000 的 6 条也全是 run_code /
检索 / 文件读。`data/sessions/**.json` 3209 份会话、13196 条消息里 `role` 只有
assistant/user，零 tool 消息、零 `tool_calls` 结果体。⇒ **历史数据量不出这条路径，不作合成替代。**

**改真机驱动**（同一取法：`page.locator("html").aria_snapshot()` 与 `inner_text("body")`，
生产点 `browser_manager.py:470` 就是这个调用；默认不传 `max_nodes/max_depth`
→ `_trim_snapshot_tree` 不裁剪 → 字符硬切就是实际生效的那一刀）。10 页全部导航成功：

| 指标 | 读数 |
|---|---|
| aria 快照触发硬切 | **3/10 = 30%** |
| aria 字符分布 | min 10 · p50 4216 · max 166720（**双峰**，小页极小、大页爆表） |
| 触发时字符损失 | 94.2% / 95.4% / 80.8% |
| 触发时**可交互元素**损失 | 554/615 = **90.1%** · 715/768 = **93.1%** · 176/217 = **81.1%** |
| 正文提取触发硬切 | 2/10 = 20%，损失 77.8% / 85.1% |

判据自身做过两面对照：正对照 6/6（含 `- checkbox:` 这种裸冒号形态——修前会漏）、
反对照 0/6（`heading`/`paragraph`/`/url`/`img` 不误收），并与独立正则在同一真树上读数一致（46==46）。
**第一次跑出的可交互损失是 0，就是判据在真 aria 格式上空转**（我按合成串里自写的 `role=button`
语法建的判据），修正后才拿到上面这组数。

**"折枝叶留骨架"被量否证**：把非可交互、非可交互祖先的行全部折掉后，
剩下的可交互骨架本身仍是预算的 **1044.6% / 1086.7% / 253.9%**（83568 / 86937 / 20313 字符）。
超限页的问题是**可交互面本身就装不下**，不是描述性枝叶挤占了它。所以原设想的"折叠代替硬切"不成立。

### 7.3 由此剩下的真缺陷（本单新判据）

`browser_dom_read` **早就在仓里**，形态正是这件事的正解：一次观察、按 `session_id`/`next_offset`
分片续读到 `can_continue=false`（`builtin_tools.py:508`，描述里写明面向"完整阅读"）。
`browser_extract_text` 的描述也已经指向它。**但 `browser_dom_snapshot` 的截断点什么都没接**——
既不报丢了多大量，也不报丢了的可交互元素有多少，更不提示改用 `browser_dom_read`；
工具描述里同样没有这句路由。于是那 30% 的页面上，模型只看到树的前缀
（结构上就是页头导航那批 chrome），**约九成可交互元素静默不可见**，而它能用的补救手段就在隔壁工具、无从得知。
这是 `AGENTS.md` 协作红线意义上的**断点**：能力写了没接进反馈环。

**要做的事**（净 LOC 应显著低于原估的 +35）：

1. 截断时如实量化：在 `result` 上补 `data_chars_total`、`interactive_candidates`/`interactive_dropped`
   之类的量（口径见 §7.2 判据，行首 role 解析），别只留一个布尔。
2. 把补救接上：截断结果里给出改用 `browser_dom_read` 的显式提示，并按既有
   `_pending_hints` 机制回灌进反馈环——不要只塞在 data 尾巴的字符串里。
3. `browser_dom_snapshot` 的工具描述补一句"快照被截断时改用 browser_dom_read 续读"，
   与 `browser_extract_text` 的描述口径对齐（两处描述现在是两套说法）。

**判据**（`tests/unit/computer_use/test_snapshot_truncation_honesty.py`）：

- 造一棵真格式、必然超 8000 的 aria 树，断言响应里带量化字段且数值与构造已知量相符
  （不是"字段存在"就算过）。
- 断言截断路径产出补救提示，且提示里点名的工具名在 `builtin_tools` 里真实存在且有执行分支
  （防止提示指向一个不存在的路由）。
- 未超限时必须**不**带这些字段——否则是新增噪声。
- **反向控制**：把量化字段改回常量 `0`、把提示删掉，两条断言都要红。

### 7.4 边界

结构性解法（把 `camofox` 侧已有的 ref 透出为一等寻址、读/动作分预算）在 **T-08**，
受 🔒 D-1/D-2 约束，不由本单顺带解决。本单只把"已经丢了三成页面里的九成事实"这件事
改成**报得出、有路可走**。

### 7.5 落地状态（2026-09-30）

§7.3 的三条**已全部落地**，并被前置的一张票改变形状：

| §7.3 条目 | 现状 |
|---|---|
| ① 截断时如实量化 | 已落：`dataCharsTotal` / `actionableCandidates` / `foldedActionableCount` 三字段进模型可见结果，与正文计数行同源。`SnapshotFold` 数据类承载（与本仓 `OffloadOutcome` 同形），可交互项口径单源在 `_snapshotActionableRoles()` |
| ② 接上补救 | 已落，但**不走 `_pending_hints`**——那条通道承载的是异步终态（超时转后台、审批已裁决），同步事实再投一份就是同一信号发两遍。改为计数行内点名 `browser_dom_read`，并加守卫：指引点名的工具必须同时在 `_BUILTIN_SCHEMAS` 和 `_builtin_dispatch` 里存在（幻影参数 `max_marks` 的前车之鉴） |
| ③ 描述口径对齐 | 已落：`browser_dom_snapshot` 描述写明超限后是跨全树等距折叠、三字段含义、以及"不要按『快照里没出现』推断页面没有该元素" |

**前置改变形状的一票**：折叠先落地（`foldSnapshotTree`，测试
`test_snapshot_fold_replaces_chop.py` 20 例 + `test_snapshot_truncation_honesty.py` 10 例）。
折叠的真实形态与 §7.1–7.2 的两版设想都不同：

- 首版按**区带**分配预算 → 活体否证：真页面区带极碎（MDN 一页 566 个区带、最大仅 9 项），
  "每区带留 1 项"本身就超预算，永远掉进兜底，尾部覆盖 0。
- 终版按**全树等距取样**，样本条数二分出"能塞进预算的最大值"；祖先链只保最近 1 层
  （实测：不封顶时维基只留 22 项、封 1 层留 59 项，硬切是 52 项）。
- 因此 §7.2 里"折叠骨架仍超预算"那条否证**只否证了"留全部可交互项"**，
  没有否证折叠本身——预算内做全局抽样是成立的，只是必须承认它**保留的元素数可以少于硬切**
  （付给计数行与跨树取样），换来的是覆盖整页 + 显式报出被折项数。

活体复验（真走 `_execute_browser_dom_snapshot`，非合成）：

```
docs-long  : 全树 140219 chars/623 项 -> 可见 7732 chars/51 项，字段 {truncated,140219,623,572}
list-dense : 全树 139401 chars/666 项 -> 可见  7303 chars/59 项，字段 {truncated,139401,666,607}
search     : 全树  41436 chars/218 项 -> 可见  7785 chars/47 项，字段 {truncated,41436,218,171}
计数行原文： - /folded: 折叠 572 项（button×12、link×560）；全文改用 browser_dom_read 续读；已省略祖先层级，正文按扁平呈现
```

净 LOC：生产 +214（`browser_manager.py` 折叠器与口径单源 +200、`tool_executor.py` 两处调用点 +15、
`builtin_tools.py` 描述改写 0 净），测试 +536 行两个文件。
`tests/unit/computer_use/` 现 **444 passed / 2 skipped**；`tools/` 两条失败
（`test_tool_loop_deadline_disposal`、`test_tool_parallelism_readout`）经 A/B 回 HEAD 复跑证实**预存**。


---

## 🔒 以下三条未经授权不得开工

## 8. T-07 · 能力可用性：硬编码布尔 → 带 owner 的三态探测

`neurova/api/endpoints/computer.py:534` 把 `vision_available` 写成常量 `False`；OS 级授权是否到位（UIA 可用性、`NEUROVA_ALLOW_GLOBAL_INPUT=1` 这条全局输入开关、沙箱池是否配置）**没有任何一等状态**。

对照侧的形态可作可行性证据：一个 typed 探测结果携带 `{platform, grantOwner, accessibility: granted|stale|denied, screenRecording: unknown|granted|denied}`，另有"状态取不到"的独立类型、"改授权需重启"的显式返回、以及按需探测开关。**其中 `stale` 与 `denied` 分开是关键**：授权失效时"重新授权"无效、必须重启宿主进程；若只报 denied，会把用户导向错误的自救动作——这类状态在你们 Windows 侧（UIA/沙箱池）同样存在。

**要做的事**：把 `vision_available` 之类常量升成一次真探测的结果，带 owner 与 stale/需重启语义，并把 fail-closed 的语义绑到该结果而不是绑到字面量。
**🔒 D-3**：探测范围先只覆盖 Windows 桌面，还是含浏览器/camofox？探测是否懒执行（每次打端点都探一次，还是缓存 + 失效）？—— 这两个决定成本和误报面，须人定。

---

## 9. T-08 · 浏览器无稳定动作句柄，每步付一次全页快照

**现状**：模型侧只有 `role + name`。camofox 后端**内部其实已经算出 ref**（把 aria 快照文本 `- role 'name' [eN]` 正则解回 ref，再 `_click_ref`，`camofox_server_backend.py:349-381`、`:644-663`），但**不把 ref 交给模型**——于是每次 `*_role` 调用都**重新快照 + 重新解析**（`:358`）。桌面侧与之对照：`runtime_id` 是稳定句柄（`desktop_uia.py:537-541`），`index` 只是每轮重编号的位置（`:95-99`）。

**价值**：把已有的 ref 透出为一等寻址，可同时省掉"每步一次全页快照"的延迟与 token；`role+name` 保留为跨快照兜底。

**为什么风险高**：这是在改 **provider 可见的工具契约**（参数形状变化 = 模型看到的调用方式变化），且与 T-03 的新鲜度语义强耦合——**句柄只有在"什么时候失效"有明确答案之后才有意义**，所以 T-08 必须在 T-03 之后。

**🔒 D-1**：ref 的生命周期绑 generation（同快照内有效）还是会话（跨快照尽量稳定）？
**🔒 D-2**：ref 是否暴露 selector/xpath 作为回退（暴露 = 给模型一条绕过快照事实的路，与桌面侧"快照事实驱动，不猜 CSS 选择器"的既有取向冲突）？

**判据草案**：`test_refAddressingAvoidsReSnapshot`（用真链路计数：N 次动作应只触发 ⌈N/失效次数⌋ 次快照）；`test_refSurvivesOnlyWithinItsGeneration`；`test_roleNameFallbackStillWorks`。

---

## 10. T-09 · 截图从不进模型上下文

**现状（亲验）**：`tool_executor.py:4831` 在归一化结果时 `pop("image_base64")`；`_emit_computer_event`（`:4855-4900`）只把 base64 推给 WS 分屏给人看；`vision_available` 常量 `False`。**即：agent 在电脑操控域是结构性盲的，只能靠 accessibility/SOM 文本感知。**

**这条的乐观之处**：地基已经有了。`chat_pipeline.py:1548-1568` 有一条成熟且**踩过坑**的请求级图片通道——`normalize_image_for_llm` 降采样挡 413，且 base64 **只挂当轮请求、绝不入历史**（注释记着 2026-09-09 串台事故：历史里遗留的"请结合图片回答"把弱模型带偏去文件系统找图）。所以这不是"新建视觉通路"，是"把工具结果的图接到已有通道"。

**这条的麻烦之处**：真接入后，历史里会留下"我看过一张图"的痕迹而无图可依——**正是那次事故的同型问题**。对照侧的答案是 imageRef 间接引用（带 authority 标注的引用而非字节）+ 完整性元数据 + "模型可见内容保护"标记，值得一并设计。

**改感知模式属产品决策，不是缺陷修复。🔒 D-4**：是否启用？与现有 accessibility 阶梯是并列（模型自选）还是分层兜底（UIA 失败才给图）？成本闸门在哪（每步给图 vs 仅在 refusal 后给图）？

---

## 11. 附录 A：复核命令（对准当前 `HEAD`，别信本文行号）

```bash
# T-01 占位面与契约
grep -rn '"message": .*placeholder' neurova/api/endpoints/ ; grep -n "class SmartClickRequest" -A 4 neurova/api/endpoints/computer.py
grep -rn "smartClick\|visualParse" src/ NeurUI/src/api/modules/computer.ts
# T-02 三表
grep -n "COMPUTER_USE_TOOLS\s*=\|_COMPUTER_TOOL_PARAM_KEYS\s*=\|_builtin_dispatch\s*=" neurova/tool_executor.py
# T-03 新鲜度推进点（应为 1 vs 5）
grep -n '"generation"\] *+= *1' neurova/computer_use/browser_manager.py neurova/computer_use/camofox_server_backend.py
# T-04 只写不读
grep -rn "max_marks" neurova/ ; grep -n "_trim_snapshot_tree" -A 26 neurova/computer_use/browser_manager.py
# T-05 单槽实例态
grep -n "_last_som_id2xy" neurova/tool_executor.py ; grep -rn "self\._last_\|self\._current_" neurova/tool_executor.py
# T-06 截断点
grep -n "8000\|\[:8000\]\|truncat" neurova/tool_executor.py | sed -n '1,20p'
# T-07/T-09 感知与可用性
grep -rn "vision_available" neurova/ ; grep -n 'pop("image_base64")\|_emit_computer_event' neurova/tool_executor.py
```

## 12. 附录 B：交付自检清单（每条工单提 PR 前逐项打勾）

- [ ] 红灯先交、且附"确实红"的输出原文；绿灯在其后
- [ ] 用 `.venv/Scripts/python.exe -m pytest`，按目录分块，未跑全量
- [ ] `tests/unit/computer_use` + `tests/unit/api` 合入前后**失败名集合逐条比对**（docs 守卫族基线本就红，不算你的）
- [ ] 若动了工具名/参数/端点：`grep` 扫到全部消费方（含 `NeurUI/src`，i18n 是 11 份）
- [ ] 若删了任何符号或收口了第二份定义：登记 `scripts/ci/toolLoopDeadlines.txt`，判据类与阈值可达性两轴**由机器算**，人不填
- [ ] 转绿后才可进 `scripts/ci/protected_tests.txt`
- [ ] 活体验证证据（命令 + 输出原文）在 commit 正文；不以单测全绿替代
- [ ] 净 LOC 去向写在 commit 正文；超出本工单估计数值须说明差在哪
- [ ] `git commit --only -- <显式路径>`，未用 `git add -A`
- [ ] 遇到 🔒 决策点：已停下提问，未自行拍板

---

## 13. 决策追加（2026-09-30 拍板，本轮未动工）

**D-5 · `visual-parse` 退役**（端点 + 请求模型 + 前端 `visualParse` 封装 + 11 份 locale 同批改）。
理由不是"没人调用"，而是它与 `computer_som_snapshot` 是**同一能力的第二条入口**；
且检测器的注入缝已在 `som.mark_screenshot(png, detector=...)` 里留好
（`som.default_detector` 注释明写"真实检测器就绪后以 `detector=` 替换，上层零改动"），
退役不丢任何将来接真检测器的路径。净 LOC 为负。

**D-6 · `smart-click` 立项为新能力**（自然语言目标 → 元素），不视为"补断线"。
拆两片，顺序不可颠倒：

- **T-10 语义解析器（依赖 T-08 的 ref）**：只在**当前快照事实**里解析，不猜选择器——
  与 `browser_dom_snapshot` 的既有纪律同向。第一片**不需要新模型**：
  对 role+name 候选做归一化匹配 → 唯一命中直接产出**动作**；多命中回
  `ambiguous` + 候选 ref 列表（不是回错的那一个）。歧义率是真数据：
  MDN 一页 618 条可交互行去重后 429，**56% 卷入重名**。
- **T-11 接通与撤谎**：实现落地后撤掉 `smart-click` 的 501 拒绝，
  并把前端 `computer.ts` 的载荷从 `{agent_id,x,y}` 改为 `{target}`（现 422 缺 `target`）。
  **在此之前 §2.6 的"422 未消除"仍成立**，不要提前改前端掩盖它。

依赖关系：T-08（ref 一等寻址）→ T-10 → T-11。理由：`get_by_role` 遇重名是
`strict mode violation` 硬失败，没有 ref 的语义解析只能停在"找到候选但动不了"。

### 13.1 D-6 第一片活体证据（2026-09-30，真 Chromium + 真端点处理函数）

取证法说明（口径要摆正）：9527 上那个后端是本轮提交**之前**起的进程，打它证明不了新代码；
重启他人实例我不做。故在进程内驱动真 Chromium、经生产管理器 `get_computer_use_manager()`
调真处理函数 `computer.smart_click()`——浏览器、快照、点击链都是真的，
**缺的只是 socket 层**，这一区分如实记下。

fixture：3 个同名 `删除` 按钮 + `提交订单` + `唯一链接`。

```
navigate success=True url=file:///…
目标='唯一链接'  -> 200 {'success': True, 'matched': {'role': 'link', 'name': '唯一链接'}, 'matchedBy': 'exact', 'generation': 2}
目标='订单'      -> 200 {'success': True, 'matched': {'role': 'button', 'name': '提交订单'}, 'matchedBy': 'partial', 'generation': 3}
目标='删除'      -> 409 目标「删除」在当前快照里命中 3 个可交互元素（button「删除」×3），不代为挑选——请给更具体的目标…
目标='报名按钮'  -> 404 目标「报名按钮」在当前快照事实里无可交互命中（先 browser_navigate 打开页面）
```

两点副产品证据：`订单` 那次 `generation` 从 2 进到 3，说明唯一命中确实走到了
"动作使快照事实失效"那条链（T-03 的成果在本单被反向用到）；歧义时 409 的 detail
**逐条列出候选**而不是回一个数字，模型可据此换目标或换工具。

**未覆盖分支（不以绿冒充）**：`502`（快照取不到时报"未执行"）这次**没被观测到**——
关掉活动 tab 后 `browser_dom_snapshot()` 仍回 `success=True` 且正文为空，于是落到了 404。
这暴露的是另一个问题：**空快照被当成成功快照**，与 T-06b 修掉的"静默裁剪"同族
（快照面把"没拿到事实"和"页面确实没有可交互元素"混成同一形态）。登记为 **T-12**：
`dom_snapshot` 需区分"空树"与"取不到"，取不到时不得回 `success=True`。

### 13.2 T-03 / T-05 活体补验（2026-09-30，真 Chromium / 真宿主桌面）

**T-03 通过**（fixture：本地页一个会往列表追加行的按钮）：

```
首次快照 generation=2
用当前 generation 点击 -> success=True
用同一个旧 generation 再点击 -> success=False
   err=target generation 过期（当前 3，传入 2）——页面已变化，快照事实失效，请重新 dom_snapshot
```

改 DOM 的 role 动作确实推进了 generation（2 到 3），且过期复点被拒、消息可分诊。
这正是 T-03 修的分叉（修前 Playwright 侧校验而不推进，同一条序列会照样通过）。

**T-05（本轮）**：两会话各做一次真 SOM 快照并各点自己编号，两次都得到同一坐标
（60 个 mark、id 12614、center 1768,1007）。原因是**同一宿主桌面产出同一张截图**，
两会话的编号表本来就相同——属**非判别性实验**，不能算作通过。
⚠️ 该轮另有一句是错的：探针报"会话注入点 None"，是我去找了已退役的 `set_session_id`，
真正的写入口是 `turn_context.set_turn_identity(user_input, session_id, user_id)`
（`neurova/core/turn_context.py:279`）。判别性活体已由 §13.3 补齐，本段留作失败记录。

### 13.3 T-05 判别性活体 + T-12 触发态复现尝试（2026-09-30，真宿主桌面 / 真 Chromium）

取证口径：全程用**生产检测器** `som.mark_screenshot` 处理**真实截屏字节**，经生产处理函数
`ToolExecutor._execute_computer_som_snapshot` / `_execute_computer_click_mark` 走完整链路。
只换掉两处外部依赖：① 截屏来源按当前会话返回不同的真实 PNG 字节；② 像素点击
`actions.click_screenshot_point` 只记录实际解算出的 `(cx, cy)`、**绝不真点鼠标**。
会话身份经 `set_turn_identity(..., session_id=...)` 注入，与生产同一条路径。

**① 自然取样（A=真实桌面截屏，B=同一桌面上编号标注已 Overlay 的真实位图）**：

```
真实检测器读数：A 标记 60 / B 标记 60；id 交集 1，其中同 id 不同坐标 0，仅 A 有 58
取仅属会话 A 的编号 79493，期望坐标 (1713, 941)
  [生产形态·会话隔离] A 点 79493 -> 实发坐标 (1713, 941) | refusal=None        → ✓ 解到自己那张图
  [变异对照·单槽覆盖] A 点 79493 -> 实发坐标 None        | refusal='stale_generation'
                      err='SOM 编号 79493 不在最近快照中（已过期或未快照）'    → ✗ 未解到 A 的坐标
```

判别性来自**变异对照**：把会话键改成恒定值（= 修复前的单槽覆盖语义），同一条断言立刻转红，
且拒绝路径上没有发出任何点击。另一轮自然取样撞到 1 个"同 id 不同坐标"。

**② 确定性逼出最坏形态（B = 同一张真实截屏整体平移 3px 后的真实位图）**：

```
A 真实截屏 379722B / B 同屏平移3px 379911B；标记 60/60，同 id 不同坐标 24 个
取撞号 50279：A 图上 (557, 318)，B 图上 (554, 315)
  [生产形态·按会话存] A 实发 (557, 318) | B 实发 (554, 315) → ✓ 各解各的坐标，隔离生效
  [变异对照·单槽覆盖] A 实发 (554, 315) | B 实发 (554, 315) → ✗ 跨会话误寻址发生
                      （A 拿到的 (554, 315) 属于 B 那张图 = 点错元素）
```

SOM 编号按 `(中心//8, label)` 散列（`som.stable_id`，`_GRID=8`），平移 1–7 像素时多数标记
仍落在同一量化格 ⇒ 撞号是设计使然而非巧合；该前提由 `tests/unit/computer_use/test_som.py::test_grid_quantization_nearby_same` 钉住。
这条把 T-05 最怕的形态**在活体上演示了出来**：修复前，会话 A 会按别人那张图的坐标点击。
如实限定：B 的画面是"真实像素 + 构造位移"，位移本身是为逼出撞号造的条件，不是宿主上自然发生的第二块屏。

**T-12 触发态复现尝试（真 Chromium，5 个候选态逐个记实际读数）**：

```
[正常页面 example.com]        success=True  dataLen=1075
[about:blank]                 直读 aria_snapshot -> '- document'   → dom_snapshot success=True dataLen=10（非空成功，正确）
[data:text/html,<html></html>] 直读 aria_snapshot -> '- document'  → 同上
[活动 tab 已关闭后]            success=False err='Locator.aria_snapshot: Target page, context or browser has been closed'
[无活动 tab 时]                success=False err='Not initialized'
```

**结论：本轮仍未复现"success=True + 空正文"这一原始形态**。§13.1 那次读数出自
经 `computer.smart_click()` 的更外层路径，而这里直取 `PlaywrightBackend.dom_snapshot`
的关闭态得到的是 Playwright 自带错误（本就已经诚实）。产出侧的空树拒绝仍保留：
它是"没拿到事实"与"页面确实没有可交互元素"唯一可分诊的落点，且 `about:blank` 类
**非空成功**未被误判成故障（反向对照在 `test_empty_snapshot_not_success.py` 里）。
camofox 侧的 `raw_snapshot` 空值需真容器才能活体，本轮仍以两后端 parity 的单元判据覆盖——**这是 T-12 剩下的活体缺口**。

**该缺口已按可得范围闭合（同轮，真 HTTP 传输 + 契约桩容器）**：本机没有 camofox 服务
（`:9377` 实测连接超时），所以不能拿"真容器"活体；改起一个**按本仓既有 camofox 契约**
（`GET /health`、`POST /tabs`、`GET /tabs/<id>/snapshot`）的本地 HTTP 桩，用生产后端的
**真 httpx socket** 驱动完整链路——真传输、真 JSON 解析、真 tab 注册，只有对端是桩：

```
契约桩起在 http://127.0.0.1:59221
initialize()（真 GET /health）-> True
navigate（真 POST /tabs）-> success=True target 注册=['tab_62ea4c70'] generation=1
[正对照 非空 snapshot] success=True data.snapshot 长度=159
[空 snapshot] success=False err='snapshot-empty: aria 快照为空，未取得任何页面事实（…）——请先 browser_navigate'
判定：✓ camofox 侧空正文在产出侧即被点名拒绝
[空 snapshot 后继续动作] success=False err='snapshot-empty: …'   ← 拒绝路径上不再按旧事实动作
```

**仍不具备的那半**：真实容器的字段/错误形态未被证明（装它需要用户授权全局 npm 包）。
T-12 的口径因此改为"**两后端产出侧语义已在真传输上证实；真容器行为待授权后补**"。

顺带量到 **T-07（🔒 D-3）的现场证据**——"能力可用"今天是一个只看环境变量、从不探测的布尔：

```
已按 app.py 同法加载 .env
NEUROVA_CAMOFOX_URL = 'http://localhost:9377'
:9377 实测：连接失败：TimeoutError: timed out
manager._camofox_enabled = True        ← 只看变量在不在，不看服务在不在
manager._backends 键 = ['playwright']
_resolve_backend(None) = 'playwright'  camofox_active()=False
```

今天它没造成故障，**只因 playwright 恰好装着**：`_resolve_backend`（`browser_manager.py:1163`）
的次序是 playwright > camofox > scrapling，camofox 永不被选中。一旦某部署缺 playwright，
这个"声称可用"的布尔就会把选择推到 camofox，再进 `initialize()` 的 supervisor 拉起分支——
`camofox_supervisor.py:73` 的 `NEUROVA_CAMOFOX_AUTOSTART` **默认为 True**，于是会去起一个第三方服务。
这条链正是 D-3 要的"带 owner 的三态探测"要拦住的东西（可用 / 已配置但不可达 / 未配置），
本轮只登记读数、不动实现；`initialize()` 我也刻意没调用，原因同上（会真去拉服务）。

**502 分支已可达（同轮补测，真 Chromium + 真端点处理函数）**：§13.1 记的"502 没被观测到"
在 T-12 落地后被补上了——关掉活动 tab 让快照真的取不到：

```
navigate -> success=True url=file:///…
  [正对照] 目标='提交订单' -> 200 {'success': True, 'matched': {'role': 'button', …}, 'generation': 2}
  现有 tab 读数：[{'target_id': 'tab_cf6b9f6e', 'generation': 3, …, 'active': True}]
  关闭 tab tab_cf6b9f6e -> success=True
  [关全部 tab 后] 目标='唯一链接' -> 502 无法取得页面快照事实，语义点击未执行：Not initialized
```

于是量出**同根因的第二批出口**（教义第 5 条）：502 本身诚实，但 detail 里给模型的原因是
内部英文裸串 `Not initialized`——既不点名"没 tab"还是"后端没起"，也不给下一步动作。
散落面比预想大（红灯里的 AST 判据一次点出 14 + 4 处）：

| 落点 | 处数 | 原形态 |
|---|---|---|
| PlaywrightBackend 各读/动作侧 `if not self._page` | 11 | `RuntimeError("Not initialized")` |
| PlaywrightBackend `open_target` 无 context | 1 | 同上 |
| ScraplingBackend `navigate` 无 fetcher | 1 | 同上 |
| PlaywrightBackend generation 校验无 tab | 1 | `"无活动浏览器 tab"`（有中文无动作） |
| camofox `_check_active_generation` / `_resolve_tab_id` | 2 | 同上 |
| camofox `_request` / `screenshot` | 2 | `"CamofoxServerBackend not initialized"`、`"not initialized"` |

三处三种措辞且两处把类名吐给模型，正是双源未收口。**登记并落地为 T-13**：
单源两个带 marker 的文案 `NO_ACTIVE_TAB_ERROR`（`no-active-tab`）与
`BROWSER_NOT_STARTED_ERROR`（`browser-not-started`），两后端共用；判据
`tests/unit/computer_use/test_unavailable_facts_are_triageable.py`（7 例：读侧、动作侧、
generation 校验、两个状态必须可区分、camofox **整句相等**的 parity、AST 反证英文裸串不得回潮）。
红灯实证（只加常量、未接线时）7 例全红，其中 AST 那条直接列出 13 个行号；接线后 7 例全绿。
`tests/unit/computer_use` 块 480 passed / 2 skipped（= 改前 473 + 新增 7）。
措辞收口后的 502 detail：`… 语义点击未执行：no-active-tab: 无活动浏览器 tab，未取得页面事实——请先 browser_navigate 打开页面（或 browser_open_target 新开 tab）`。

**manager 层另两处英文抛出未动**（`browser_manager.py:1187/1192`
`Browser backend not available` / `Failed to initialize backend`）：那属"能力可用性"口径，
正是被 🔒 D-3 锁住的 T-07（带 owner 的三态探测）要统一承载的面，本轮不越权先改一半。

---

## 14. T-14 · 一族常驻红测试断言的是从未实现的设计（🔒 D-7，本轮量完未处置）

### 触发：补 T-05/T-12 活体时顺手跑的邻域回归

`tests/integration/` 的浏览器块出红，为判"是不是我改的"逐条对过活代码后发现：**这族红的根因
与本轮无关，而是同一份从未落地（或已退役）的设计留下的 26 例常驻红**。全集实测：

```
25 failed, 4 passed in 2.00s（另 1 例同族后补，见下）
  tests/integration/test_browser_automation.py            2 例
  tests/integration/test_browser_manager_integration.py   5 例
  tests/integration/test_computer_use_browser_integration.py  14 例
  tests/integration/test_scrapling_spider.py              4 例
  tests/integration/test_computer_use_integration.py      1 例 ← D-5 复核时新补，见下 ⑤
```

### 判据（逐条问活代码，不问测试的意图）

```
BrowserManager.__init__ 形参 = ['self', 'config']  → 有无 config_path：False
BrowserManager 有无 _backend_configs：False
BrowserManager 有无 _compress_snapshot：False
browser_manager 模块有无 HAS_SCRAPELY（测试 patch 的名）：False
browser_manager 模块有无 HAS_SCRAPLING（真实名）：True
ScraplingSpiderTool 有无 default_concurrency/obey_robots：False/False
run_spider 源码里是否读取 concurrency：False；domain_delay：False；obey_robots：False
_resolve_backend 形参名 = ['self', 'preferred']   ← 测试把它当 URL 路由器用
```

三条独立子族，同一根因（**测试照一份不存在的设计写**）：

1. **YAML 后端路由**：`BrowserManager(config_path=…)`、`_backend_configs`、
   `_resolve_backend("https://…")` 按 URL pattern 选后端——三项在活代码里都没有
   （`_resolve_backend` 收的是**后端名**，`_load_config` 只看 `HAS_*` 与环境变量）。此族 **17 例**
   （`test_browser_manager_integration` 4 + `test_computer_use_browser_integration` 13）。
2. **快照压缩**：`_compress_snapshot` / `test_browser_snapshot_returns_compressed_tree` 断言的是
   头部压缩那套；该面已由 `foldSnapshotTree` 单源取代（T-06），属**退役未撤测**。**2 例**。
3. **爬虫工具**：`run_spider` 从不读 `concurrency`/`domain_delay`/`obey_robots` ⇒ `create_spider(**kwargs)`
   是**只写不读的幻影旋钮**（与 T-04 同族），其中 `obey_robots` 从未生效意味着抓取默认**不受 robots.txt
   约束**——这条是合规面，不是测试面。另 `@patch('…HAS_SCRAPELY')` patch 一个不存在的名字，
   那 2 例从未跑到断言就先 AttributeError，即**这文件从写下起就没绿过**。**4 例**。
4. **零断言的 print 脚本混在测试根里**：`test_browser_automation.py` 两个"用例"通篇 `print`、
   没有一条断言（`test_routing_logic` 只把期望与实际打印出来对比，不判失败），且是 `async def`
   而未标 `pytest.mark.asyncio`——在 `asyncio: mode=Mode.STRICT` 下直接判红。
   按 `AGENTS.md` §4"临时验证脚本即用即删，不留 `tests/`"，这 2 例本不该存在。**2 例**。
   合计 17 + 2 + 4 + 2 + 1 = 26，与实测数一致。
   ⚠️ 本单初版把它记成"19 + 2 + 4 + 2 = 25"——那是**我自己加的错**（式子本身就等于 27），
   ① 的 19 是把 ② 的两例从 25 里减了两遍。登记台账里的数必须能被复算，这种错比漏报更坏。
5. **退役面残名（D-5 复核时补进台账）**：`test_computer_use_integration.py` 也是同类——
   通篇 `print` 不断言（schema 取不到只打一行 `✗ …: schema 缺失` 就完事），
   且候选清单里还列着 `computer_visual_parse`（D-5 已退役，生产码现零命中，
   复算：`grep -rnE "visual_parse|visualParse|VisualParse" neurova/ src/ NeurUI/src` → 0；
   ⚠️ 复验时**必须带 `-E`**：不带时竖线是字面量，那条命令会"零命中"得毫无意义）。
   所以它既属"零断言脚本混在测试根"，又带一个退役残名。
   ⚠️ 别把它和 `tests/unit/tools/test_capability_graph_phase3.py` 混为一谈：那份是
   `xfail(strict=False)` **显式声明"API 未交付的先写规格验收面"**，reason 里点名了
   全历史 `-S` 检索零命中与台账章节——那是诚实的挂起态，不是常驻红，也不该被"修绿"。
   两者的区别就是本单一直在说的：失败要么以诚实形态暴露，要么显式登记为未交付，
   不可以"看起来在跑"冒充有守卫。

### 为什么它今天还没炸

CI 不跑这族文件：`.cnb.yml:162` 的被测集是 `grep -v '^#' scripts/ci/protected_tests.txt`
（现 **346 个条目**，别拿 `wc -l` 的 1315 当条数——那含注释行）逐行拼出来的，
而这五个文件名在该清单里**零命中**。于是红只在本地全量出现——
但它每次都要求人肉证明"不是我改的"（本轮就付了这笔成本，见提交说明里的因果排除段）。

### 🔒 D-7 要拍的板（不可逆点在两侧）

- **甲 · 退役**：删掉或重写为活契约（约 −260 行）。代价：丢掉这份设计意图的记录，
  且"YAML 路由"若将来要做，得重写判据。
- **乙 · 补契约**：实现 URL-pattern 路由与爬虫旋钮语义（约 +400 行，含 `obey_robots` 真生效）。
  代价：改变抓取行为（robots 一旦生效，现有爬虫任务的取数面会收窄），属产品口径。
- 我的倾向：**②③按甲处理**（压缩面已被 fold 取代，爬虫旋钮要么真生效要么删掉，不留只写不读），
  **①按乙另立单**——YAML 路由与 T-07 的"带 owner 的三态探测"是同一张能力表，
  分开做会造出第二份事实源（教义第 6 条）。但**这句话要你来说**。

---

## 15. T-15 · 子进程文本不落编码 = 机器码页决定成败（本轮已落地第一处 + 棘轮）

### 病灶与它的真实形状

`subprocess.run(..., text=True)` 不声明 `encoding` 时按 `locale.getpreferredencoding()` 解码——
中文 Windows 上是 **cp936/GBK**。本仓有 173 条 UTF-8 中文入库路径
（现场复算：`git -c core.quotepath=false ls-files` 共 5064 条，含非 ASCII 者 173），
GBK 解不动。而**真正的坑不是解码失败本身**，是失败之后的形态：`text=True` 的读取发生在
子线程，线程里的 `UnicodeDecodeError` 被吞，主线程只拿到 `proc.stdout is None`：

```
AttributeError: 'NoneType' object has no attribute 'split'
PytestUnhandledThreadExceptionWarning: Exception in thread Thread-2 (_readerthread)
UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 60785: illegal multibyte sequence
```

traceback 指向"这行在切字符串"，与根因毫无关系——顺着它修只会去给 `.split` 加判空
（正是修复教义第 1 条禁的 consumer-only guard）。

### 它造成的具体损失

`scripts/scan_docs_refs.py` 是文档台账的**事实源**，它一挂，两道守卫整族红：
本机改前 **13 FAILED + 6 ERROR**，改后 **30 passed**。守卫的作用是拦红，
而假红的代价是训练人去忽略红——比没有守卫更糟。

### 修法（不是"加个 encoding"）

`trackedFiles()` 改为：按**字节**取、在**主线程**显式解码、并检查 `returncode`；
分隔用 `ls-files -z`（git 的机器可读 NUL 分隔，顺带免疫文件名里带换行）。
解码用 `surrogateescape` 而非 `replace`：个别非 UTF-8 文件名要能原样回流去比对路径，
替换成 U+FFFD 会让台账把它判成"路径不存在"——那是把故障伪装成结论。
失败要么不发生，要么以"git 取不到清单（rc=…）"这个真实形态发生。

### 全族量级与本轮的边界

AST 数（不按子串，避免注释里的 `text=True` 误判）：**109 处 / 59 个文件**，其中生产码 12 处——
`neurova/computer_use/camofox_supervisor.py` 3、`neurova/core/env_check.py` 2、
`neurova/image_pipeline/docker_builder.py` 6、`neurova/sandbox/exec_sandbox.py` 1。
一次改 109 处不在本单范围（且 `netstat` 这类外来命令的输出码页与 git 不同，得分别定策），
所以本轮做的是**拦住增量**：判据（`tests/unit/core/test_subprocess_encoding_discipline.py`）——

- **跨机器恒定的那一档是静态的**：按 AST 数落点（全仓棘轮 + `neurova/` 零基线档）。
  ⚠️ 本单初版把行为判据写成"毒 `locale.getpreferredencoding` 成 ascii，Linux 上也成立"，
  **那是错的**：`text=True` 的默认编码在 `io.TextIOWrapper` 的 C 层决定，Python 层
  monkeypatch 那个函数影响不到它（实测：改成 `"ascii"` 后，GBK 字节照样被按 cp936 解开）。
  行为判据因此只在"本机码页 ≠ 生产者码页"时才红——它是本机现场证据，不是跨机器守卫；
- **要跨机器咬住解码分支，喂 `0xFF`**：它在 utf-8、cp936/GBK、ascii 下都是非法起始字节
  （latin-1 例外，本机与 CI 都不是）。实测本机：`b"\xff\xfe"` → `UnicodeDecodeError` 且
  `stdout is None`；UTF-8 中文在这台 GBK 机器上同样 `None`。该写法落在
  `tests/unit/core/test_proc_text.py` 与 `tests/unit/sandbox/test_exec_output_decoding.py`；
- **正反对照**：注入一条必须被数到（判据不空转）、声明了 `encoding` 的不被数到
  （不把 `text=True` 一棍子打死）。

**生产码 12 处已同批清掉**（建 `neurova.core.proc_text.runText/decodeChild` 单源入口后接入）：
`image_pipeline/docker_builder.py` 6、`computer_use/camofox_supervisor.py` 3、
`core/env_check.py` 2、`sandbox/exec_sandbox.py` 1——`neurova/` 现处于**零基线档**，
再加一处即红。同批又清掉**读 git 输出的守卫与其测试** 18 处
（`test_protected_subset_registration_history` 6、`test_npc_runtime_budget` 5、
`test_npc_script_interpreter_reachability` 7；前者原先 3 例 `AttributeError:
'NoneType' object has no attribute 'splitlines'` 就是这个根因，现已 7 passed）。
棘轮基线随之 **109 → 79**（`scripts/` 21、`tests/` 46、其余在 deploy/data/docs）。

### 同族的另一侧：写控制台也按码页走（本批一并撞出）

把读侧修好后，`tests/unit/ci` 里 1 例反而新红：子进程正常输出 UTF-8 了，
**测试自己**用 `text=True` 不带编码去读，拿到 `stdout is None`——失败被顶高了一层，
恰好证明读侧的修法是对的。同轮还量出写侧的独立形态：`scripts/ci/npc_runtime_budget.py`
在没有平台下发预算时会打 `⚠️`，而**中文 Windows 的 cp936 编不出这个字形**，
`print` 直接 `UnicodeEncodeError` 把门禁自己打死（Linux CI 永远看不见）：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0' in position 69
```

按同仓既有先例（`scripts/ci_static_gate.py:37` 的那两行）给 `scripts/ci/` 下
**9 个**会打非 GBK 字形的入口脚本补了 `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")`。
取舍：9 处各写两行而不是抽一个共享模块——这些脚本是被 CI 逐条起进程跑的独立入口，
跨目录 import 反而脆（`sys.path[0]` 是脚本自己所在目录，不是仓根）。

**仍红的 7 例已定性、不属编码族**：全部是"在剥离环境变量的情况下起 node"——
本机 `node -e "console.log('hi')"` 正常，但门禁测试以最小 env 起 node 时
node 自己在 `InitializeOncePerProcess` 里断言失败：

```
#  Assertion failed: ncrypto::CSPRNG(nullptr, 0)   at src\node.cc:1224
```

即"双解释器同读数"这条判据在 Windows 上无法以最小 env 验证，属 node/环境层，
留作后续单独诊断（不在本工单集内，未动实现）。

---

## 17. 本批判据此前**没进 CI**（已补 16 条）

`AGENTS.md` §4 写明"CI 的被测子集就是 `scripts/ci/protected_tests.txt`"，清单头也写着维护方式
是"每完成一项，把它的测试文件加进来"。逐条查下来，本工单集从 T-02 到 T-16 写的判据
**一条都不在清单上**——意味着这些守卫只在开发者本机响，合进主线后 CI 并不会跑它们。
这正是本单反复在说的"注册无消费者的模块"形态，只不过消费者本该是 CI。

处置：把本批 16 个判据文件**逐个单跑**确证全绿后补入清单（"只收逐文件单跑确定全绿的"这条
规矩不能破，见 `AGENTS.md` §4）。补入前每个文件单独跑一次的读数（摘要）：

```
绿  test_snapshot_fold_replaces_chop 20 passed      绿  test_snapshot_truncation_honesty 10 passed
绿  test_snapshot_budget_honesty 9 passed           绿  test_empty_snapshot_not_success 10 passed
绿  test_semantic_target_resolution 10 passed       绿  test_som_marks_are_session_scoped 5 passed
绿  test_snapshot_freshness_parity 14 passed        绿  test_target_generation 18 passed
绿  test_camofox_server_backend 37 passed/2 skipped 绿  test_computer_tool_faces_reconcile 6 passed
绿  test_computer_placeholder_honesty 15 passed     绿  test_visual_parse_retirement 8 passed
绿  test_subprocess_encoding_discipline 6 passed    绿  test_proc_text 10 passed
绿  test_exec_output_decoding 3 passed              绿  test_backend_interface_contract 4 passed
```

补入后，钉这份清单自身的三条守卫仍全绿（`test_dev_path_and_runtime_dep_guards`、
`test_ci_parity_guard`、`test_protected_subset_registration_history` 7 passed）——
后者正是拦住"清单被静默删行"的那道，新增方向一并验过。


一处判据上的取舍值得记下：`docker inspect --format` 这类**把输出当数据**的调用，
降级成 U+FFFD 会让解析静默拿到错值，比崩更坏；但入口默认仍是 `replace`，
因为本缺陷的可见形态是 `None`（整条结果丢掉）而不是"个别字符可读性差"。
需要严格性的调用方传 `errors="strict"`——`runText` 支持，本批未强制。

---

## 16. T-16 · 沙箱后端漏实现 `enforced()`（本轮落地，扫荡时抓到的第二条链）

### 怎么撞上的

改完 T-15 的 `exec_sandbox.py` 后跑 `tests/unit/sandbox` 验收，9 例红。逐条看 traceback，
红点不在我改的行上，而在 `code_sandbox.py:198`：

```
选中后端 = AppContainerSandbox | backend_name = appcontainer | 有 enforced 方法 = False
AttributeError: 'AppContainerSandbox' object has no attribute 'enforced'
```

`ExecSandbox` 声明了 `enforced()`（P1-7 诚实化：后端必须自报"是否真落实了声明的隔离"），
而 `AppContainerSandbox` **不继承基类**、靠鸭子类型冒充接口，唯独漏了这一个方法。
本机 `get_exec_sandbox(NETWORK_OFF)` 正正选到它 ⇒ **代码执行工具在装了 AppContainer API 的
Windows 机器上是崩的**；Linux CI 选不到这个后端，所以这条崩链门禁永远看不见。
病形与 T-15 完全一致：**结果由机器决定，守卫只在一台机器上跑**。

### 修法（按教义第 5 条扫荡，不按"修被点名的那一条"）

判据不做成"给 AppContainer 补个测试"——它自动发现所有定义了 `backend_name` 的后端类，
逐个查接口面（`backend_name/available/enforced/execute`）。第一次跑就点到**第二个**漏项：

```
沙箱后端缺接口成员 {'RestrictedTokenSandbox': ('enforced',)}
```

于是两个后端一起补，且各自的 `enforced()` 都只读本模块**已有**的事实，不新造口径：

- `AppContainerSandbox`：`_DLL.load()` 且 `severity ∈ enforced_severities()`；
  `severity` 未指定 ⇒ False（没声称的档位不谎称已落实）。
- `RestrictedTokenSandbox`：`severity ∈ enforced_severities`（该集合是空 frozenset）⇒ **如实 False**。
  它结果里的 `sandbox_enforced=True` 只声称"受限令牌生效"（模块头第 16 行早作了此区分），
  拿它冒充"隔离档位已落实"就是把未知说成事实。

### 连带纠正的一条撒谎文案

`resolveBackend()` 的 `reason` 原先硬编码"平台后端无内核隔离 → 自报 enforced=False"。
补齐契约后 AppContainer 如实回 `True`，那句话就和字段互相矛盾——**是补契约这一步把假话暴露出来的**。
改成跟着值走（`enforced` 为真时另给一句），避免同一状态存在第二份事实源。

### 实测

- 判据：`tests/unit/sandbox/test_backend_interface_contract.py` 4 例（自动发现非空的前提对照、
  全员接口、注入缺方法的后端必须被点出的正对照、`RestrictedToken`/未指定 severity 的诚实 False）；
- 回归：`tests/unit/sandbox` 由 **9 failed → 56 passed**；与 `tests/unit/computer_use` 合跑
  **536 passed / 3 skipped**；
- 活体（本机 Windows，真 AppContainer 内执行）：

```
resolveBackend -> {"backend": "appcontainer", "enforced": true, "severity": "network_off",
                  "reason": "Docker 不可用，平台后端自报已落实该档隔离"}
execute        -> {"stdout": "沙箱活体·订单42\n", "stderr": "", "exit_code": 0,
                  "backend": "appcontainer", "enforced": true, "timed_out": false, "duration_ms": 32.52}
```

改前这条链在 `resolveBackend()` 就抛 AttributeError，压根到不了 execute。





