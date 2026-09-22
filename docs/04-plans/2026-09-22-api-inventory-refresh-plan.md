# 立项：`api_inventory.md` 重生成（前端 API 清单快照过期）

> 立项日期：2026-09-22
> **状态：已落地（2026-09-22）**——生成器 `scripts/generate_api_inventory.py` + 守卫
> `tests/unit/test_api_inventory_freshness_guard.py` / `tests/unit/test_api_inventory_guard.py`；
> 销账后台账第八节入筛条目 103 → 0。
> 承接单：Issue #112（本立项）；上游：Issue #68 下一层——归档层按「是否影响当下导航」筛选后，入筛的指路条目
> 台账与判据见 `docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md` 第八节；
> 判据单源在 `scripts/scan_docs_refs.py::navigationImpactRefs`。
> 性质：文档事实源重生成（非缺陷修复）——净 LOC 为文档，验收看「逐条可核」
> 关联载体：`docs/09-dev-progress/api_inventory.md`（导航可达：`docs/0-index/README.md:236` 列为领域入口）

---

## 1. 现状（2026-09-22 实测锚点）

`api_inventory.md` 自述生成于 2026-05-14、更新于 2026-06-06，是一份**API 清单**：
标题即「Neurova 前端UI所需API完整清单」，正文逐表列举「模块名称 | 文件路径 | 实现状态」。

它是一篇**专职指路文档**：存在的意义就是把人指向具体模块。因此判定它是否健康的判据
不是「它的陈述是否符合当时的实现」（那是历史留痕），而是**它今天是否把人指对地方**。

实测（对现行代码树取全集后比对声明）：

- 声明的前端 API 模块 **71 个**，其中 **29 个在 `NeurUI/src/api/modules/` 已不存在**：
  `skill.ts`、`marketplace.ts`、`channel.ts`、`channel_config.ts`、`workflows.ts`、
  `files_api.ts`、`benchmark.ts`、`knowledge_api.ts`、`emotion.ts`、`mobile-pairing.ts`、
  `synonym.ts`、`channel_sharing.ts`、`dashboard.ts`、`system.ts`、`group-chat.ts`、
  `knowledge-graph.ts`、`user-groups.ts`、`file-flows.ts`、`tools.ts`、`skill-versions.ts`、
  `knowledge-integration.ts`、`semantic-search.ts`、`enhanced-memory-search.ts`、
  `memory-timeline.ts`、`memory-enhancement.ts`、`audio.ts`、`channel-adapters.ts` 等
  （改名或合并后的对应物为 `synonyms.ts`、`channel-configs.ts`、`files.ts`、
  `knowledge.ts`、`mobile.ts`、`system-logs.ts`、`tool-layers.ts` 一类）。
- 反向缺口更大：`NeurUI/src/api/modules/` 现行 **62 个 `.ts` 模块里 20 个未列出**
  （`cost.ts`、`health.ts`、`knowledge.ts`、`mobile.ts`、`neurflow.ts`、`plans.ts`、
  `rsiGovernance.ts`、`studio.ts`、`text-evolution.ts`、`governance.ts`、
  `metacognition.ts`、`negative-screen.ts`、`agent-package.ts`…）。

结论：**这不是「某几行路径写错」，是整篇级过期**。逐条补路径只能得到一份
「半对半错」的清单——而清单的全部价值在于可信。

## 2. 为什么单独立项

归档层的一般口径是「历史留痕，不就地改写」，本轮筛选特意为指路文档留了例外：
它的失效条目会**实际把人带错**。但「改指」这个动作对整篇级过期**不成立**——
改完 29 条路径，反向缺的 20 条仍在，读者拿到的还是一份会漏模块的清单。

故本项不落在「改路径」，落在**重生成 + 快照纪律**，需要独立排期与人工确认。

## 3. 目标与非目标

**目标**

1. **重生成**：以现行代码树（`NeurUI/src/api/modules/`、`neurova/api/endpoints/`）为唯一
   事实源，取一次全集，产出「模块 ←→ 端点前缀 ←→ 实现状态」三列齐全的清单。
2. **生成方式可复算**：清单由脚本产出而非手写，脚本落 `scripts/`，
   输出与代码树的差集可随时重跑核对（禁止又造一份会漂移的手写表）。
3. **快照纪律**：清单头部写明生成命令与生成日期；超过约定周期未重生成时，
   在头部以**显式文本**标注「快照，可能过期」——不得让读者误当现行事实源。
4. **导航归属确认**：`docs/0-index/README.md:236` 把本篇列为 `09-dev-progress` 领域入口。
   重生成后确认它是否仍应留在导航图上；若其定位改为历史快照，则从领域入口降级为归档。

**非目标**

- 不改归档层的其它条目（`05-reports` / `06-bugfix` / `09-dev-progress` / `11-legacy`
  其余 ~1740 条不构成当下导航问题，继续按台账登记）。
- 不重写 `docs/02-api/API_REFERENCE.md`（那是接口事实源，与本篇是「前端所需」的视角，
  两者职责不同，不合并）。

## 4. 验收判据

1. 清单声明的前端模块与 `NeurUI/src/api/modules/*.ts` **双向差集为空**（可重跑复算）；
2. 声明的端点前缀与 `neurova/api/endpoints/` 实际注册前缀一致；
3. 头部含生成命令与日期；
4. 本条销账后，台账第八节该行改记为「已重生成 + 快照日期」，
   棘轮基线 `tests/unit/archiveNavPointerBaseline.txt` 相应下调。

