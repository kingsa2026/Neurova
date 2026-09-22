# 立项：`api_inventory.md` 重生成（前端 API 清单快照过期）

> 立项日期：2026-09-22
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

- **唯一写者**：`scripts/generate_api_inventory.py`；清单正文由它产出，
  生成命令 `python scripts/generate_api_inventory.py --write`。
- **双向差集归零**：清单声明的前端模块 61 个 == `NeurUI/src/api/modules/*.ts` 全集
  （排除 barrel `index.ts`）；后端挂载点 88 条 == 注册表 + `app.py` 直接挂载的实际结果。
- **过期判据换成差集**：不再靠日历。代码树增删一个模块，差集即非空，
  守卫 `tests/unit/test_api_inventory_freshness_guard.py` 报红并给出两侧名单。
- **导航归属**：仍作**现行清单**保留在 `docs/0-index/README.md` 的 `09-dev-progress`
  领域入口表内（不降级为归档）；重生成后其路径引用全部可解析，
  台账第八节入筛条目 103 → 0，棘轮基线 `tests/unit/archiveNavPointerBaseline.txt` 下调为 `0`。
- **live-verify**：静态收集到的 830 条路由与真应用 `openapi()` 的 836 条逐条对齐，
  静态侧零假阳性（守卫内含该自证）。

## 7. 重生成暴露的断点（本单**登记**，另单处置）

重生成按「逐条可核」执行，顺带把此前只存在于架构评审里的三处接线断点变成**可复算读数**。
它们不在本单改动范围（改动面涉及运行时路由行为，需独立评估），故在此登记，不静默遗留：

| 断点 | 读数 | 性质 |
|------|------|------|
| `/api/evolution`、`/api/rag` | 挂载动作在、路由零条 | `endpoints/__init__.py` 的 `evolution_router` / `rag_router` 是模块级空 `APIRouter()`，全仓无任何注册语句 |
| `/api`（顶层 `router`） | 同上 | `endpoints/__init__.py` 的顶层 `router` 零路由，仅作容器 |
| `cost.ts` 请求 `/api/v1/budgets`、`/api/v1/cost-rollup` | 运行时零命中 | 后端挂在 `/api/budgets`、`/api/cost-rollup`（缺 `v1`），前端 `baseURL=/api/v1` → 必 404 |

处置建议（择一，须单独立项）：空 router 接线或删除；
`cost.ts` 的两条前缀要么后端改挂 `/api/v1`，要么前端改走绝对路径——
两条路都会动运行时行为，需与 `docs/architecture-model/architecture-findings.md`
第 6.1/6.3 节的既有裁定合并考虑，不在本单顺手改。
