# ZCode 工具调用与工具数量对照——Neurova 可补充项分析

- 日期：2026-11-15
- 对象：zai-org/ZCode v3.18.2（克隆件 `E:/项目/_external_repos/zai-org-ZCode`，只读）vs 本仓当前代码
- 方法：ZCode 侧逐项读取工具注册表（`apps/zcode-cli/packages/core/src/tool/handlers/index.ts` 与 `session-control/index.ts`）；Neurova 侧枚举 `neurova/builtin_tools.py::_BUILTIN_SCHEMAS` 全部键。只陈述两边代码里核实到的事实。
- 关联：[ZCode 对照评测主报告](zcode_vs_neurova_harness_code_comparison_2026-11-14.md)（维度 B 工具系统与执行治理的深化）。

---

## 1. 总量与构成

| | ZCode | Neurova |
|---|---|---|
| 内置工具数 | **53**（注册表 46 + 会话控制族 7） | **119**（`_BUILTIN_SCHEMAS` 键）+ MCP/技能动态面 |
| 面向 | 编码工作流深度优先 | 通用 Agent 平台广度优先 |

ZCode 53 个按族分布：文件与代码 7（read/write/edit/bash/glob/grep/js-REPL）、网络 2（webFetch/webSearch）、任务与计划 5（todoRead/todoWrite/enterPlanMode/exitPlanMode/askUserQuestion）、定时与错峰 7（cron×5/offPeak×2）、会话控制 7（List/Read/Create/Fork/SendTo/Wait/InterruptSession）、多代理协调 8（agent/task/sendMessage/respondToCoordinator/submitResult/escalate/taskOutput/taskStop）、工作流脚本族 10（createWorkflow/amendWorkflow/saveWorkflow/evalWorkflowSnippet/listWorkflowRuns/getWorkflowRun/resumeWorkflowRun/resolveWorkflowQuestion/fillWorkflowHole/listSavedWorkflows）、工具面治理 6（toolSearch/deferredToolCall/listModels/searchPlugins/suggestPluginInstall/readTopicResource）、技能 1（skill）。

Neurova 119 个按族分布：记忆与上下文 8、文件 9、电脑操控 11、浏览器 34、语音 3、中文生态与内容 4、检索与网络 5、数据 1、实用 4、Agent 与协调 4、技能知识 3、规划 2、工作流与画布 28、其他 1。

## 2. ZCode 工具调用机制（Neurova 视角的要点）

1. **两段式工具加载**：`toolSearch`（按需检索工具目录）+ `deferredToolCall`（取回 schema 后再调用）——常驻上下文只放目录，schema 按需加载。Neurova 的 A6（`tool_search`/`tool_describe`/`tool_call` + BM25/语义混合）已同构。
2. **ToolEntry 元数据单源**：每个工具的 readOnly/destructive/riskLevel/needsApproval/timeout 由一份 ToolEntry 元数据同时供权限判定、调度并行、审批卡消费。Neurova 的对应声明分散在 capability/flags/reproducible 各键（P1-2 的统一收口仍开项）。
3. **逐工具结果预算**：resultBudget 默认 100KB，超限落 artifact 只回预览。Neurova 已补齐（P1-1，`result_budget_chars`）。
4. **审批即管线**：ASK 的审批单携带执行入参指纹，批准即按原参数执行。Neurova 已补齐（P1-2a 指纹）。
5. **协调协议**：子代理以 `submitResult` 结构化交结果、`respondToCoordinator` 定向应答、`escalate` 遇阻升级——长任务子代理卡死时有升级出口。Neurova 的 spawn_subagent 只有结果回灌。
6. **后台任务内省**：`taskOutput`/`taskStop` 查询与终止后台任务。
7. **定时任务全生命周期**：cronCreate/List/Update/Delete/PauseSelf 五工具覆盖建/查/改/删/暂停。
8. **会话控制族**：Fork（分叉会话）/Interrupt（打断当前轮）/SendTo/Wait——跨会话操作是一等工具。

## 3. 逐类对照与可补充候选

