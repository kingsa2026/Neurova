# 协作域信息架构重排（Collaboration IA Redesign）设计规格

- 日期：2026-09-19
- 状态：实施中（architectural）；§7 两枚全局项经实施期核实已修订，见 §13。
- 范围：NeurUI 前端协作域（`/collaboration/*`）+ 侧栏导航 + 数据适配边界 + 两枚全局项。后端协作端点不改。

## 0. 现状与问题（证据基线，来自代码 + 实时巡检截图）

- 路由重复：`router/index.ts` 中 `collaboration`（基路径，约 L227-231）与 `collaboration/sessions`（约 L237-241）**同指 `@/pages/CollaborationPage.vue`**；基路径为只能手输的孤儿路由。
- 三页共用同一主标题 `t('collab.title')`=「协作管理」，但面包屑各异（协作 / 协作会话 / 协作中心）。
- 数据口径打架：sessions 页「协作历史」统计用 `listSessions().filter(status==='completed')`；`/collaboration/history` 与 `/collaboration/sessions` 返回同一批记录 → 同一数据一处显示 0、一处显示 1。
- 字段错配（前端 `CollabSession.createdAt`/`participants` vs 后端 `created_at`(epoch)/`members`）→ 表格「创建时间」整列为空、详情弹窗成员为空。
- 状态直显英文 `active`（i18n 已有键未用）；标题拼接「活跃 协作管理」。
- 视觉割裂：外层 Glass、内层原生 `a-table/a-modal/a-drawer/a-steps/a-form`（`css-dev-only-do-not-override-*`）；sessions 无副标题、统计卡无图标（hub 有）；页头 CTA 尺寸不一。
- sessions 页「快捷操作」5 按钮与侧栏/hub「功能模块」三处重复。
- 侧栏：进入 `/collaboration/*` 分组默认折叠、无高亮；「协作 12」计数把 `/channels` 混入、缺 `neuron` 链接。
- 全局（基线报告，实施期核实见 §13）：侧栏底部用户胶囊疑似遮挡上方菜单；冷启动首次深链接疑似误跳 `/login`。**注：后一条的水合竞态归因已被证伪**——token 在 store 初始化时同步读自 localStorage，非异步水合。

## 1. 目标 / 非目标 / 验收

目标：协作域收敛为**单一心智模型**——hub 为唯一总览入口，子页各司其职；数据/视觉/导航对齐设计系统与站点其余页。

非目标：不改后端协作端点与写路径；不改其它域页面（除两处全局修复外）；不引入新状态管理。

验收：见 §8。

## 2. 决策（已与用户敲定）

- 骨干：hub 唯一入口；`/collaboration`→`redirect` hub；sessions 专页；**history 并入 sessions 作为状态过滤，history 独立页/路由退役**。
- 深度：**深度玻璃化**（含表格、发起向导、统计卡、详情）。
- 纳入**两枚全局项**（侧栏 footer 遮挡、冷启动鉴权）；实施期核实后：前者已由现有 GlassNav 布局满足（仅待实机确认），后者前提不成立→无需修改（见 §13）。

## 3. 路由 / IA

`router/index.ts`：
- `collaboration`（基）：`component` 改为 `redirect: '/collaboration/hub'`（删重复组件挂载）。
- 保留 `collaboration/hub` = `CollaborationHubPage.vue`（唯一总览）。
- `collaboration/sessions` = 协作会话专页（组件沿用 `CollaborationPage.vue`，语义/标题改「协作会话」；文件可择机更名 `CollaborationSessionsPage.vue`，非必须）。
- **删除** `collaboration/history` 独立页/路由；新增 `collaboration/history` → `redirect: '/collaboration/sessions?view=history'`（保旧书签）。
- 其余子路由不变；`collaboration/neuron` 路由保留，但其侧栏入口维持**顶层 `/neuron` 独立项**（不并入协作分组，见 §4）。
- sessions 支持 `?view=` ∈ {active, history, all}，默认 active；页面顶部状态切换用 `a-segmented` 分段控件。

## 4. 侧栏导航（真源 `config/navigation.ts` + `config/modules.ts`，渲染在 `layouts/MainLayout.vue`）