## 5. 风险与处置

- **重生成会改变大量行**：属预期——清单的价值就是与代码树对齐。审阅按「差集是否为空」看，
  不逐行比对旧文本。
- **端点前缀需运行时确认**：前端所需与后端注册可能不一致，差异项以**显式列表**暴露
  （缺哪个、谁负责），不得用「大致一致」带过。

---

## 6. 落地结果（2026-09-22，Issue #112 销账）

**唯一写者**：`scripts/generate_api_inventory.py`；清单正文由它产出，
生成命令 `python scripts/generate_api_inventory.py --write`。

### 验收判据逐条核对

1. **模块双向差集为空** —— 清单声明 ←→ `NeurUI/src/api/modules/*.ts`，实测双向 0 差异。
   声明侧从清单正文解析（不直接读磁盘），否则该断言会退化成恒真。
2. **端点前缀与后端注册一致** —— 差异**显式登记**而非「大致一致」：前端调用未命中
   后端注册 59 处（逐条给出调用路径与形态：`路径未注册` 45 · `方法不匹配` 14），
   后端已注册无前端消费 20 个一级前缀逐条列出。
   取舍说明：本仓路由由挂载表 + `APIRouter(prefix=...)` + 聚合器 include 三层构成。
   起初试过静态重建路由表，实测比真实表少认 40 余条——**那等于再实现一遍 FastAPI
   路由匹配**，属第二套平行体系且必然逐版漂移，还会把真实端点误报成「未注册」
   （假阳性比漏报更坏：它会训练人忽略这张表）。故后端事实源改取
   `create_app()` 装配后的真实路由表（与 `tests/e2e/test_backend_boot.py` 同一条装配路径）。
3. **头部含生成命令与日期** —— 机器区首两行即命令与快照日期；`SNAPSHOT_MAX_AGE_DAYS`
   到期由守卫点名，逾期不重生成即红。
4. **导航归属** —— 重生成后**仍留在导航图上**，不降级为归档。理由：它现在满足
   「专职指路文档」的健康前提（与代码树一致、可复算、差异显式），不再是过期快照。
   `docs/0-index/README.md` 的链接描述同步为「前端 API 面清单（生成物…）」。
5. **销账** —— 台账第八节入筛条目 103 → 0；棘轮基线
   `tests/unit/archiveNavPointerBaseline.txt` 由 `103` 下调为 `0`（只降不升）。

### 与接口事实源的分工

本清单是**前端视角**（哪个前端模块请求了哪些端点前缀、哪些后端前缀还没有消费方）；
接口本身的事实源仍是 `docs/02-api/API_REFERENCE.md`。两者职责不同，不合并——
立项第 3 节「非目标」已写明，落地时未偏离。

### 守卫分工（同一判据，两条守卫各锁一半）

| 落点 | 作用 |
|------|------|
| `scripts/generate_api_inventory.py` | 清单**唯一事实源**：读代码树取全集，产出机器区；`--write` 落盘 |
| `docs/09-dev-progress/api_inventory.md` | 改为生成物：机器区 + 叙述性说明分区，机器区禁手改 |
| `tests/unit/test_api_inventory_freshness_guard.py` | 锁模块双向差集、前缀表、快照纪律、生成入口幂等与运行时零假阳性 |
| `tests/unit/test_api_inventory_guard.py` | 锁机器区与生成器输出**逐字一致**、两组差异逐条登记、快照不逾期 |

## 7. 重生成暴露的断点（已处置：2026-09-22）

重生成按「逐条可核」执行，把此前只存在于架构评审里的接线断点变成了**可复算读数**。
原计划是「本单只登记、另单处置」；后续在同一线上收口了——因为它们的根因同一处：
**挂载事实有两份**（注册表 + `app.py` 旁路），两份之间没有任何一致性校验。

| 断点 | 修前读数 | 处置 |
|------|------|------|
| `/api`、`/api/evolution`、`/api/rag` | 挂载动作在、路由零条 | `endpoints/__init__.py` 的 `router` / `evolution_router` / `rag_router` 是模块级空 `APIRouter()`，全仓无任何注册语句 → **删除空壳与挂载**（空 router 不是「待接线」，是「不存在却对外可见」） |
| `/api/neuron/neuron/*`、`/api/coordination/coordination/*` | 前缀重复段 | 表内 prefix 与模块自述 `APIRouter(prefix=...)` 各叠一次 → **表内前缀留空、以自述前缀为准**，旁路挂载删除 |
| `/api/v1/budgets`、`/api/v1/cost-rollup` | 运行时零命中 | 旁路挂在 `/api` 下（缺 `v1`），前端 `baseURL=/api/v1` → 必 404 → **并入注册表挂 `/v1`**，旁路副本删除 |

三处的共同修法：**挂载只有一个入口**——`endpoint_modules` 注册表；`app.py` 的旁路
`include_router` 组全部删除。判据（`mountedRouterAudit` / `unmountedEndpointModules`）
单源在同一条装配路径上，常驻守卫
`tests/unit/api/test_route_mount_contract_guard.py` 逐条钉住。

`docs/architecture-model/architecture-findings.md` 第 6.1/6.3 节的既有裁定同批对齐：
6.1 记的「两套注册事实源」与 6.3 记的「前后端前缀契约断裂」在本轮一并收口。