### 3.1 ZCode 有、Neurova 无 → 建议补充

| # | 候选 | ZCode 形态 | Neurova 现状 | 建议 | 优先级 |
|---|---|---|---|---|---|
| 1 | **定时任务生命周期** | cronCreate/List/Update/Delete/PauseSelf 五工具 | `schedule_task` 仅 create/list/cancel | 给 `schedule_task` 扩 `update`（改 cron/参数）/`delete`/`pause`+`resume` 子命令，补齐定时任务全生命周期 | **P1** |
| 2 | **子代理升级/应答协议** | escalate（遇阻升级）/ respondToCoordinator（定向应答）/ submitResult（结构化交结果） | spawn_subagent 只有结果回灌；子代理卡死/遇阻无升级出口 | 子代理运行时增 `escalate`（升级到主代理或用户）与结构化结果提交——长任务不再静默卡死 | **P1** |
| 3 | **后台任务内省** | taskOutput/taskStop | subagent_status 只覆盖子代理；定时任务无输出查询/停止 | 为定时/后台任务补 `task_output`/`task_stop`（或并入 schedule_task 的 list 子命令扩展） | **P2** |
| 4 | **错峰任务族** | offPeakCreate/List（429 感知错峰排队） | 429 停让只在单次调用层 | 依赖弹性包的 off-peak 排队能力落地后，暴露错峰任务创建/查询工具 | **P2**（依赖弹性包 off-peak） |
| 5 | **JS REPL** | js（Node 独立 REPL） | run_code 只跑 Python | 前端/JS 密集场景（本仓自身前端工作流）有真实价值；走既有沙箱执行面 | **P3** |
| 6 | **主题资源读取** | readTopicResource | 无直接对应 | 与 P3-16 UI 资源托管配套时再做 | **P3** |

### 3.2 调用机制层面 Neurova 已对齐（本批或既有）

| 机制 | ZCode | Neurova |
|---|---|---|
| 两段式工具加载 | toolSearch + deferredToolCall | A6：tool_search/tool_describe/tool_call（BM25+语义混合） |
| 逐工具结果预算 | resultBudget 100KB→artifact+预览 | `result_budget_chars`（P1-1） |
| 审批=执行 | 审批单携执行入参，批准即原参数执行 | 执行入参指纹核验（P1-2a） |
| 危险命令分级 | guarded 语法匹配+单次确认 | command_syntax 三级判定+白名单降级（P1-3） |
| 会话级权限模式 | 六种 CollaborationMode | 权限六态+请求级/治理覆写解析（P1-4） |
| 后台任务 | taskOutput/taskStop | subagent_status（子代理维度） |

### 3.3 Neurova 独有、ZCode 没有的（保持，不补）

记忆八件套（memory_search/recall_history/recall_context_span/pool_search/graph_search/context_compress/context_status/voice_memory_search）、浏览器 34 工具（cookies/storage/console/pdf/download/drag/hover/select/eval/tab 管理等）、电脑操控 11（含 SOM 快照/SSH）、语音 3（ASR/TTS/语音记忆）、中文生态 4（bilibili/rss/v2ex/youtube_transcript）、deep_research/social_search/agent_reach、query_database、write_pdf、emotion_analyze、画布与工作流 28（canvas×12/workflow×9/custom_node×4/schedule_task/node_schema 等）。ZCode 作为编码 harness 没有这些面——是 Neurova 的广度优势，不在"补充"之列。

## 4. 结论

工具**数量** Neurova 119 > ZCode 53，但 ZCode 在五处有真实增量价值：**定时任务全生命周期**（P1）、**子代理升级/应答协议**（P1）、**后台任务内省**（P2）、**错峰任务族**（P2，依赖弹性包 off-peak）、**JS REPL 与主题资源读取**（P3）。调用机制层面，两段式加载、结果预算、审批=执行、危险命令分级、会话级权限模式五项已在本批对齐；剩余差距是 **ToolEntry 元数据单源**（P1-2 收口）。建议按上表优先级点单实施；每项均走先红后绿＋推双远端。