> **实施期决定（2026-09-19，用户）：**下列四级子分组重排与“neuron 入协作”**本轮不执行**——保持扁平列表；高亮/自动展开已实现；`/neuron` 保持顶层独立项、不计入协作分组（计数维持 10）。以下为原设计意图，仅供后续参考。

- 协作域按功能子节重排（**已收回**）：
  - 总览：协作中心(hub)
  - 编排：协作会话(sessions)、协作模板(templates)、工作流(workflows)、画布(canvas)
  - 协作：项目(projects)、团队(teams)、任务(tasks)
  - 集成：Webhook(webhooks)、会话同步(session-sync)、NEURON(neuron)
- 计数口径：协作分组计数只统计 `/collaboration/*` 项；`/channels` 归其应有分组（渠道/集成域），不再计入协作；`/neuron` 保持顶层独立项也不计入（维持计数=10）。
- 高亮/展开（**已实现**）：`GlassNavGroup` 以 `activePathPrefix` 驱动，路由使当前 `/collaboration/*` 自动展开所属分组并置 `is-active`；覆盖深链接首屏。

## 5. 数据适配边界（根因处一次归一，组件不再各自猜字段）

在 `api/modules/collaboration.ts` 新增导出 `toSession(raw)`（或 `listSessions()` 内统一映射），把后端记录归一为 `CollabSession`：
- `createdAt ← 格式化(created_at)`：epoch 秒 → `YYYY-MM-DD HH:mm`（本地时区）；缺失/非法 → `—`。
- `participants ← members ?? participants ?? []`。
- `status ← raw.status`（原样，UI 侧再 i18n 映射）。
- `name/id/description` 原样。
- sessions 页**只用 `listSessions()`** + 前端按 `status` 过滤出 active/history/all；**停用 `listHistory()`**（history 并入，消除两源打架）；`listHistory` 保留导出但不再被页使用（避免破坏其它引用；如无引用则删除）。
- 详情弹窗读归一后的 `participants`/`createdAt`。

## 6. sessions 页视觉 / 组件（深度玻璃化）

- 新建可复用 `components/GlassTable.vue`：薄封装 `a-table`，统一主题（去 `css-dev-only-do-not-override-*` 观感）、空态、条件分页（数据量 ≤ pageSize 时隐藏分页器）。sessions 表格改用之（后续页可复用）。
- 页头：标题「协作会话」+ 副标题（复用 hub 头样式）；CTA 按钮尺寸与站点一致（`--md`）。
- 统计卡：带图标，复用 hub `statCard` 观感；值取自归一后 sessions（总计 / 活跃 / 历史）。
- 状态列：i18n 化 `Tag`（active→进行中 / completed→已完成 / failed→失败 / paused→已暂停 / archived→已归档）。
- 标题不再字符串拼接「活跃 + 协作管理」；分节用清晰小标题。
- 「发起协作」向导：经核实，站点**无** GlassDrawer/GlassModal 组件，协作域各抽屉（CanvasStore/TriggerManager/Annotation/WorkflowVersions）统一用 `a-drawer` + 全局 `ConfigProvider` Ant 主题（App.vue 按 skin×深浅色注入 radius/color/font）；向导按钮已用 `GlassButton`、模板卡已玻璃化。实机走查确认抽屉/步骤条/表单/详情弹窗均深色玻璃一致、无原生白底割裂（见 §13）。**不再另加定制玻璃壳**（会与全站抽屉惯例不一致，反背离“与 hub/agents 一致”目标）。
- **删除**页内「快捷操作」面板（导航职责归 hub + 侧栏）。

## 7. 两枚全局项（实施期核实后修订，详见 §13）

