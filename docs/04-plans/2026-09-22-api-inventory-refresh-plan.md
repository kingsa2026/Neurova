# 立项：`api_inventory.md` 重生成（前端 API 清单快照过期）

> 立项日期：2026-09-22
> **状态：已落地（2026-09-22）**——生成器 `scripts/gen_api_inventory.py` + 守卫
> `tests/unit/test_api_inventory_guard.py`；销账后台账第八节入筛条目 103 → 0。
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

## 6. 落地记录（2026-09-22）

### 交付物

| 落点 | 作用 |
|------|------|
| `scripts/gen_api_inventory.py` | 清单**唯一事实源**：读代码树取全集，产出机器区；`--update` 落盘 |
| `docs/09-dev-progress/api_inventory.md` | 改为生成物：机器区 + 叙述性说明分区，机器区禁手改 |
| `tests/unit/test_api_inventory_guard.py` | 常驻守卫：重算比对 + 5 项反向控制 |

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
原立项第 3 节「非目标」已写明，落地时未偏离。

---

## 7. 重生成暴露的断点：处置记录（2026-09-22 同批）

第 6 节重生成把三处断点从「静态前缀推导」提到了「真实路由表实测」，本章是它们的处置记录。

### 7.1 断点与根因

根因是**同一件事**：注册表把「挂载动作」与「接线完成」当成同一件事。
`register_endpoint_routers` 只要求模块有 `router` 属性就 `include_router`，于是
三类「看起来接了、实际断着」的形态得以长期存活：

| # | 形态 | 实测 |
|---|------|------|
| 1 | 零路由挂载 | `/api/evolution`、`/api/rag` 挂的是模块级空 `APIRouter()`，叶子路由零条 |
| 2 | 前缀叠层 | `/api/coordination` + router 自持 `/coordination` → 实际 `/api/coordination/coordination/*`；`/api/neuron` + `/neuron` → `/api/neuron/neuron/*` |
| 3 | 双源挂载 | `neuron` 的 router 被注册表与 `app.py` 各挂一次；`budget_api` / `cost_rollup_api` 只走 `app.py` 旁路，不在注册表 |

外加一处契约断裂：`cost.ts` 按 `baseURL=/api/v1` 请求 `/api/v1/budgets`、
`/api/v1/cost-rollup`，而后端把两者挂在不带 `v1` 的 `/api` 下 → 必 404，
且调用处 `.catch(() => null)` 把它吞成「存储未就绪」，看板静默空白。

### 7.2 处置（在根因处修，不在报错处兜底）

- **删空壳**：`endpoints/__init__.py` 的顶层 `router`、`evolution_router`、`rag_router`
  三个零路由 `APIRouter()` 全部删除，`app.py` 对应三处 `include_router` 一并删除。
  证据：全仓 grep 这三个名字，除定义与挂载外零消费者，前端零调用方。
- **单一挂载表**：`budget_api` / `cost_rollup_api` 收口进注册表（挂载前缀 `/v1`，
  实际路径 `/api/v1/budgets/*`、`/api/v1/cost-rollup/*`，与前端 baseURL 对齐）；
  `app.py` 的三处旁路 `include_router`（`budget_router` / `cost_rollup_router` /
  `neuron_router`）删除——同一件事不再有两个写入点。
- **去叠层**：`neuron` 挂载前缀 `""`（router 自持 `/neuron`），`coordination_api`
  挂载前缀 `""`（router 自持 `/coordination`），实际路径回到 `/api/neuron/*`、
  `/api/coordination/*`。
- **判据单源**：三类形态的检测写进 `scripts/gen_api_inventory.py`
  （`appMounts()` / `mountProblems()` / `unwiredEndpointRouters()`），
  守卫 `tests/unit/api/test_endpoint_mount_wiring_guard.py` 只做「取数 → 断言 →
  反向控制」，不另写一套解析。

路由表实测：**839 → 830 条**（去 41 条叠层/错前缀，增 32 条归位）。
逐条核过：无一条是「删掉真实端点」，全部是同一批端点的路径归位。

### 7.3 已实现未接线的 router（登记，走棘轮）

六份模块有真实路由但全仓无挂载点。**不许静默遗留**，也不必在本单强接——
逐条理由写在 `tests/unit/endpointWiringBaseline.txt`，守卫双向钉住（新增即红、
修好后未下调亦红）：

- `computer_api` / `cost_api`：唯一调用方是 `NeurUI/src/api/computer.ts`，而它只被
  `NeurUI/src/views/*.tsx` 三份 React 原型引用（Vue 入口从不加载，`package.json`
  无 react 依赖，见 `architecture-findings.md` 第 12 节 u5）。且 `computer_api`
  的鉴权是 `Depends(lambda: "current_user")` 硬编码身份，挂上去等于对匿名开放。
- `phase3_api`：全仓零调用方；它依赖的 `small_brain_router` / `outbox_handler`
  在生产链路另有主线消费方（`agent/model_selector.py`、`agent/turn_coordinator.py`）。
- `migration_api`：零调用方，且底层 7 阶段实现**全是 `pass`**、
  `verify_migration()` 恒返回 `True`——挂上去等于对外提供一圈恒真接口。
- `skill_market` / `skills_market`：ADR 0013「统一技能市场端点」判定的待删套
  （分别 stub / demo 实现，模块自带 `_DEPRECATED`），规范端点为 `skill_pool_api.py`。

### 7.4 同一根因的其余命中点（放大视角）

守卫失明与上面是**同一条契约**：`include_router` 不再就地摊平子路由，而是追加惰性
包装对象（`_IncludedRouter`）。凡直接 `for r in app.routes: r.path` 的测试都会
`AttributeError`，或用 `hasattr` 兜底后**静默取空集**——守卫既红不了也绿不了。
故遍历收口为 `tests/route_table.py` 一份，并修好命中点：

- `tests/unit/test_neuron_api_registration.py`（3 例红转绿）
- `tests/unit/api/test_console_split_contract.py`（4 例）
- `tests/unit/api/test_knowledge_route_order.py`（2 例）
- `tests/unit/api/test_knowledge_config_endpoints.py`（1 例）
- `tests/unit/api/test_growth_route_livability.py`（1 例）
- `tests/unit/api/test_text_evolution_api.py`（1 例）
- `tests/test_api/test_memory_route_shadowing.py`（1 例）

```text
# 改动前（红）
pytest tests/unit/api tests/test_api tests/unit/test_neuron_api_registration.py
  → 27 failed
# 改动后（同一个集合）
  → 全部转绿，新增失败 0（A/B 逐行比对 comm 为空集）
```

### 7.5 非目标（未偏离）

`computer.ts`（React 原型客户端）那一支的 `/api/computers/*`、`/api/cost/*`
十五条差异**仍留在差集表里显式登记**，未顺手补后端——那要先裁定
`NeurUI/src/views/*.tsx` 是迁移中还是误提交（findings u5），属产品形态决策。
删条目不等于修好：清单的价值在可信，藏差异则整表不可信。