- 侧栏 footer 遮挡：基线描述为需修。核实发现 GlassNav.vue 已将页脚做成固定不滚的 flex 兄弟项（`margin-top:auto; flex-shrink:0`），菜单区独立 `overflow-y:auto` 且以 `padding-bottom = footer-bleed` 保证末项不被常驻遮挡；“遮挡”实为有意的 scroll-bleed 玻璃折射。**无需改 MainLayout.vue**；仅需实机目测末项不被永久遮挡。
- 冷启动鉴权：基线假设“守卫在水合完成前误判”→**证伪**。`secureStorage.get` 是同步 `localStorage.getItem`；`auth.ts` 在 store 初始化即同步读出 `token`，`isAuthenticated = !!token`；`main.ts` 先 `app.use(pinia)` 后 `app.use(router)`，守卫内 `useAuthStore()` 在 `isAuthenticated` 判断前已同步含水。有效 token 的冷启动深链接不会误跳 `/login`。**无缺陷可修，不改代码**（遵守 Repair Doctrine：不为不存在的 bug 做表面修补）。

## 8. 验收标准

1. 访问 `/collaboration` 落到 hub；`/collaboration/history` 落到 `sessions?view=history`；无空白/重复标题页。
2. sessions 表「创建时间」有值且为本地化时间串；详情成员非空；状态列中文；标题/面包屑/侧栏名三处一致。
3. 进入任一 `/collaboration/*`：侧栏分组自动展开且当前项高亮；协作计数不含 `/channels`；`/neuron` 保持顶层独立项、不计入协作分组（用户 2026-09-19 决策，见 §4）。
4. sessions 无「快捷操作」重复面板；表格/向导/统计卡观感与 hub、agents 一致（同一 Glass 体系）。
5. 侧栏底部用户胶囊不遮挡菜单（`/agents` 与 `/collaboration/*` 均实机目测）；滚动只发生在菜单区、末项滚到底不被页脚常驻遮挡。
6. （原为“冷启动鉴权竞态修复”；经核实该缺陷不存在，本条改为回归项）冷启动首次直链 `/collaboration/sessions`（带有效 token）仍直达、不跳 `/login`（行为保持现状，无需代码变更）。
7. `npm run build`（vue-tsc）0 错误；相关 vitest 全绿。

## 9. 测试策略（TDD，分垂直切片）

- 路由：`vitest` 断言 `/collaboration`→hub、`/collaboration/history`→`sessions?view=history`、sessions 组件解析。
- 导航：`navigation.ts`/`modules.ts` 分组与计数快照；`MainLayout` 高亮/展开随路由变化。
- 适配：`toSession()` 单测（epoch→串、members→participants、缺字段→`—`）。
- 组件：`GlassTable` 渲染/空态/条件分页；sessions 状态 i18n 映射；向导玻璃壳快照。
- 守卫：回归单测（localStorage 有有效 token 时守卫放行深链接、不跳 `/login`）——固化“同步水合”的现有正确行为，非验证新修复。
- 手工：`.venv`/前端 dev 起服务，走查 5 页对齐 + 截图留档。

## 10. 涉及文件

`NeurUI/src/router/index.ts`、`config/navigation.ts`、`config/modules.ts`、`layouts/MainLayout.vue`、`api/modules/collaboration.ts`、`pages/CollaborationPage.vue`(sessions)、`modules/collaboration/CollaborationHubPage.vue`(卡样式复用来源)、新 `components/GlassTable.vue`、`pages/CollaborationHistoryPage.vue`(退役/重定向)、路由守卫所在文件、`i18n/locales/{zh-CN,en-US}.ts`。

## 11. 实施分期（供 writing-plans 拆票）

1. 路由 + 重定向 + 侧栏分组/高亮/计数/neuron（结构性，先行、低风险）。
2. 数据适配边界归一（toSession）+ sessions 停用 listHistory 分叉 + 过滤视图。
3. sessions 深度玻璃化（GlassTable + 统计卡 + 向导 + 去快捷面板 + 状态 i18n + 页头）。
4. 两枚全局项：侧栏 footer 已由 GlassNav 布局满足（实机目测即可）；冷启动鉴权经核实不成立，无代码变更（回归保留）。

## 12. 风险与回退

- 纯前端；后端端点不动 → 回退粒度按分期切片独立可回滚。
- history 退役若触及其它引用：先确认 `listHistory` 调用方，保留导出以降破坏面（无引用则清理）。
- 新增 `GlassTable` 仅承载展示与透传，避免把业务塞进组件（单一职责）。
- 不改鉴权语义；冷启动鉴权竞态经核实不成立（token 同步读取），本 spec 不引入任何守卫时序变更。

## 13. 修订记录（实施期核实）

实施阶段按 systematic-debugging 先查根因再动手，对 §7 两枚全局项与 §6 向导玻璃化作了证据级核实：

- **冷启动鉴权竞态 → 证伪（不修）。** 证据链：
  - `NeurUI/src/utils/security.ts` L239 `secureStorage.get` = 同步 `localStorage.getItem`；
  - `NeurUI/src/stores/auth.ts` L15 `token = ref(secureStorage.get(TOKEN_KEY))` 在 store 初始化同步完成，L27 `isAuthenticated = computed(() => !!token.value)`；
  - `NeurUI/src/main.ts` L42→L43 先装 pinia 后装 router；`NeurUI/src/router/index.ts` L523 守卫内 `useAuthStore()` 触发 setup 时 token 已同步就绪，L525 才读 `isAuthenticated`。
  - 结论：不存在“守卫早于水合”的异步窗口，`await` 无处可加；有效 token 冷启动直链不误跳。原计划的“改守卫水合时序”未执行（无缺陷可修）。
- **侧栏 footer 遮挡 → 已由既有 GlassNav 布局满足（仅待实机目测）。** 证据：`GlassNav.vue` 页脚 surface `margin-top:auto; flex-shrink:0`（L114-117）为固定不滚兄弟项；菜单区 `.nr-glass-nav-items` `flex:1; overflow-y:auto` + `padding-bottom: var(--nr-nav-footer-bleed)`（L103-113）保证末项滚到底不被常驻遮挡。“遮挡”即该文件中有意为之的 scroll-bleed 玻璃折射。原计划“改 MainLayout.vue flex”定位错误，未执行。
- **§4 高亮/自动展开 → 已实现。** `GlassNavGroup.vue` 以 `activePathPrefix` 派生 `anyChildActive`，`watch` 自动展开并持久化、头部置 `is-active`；`MainLayout.vue` L162 对协作分组传 `active-path-prefix="/collaboration/"`。剩余仅 §4 的“协作域四级子分组细化”，属可选视觉收尾，未纳入本轮代码变更。
- **§6 向导玻璃化 → 已由站点惯例 + 全局主题满足（实机走查确认）。** 证据：全站无 GlassDrawer/GlassModal，协作域抽屉统一 `a-drawer` + `App.vue` 的 `ConfigProvider` 主题；浏览器走查 `/collaboration/sessions` 逐项目测——列表页（副标题/3 图标统计卡/活跃历史全部分段器/创建时间有值/状态中文/无快捷面板）、发起向导 4 步抽屉、详情弹窗均深色玻璃一致、无原生白底割裂；截图存 `gui-test-screenshots/collab-0*.png`。未对向导做定制玻璃壳（避免背离全站抽屉惯例）。
- **顺带发现的两项向导缺陷 → 已修（用户“解决顺带发现”）。** 实机走查揭示“缺校验”只是下游症状，真根因是**载荷与后端契约错位**：
  - 后端 `CollaborationStart`（snake_case `template_id`+`participants`+`context`，无 alias、`extra='ignore'`）；前端曾直发 `{templateId,name,description}` → 全被丢弃，会话恒为 "New Collaboration"。修复：`api.startSession` 边界映射为 `template_id` + `context:{name,description}`（测试 `collaboration-start.test.ts`）。
  - 模板列表缺 `toSession` 同类的归一：后端回 `template_id`、无 `type`，而 `CollabTemplate` 要 `id`/`type` → `tpl.id`=undefined → 向导第1步选不中、两卡同时高亮、下一步永远禁用（死路）。修复：新增 `toTemplate()` 并在 `store.fetchTemplates` 统一归一（一处修好所有消费方，含模板页 `openEdit`）；测试 `collaboration-templates.test.ts`。
  - 必填校验：`canProceed` 要求第1步选中模板才能“下一步” + `handleStart` 防御守卫；第3步标签由 `agent.config`（“配置”）改为专用 `collab.basicInfo`（“基本信息”）；`type` 空时不渲染空 tag；提示文案对比度调亮。vue-tsc 0 错、vitest 14 绿、`npm run build` 绿、实机复验单选高亮+下一步解禁+可入第2步。
