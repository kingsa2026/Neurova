# reference_ab vs Neurova：平台托管型多智能体编排 vs 自研蜂群编排 对照评测（2026-11-20）

> **性质**：外部参照项目机制研读与对照评测（研究参考，仅作背景，不可作事实源）。
> **参照项目**：代号 `reference_ab`——某云厂商解决方案库中的「多智能体协作」Guidance（客户支持场景演示）：基础设施即代码（IaC）装配 + 托管 Agent 平台原生「监督者协作」编排 + 四个领域子代理 + 向量知识库与数据湖 text2SQL 工具 + 托管 GraphQL 网关 WebSocket 流式 + React Flow 协作过程可视化。TypeScript monorepo：后端 IaC 约 3.9k 行 + 前端 React 约 2.4 万行 + Python 工具 290 行（116 个源文件），Apache-2.0，2025-03 立项，76 stars / 45 forks，最近代码推送 2026-01-08（本次研读取 main 快照）。
> **本文纪律**：全文不出现参照项目、其云厂商与托管平台的产品实名；云厂商称「平台厂商」，托管 Agent 服务称「托管 Agent 平台」，各云服务按通用形态指代（对象存储/文档数据库/托管 GraphQL 网关/托管身份服务/函数计算/数据目录/交互式 SQL 查询引擎/事件总线/Web 应用防火墙/CDN）。开源通用件（React/React Flow/WebSocket/GraphQL/OpenAPI/ESLint/Husky 等）按原名指代。本仓侧全部结论以 file:line 实证，关键论断经二次抽查核实。

---

## 1. 结论摘要

1. **形态判断**：reference_ab 是「平台托管编排」路线的示范项目——任务分解、路由、委派、汇总这些编排智能**全部下放给托管 Agent 平台的原生监督者协作能力**，仓库自身只负责四件事：基础设施装配（IaC）、提示词工程（各代理 instruction 文件）、工具供给（text2SQL 函数 + 向量知识库）、以及面向人的可观测化（trace 解析 + React Flow 协作图）。它与本仓「自研编排内核」路线（状态机、事件账本、候选合并、审批链、租户隔离全部自己持有，`neurova/agent/swarm.py` / `swarm_support.py` / `candidate_merge.py` / `approval_chain.py`）是同题不同解：**对方把复杂度交给了平台，本仓把复杂度留在代码里**。
2. **总评分**：**Neurova 81.6 / 100 vs reference_ab 44.6 / 100**（10 维 30 子项，§4）。本仓在编排深度相关的维（任务分解、生命周期、结果聚合、审批治理、隔离）全面领先，其中「结果聚合与质量门」「人在环与审批治理」两维对方近乎空白；对方在「记忆与知识接入」一维与本仓打平（7.3 vs 7.3），在「实时协作可视化」单个子项上拿到全场最高分（9/10）。
3. **对方最值得学的不是编排本身，而是三件周边工程**：①知识库摄取的**事件驱动自动化三件套**（数据变更事件触发摄取 + 部署后立即同步 + 24 小时同步检查器，`product_recommendation/index.ts:72-135`、`kb-sync-checker/index.py:119-189`）；②**代理协作 trace 的前端图可视化**（2106 行 traceParser + React Flow 实时协作图，把「谁在干什么、耗时多少、谁给谁的最终答案」画给人看）；③**成本透明表**（逐服务、逐代理的月度成本测算 + 预算建议写进 README）。
4. **对方的天花板也很清楚**：编排逻辑埋在提示词里（路由正确性依赖模型、不可回归测试）；无生命周期状态机、无结果候选与评审门、无审批链、单租户、后端测试文件为 0 行。这些恰是本仓蜂群的核心资产。**两条路线不可直接互换**：平台托管用可控性换开发速度，自研编排用速度换治理深度；本仓的差异化价值恰在被对方省略的那一半——但对方也提醒我们：治理深度若不配上同等体验（可视化、开箱即用），用户感知会打折扣。
5. 借鉴清单：**P1×3 + P2×4**（§6），不照搬×4（§6.3）。无 P0 级借鉴项——对方没有任何一项触及本仓的在途风险或正确性缺口；反向地，本次梳理顺带钉实了本仓三处「设计-实现落差」（外部成员验收通道未接线、外部成本标记未落地、候选板进程内态），已列入 §5.3。

---

## 2. 参照项目画像

### 2.1 定位与总体架构

```
 用户浏览器（React + 云厂商设计系统 + React Flow 协作图）
   │  Web 应用防火墙 + CDN（对象存储托管静态站）
   ▼
 托管 GraphQL 网关 / WebSocket 订阅（onUpdateChat）
   │  Mutation.sendChat
   ▼
 函数计算 resolver（平台 InvokeAgent，enableTrace + streamFinalResponse）
   │  每帧回写 Chat 记录（文档数据库，24h TTL）
   ▼
 监督者 Agent（托管平台原生 supervisor 协作，平台主力模型）
   ├── Personalization 子代理（轻量模型 + 向量KB + SQL 工具）
   ├── OrderManagement 子代理（超轻量模型 + SQL 工具）
   ├── ProductRecommendation 子代理（轻量模型 + 向量KB + SQL 工具）
   └── Troubleshoot 子代理（超轻量模型 + 向量KB）
              │ 共享动作组函数（OpenAPI schema → /athenaQuery）
              ▼
        交互式 SQL 查询引擎 + 数据目录（对象存储结构化数据）
```

装配顺序见后端栈入口（`src/backend/lib/stacks/backend/index.ts:20-46`）：auth → storage → multiAgent → streamingApi；各代理 ID 经环境变量由部署期导出、构建期注入前端（同文件 `:48-72`）。

### 2.2 关键数字（main 快照实测）

| 维度 | 读数 |
|---|---|
| 代码形态 | TypeScript monorepo：IaC 后端 3856 行 + React 前端 23781 行 + Python 290 行 |
| 代理数量 | 1 监督者 + 4 子代理（全部为托管平台代理） |
| 编排模式 | 仅「监督者协作」一种（平台原生） |
| 自研编排代码 | 0 行（路由/委派/汇总均在平台内 + 提示词） |
| 工具 | 1 个共享 text2SQL 函数（`/athenaQuery`），5 个代理共用 |
| 知识库 | 4 个向量知识库（平台嵌入模型），对象存储数据源 |
| 结构化数据 | 3 个数据目录库 + SQL 查询引擎，5 张演示表 |
| trace 解析器 | 前端 `traceParser.ts` 2106 行 |
| 后端测试 | **0 行**（`src/backend/test/demo.test.ts` 空文件） |
| 前端测试 | 3 文件 476 行（agentConfig / traceParser / subtask） |
| 成本表 | README 逐服务测算：10 万请求/月约 $760.94，建议配预算告警 |

### 2.3 工程纪律亮点

- **成本透明**：README 内置逐服务成本表（含每个代理的调用次数×单价、知识库费用、Agent 构建服务费），并建议配置预算告警——把「这套东西跑起来多少钱」写成了文档义务。
- **合规自动化**：IaC 规则扫描（cdk-nag 形态）+ 显式抑制清单（每条抑制附理由，`streaming-api/index.ts:49-66`）；文档数据库默认开时点恢复 + 平台托管密钥加密（`streaming-api/index.ts:69-80`）。
- **凭据零硬编码**：代理 IDs 全部由部署期导出、构建期注入（`backend/index.ts:48-72`），前端另备本地开发配置通道与占位符兜底（`agentConfig.ts:194-284`）。

---

## 3. 核心机理研读

### 3.1 编排：平台原生监督者协作（对方的核心押注）

监督者以 `AgentCollaboratorType.SUPERVISOR` 声明，挂四个 `AgentCollaborator`（`multi-agent/index.ts:189-237`）。每个协作者只带三样东西：代理别名、一句话协作指令（如「订单管理问题路由给本代理」，`order_management/index.ts:78-83`）、以及 `relayConversationHistory: true`（会话历史接力，`product_recommendation/index.ts:196-201`）。

真正的「编排逻辑」写在监督者的 17 行提示词里（`multi-agent/instructions.txt`）：①分析意图定目标 → ②按领域选子代理 → ③复杂请求可串行/并行委派 → ④汇总全部子代理结果成一篇回答；外加两条约束「不得编造」「回复不超过 100 词」。

**要点**：任务分解与路由是模型在平台运行时隐式完成的，仓库里没有一行代码决定「谁接哪个活」——因此也没有路由正确性的回归测试手段。串/并行委派只是提示词里的建议，实际并发行为不可控、不可观测（平台侧 trace 例外）。子代理按领域配不同档位模型（主力/轻量/超轻量），是一种朴素的成本分级。

### 3.2 工具层：单函数 + OpenAPI schema 的 text2SQL

五个代理共享同一个 Python 函数计算动作组（`action-group/executor-function/index.py:15-77`）：以 OpenAPI schema 声明 `/athenaQuery`（入参 SQL 文本），执行链路为「查询小写化 → 发起查询 → 每秒轮询状态 → 取结果」。数据面是 SQL 查询引擎 + 数据目录直查对象存储（无数据搬迁）。子代理提示词内联了表 schema 与 SQL 示例（如 `product_recommendation/instructions.txt` 的 `<athena_schemas>` 段），用 few-shot 约束生成 SQL 的列名与格式，并加了「列名必须对照 schema 复核」「品名检索用 LIKE」这类针对性提示。

### 3.3 知识工程：摄取自动化三件套（对方最完整的周边工程）

1. **事件触发摄取**：事件总线规则监听知识桶数据变更 → 自动发起摄取作业（`product_recommendation/index.ts:72-95`）；
2. **部署后立即同步**：资源部署完成事件触发初始摄取（`index.ts:115-135`），另有部署尾 custom resource 等全部知识库就绪后统一触发一次同步（`multi-agent/index.ts:141-174`）；
3. **24 小时同步检查器**：定时函数检查每个数据源「24 小时内是否有成功的摄取作业」，没有就带指数退避补跑（`kb-sync-checker/index.py:119-189`）。

这套「事件驱动 + 部署钩子 + 兜底巡检」的组合，保证演示环境的知识库永远不会静默过期。

### 3.4 通信与流式：托管网关 WebSocket 单通道

对外只有一条通道：前端 `Mutation.sendChat` → 函数计算 resolver → 托管平台 `InvokeAgent`（`enableTrace: true` + `streamFinalResponse: true` + `sessionAttributes` 携带用户名，`resolver-function/index.ts:87-102`）；每收到一帧就把**累计文本 + 完整 trace JSON** 写回 Chat 记录，前端经 GraphQL 订阅收流（`Chat/api.ts:22-23` 采用「静默成功」模式——发消息接口只管触发，响应全走订阅）。限流错误带 5 次指数退避重试（`resolver-function/index.ts:23-60`）。

**代理间通信完全不在仓库代码里**：协作历史接力由平台在监督者与协作者之间自动完成，仓库只能通过 `relayConversationHistory` 开关表达「接不接」，表达不了「接多少、怎么裁剪」。

### 3.5 可观测性：trace 全量 + 前端图可视化（对方体验最强的一面）

- 采集：trace 全量开启；每帧 trace 以 `traceMetadata`（agentId/agentName/collaboratorName/agentAliasId/sessionId/agentVersion/trace/callerChain）结构化落库（`multiWebsocket.ts:36-45`）。
- 解析：前端 `traceParser.ts`（2106 行）把平台 trace 事件流解析成 Task/SubTask 层级——模型输入/输出配对、知识库检索与动作组调用分类、逐步耗时计算、最终响应检测、监督者/协作者身份判定。
- 呈现：React Flow 实时协作图（`AgentFlowPanel`）——代理为节点、消息流动画边、节点状态指示（活动/完成/空闲）、点击节点看 TraceModal 逐步明细。
- 兜底：代理身份识别有「环境变量静态映射 + 动态发现注册 + 名称模式匹配」三层（`agentConfig.ts:57-156`）。
- 局限：解析重逻辑全在前端；后端没有统一的运行台账/审计事件闭环；trace 字段是平台私有结构，前端解析器与平台版本强耦合（2106 行里大量防御性分支即是证据）。
- **一个值得注意的缺口**：前端为「路由分类器代理」预留了完整配置与识别逻辑（`agentConfig.ts:13-20,104-105`），但后端栈并未创建该代理、也未注入对应环境变量（`backend/index.ts:48-72` 无对应键）——属于前瞻性死配置。

### 3.6 安全与部署

- **安全**：托管身份服务用户池（密码策略、admin/users 两组）+ 身份池；Web 应用防火墙双层（CDN 边缘托管规则组 + 区域 ACL 关联 GraphQL 网关与用户池，`auth.ts:164-234`）；GraphQL 按 owner 隔离（`identityClaim: "sub"`，`schema.graphql:2-3`）；对象存储访问日志、数据目录/查询引擎最小授权策略、合规扫描抑制清单、文档数据库时点恢复 + 托管密钥加密。**单租户**，无组织/部门级隔离概念。
- **部署**：IaC 全量 + 交互式 CLI（configure/develop 两命令）+ 流水线服务 CI/CD（`pipeline.ts`）+ 前端托管；Husky/commitlint/ESLint/ruff 工程链齐全。
- **测试**：后端测试文件为空（0 行）；前端仅 3 个单测文件（476 行，覆盖 agentConfig 与 traceParser）；无任何编排行为级测试。

---

## 4. 评分框架与逐维评分

### 4.1 框架说明

10 维 × 10 分 = 100 分；每维 2–4 个子项，子项各按 0–10 打分后取平均得维度分。评分口径：**只看仓库内可验证的机制与工程事实**——平台托管能力只在其对仓库代码可见、可控、可测的范围内计分；黑盒内的能力不因「平台有」而自动得分，但其在仓库中的接线质量、暴露程度与可测性计分。两种部署形态（云托管 demo vs 自托管平台）带来的先天差异在涉及维度单独注明，不做虚高或虚低修正。

### 4.2 评分卡

| # | 维度 | 子项 | reference_ab | Neurova |
|---|------|------|:---:|:---:|
| D1 | 编排模式与拓扑 | 模式多样性 | 3 | 9 |
| | | 拓扑表达力 | 5 | 8 |
| | | **小计** | **4.0** | **8.5** |
| D2 | 任务分解与派发 | 结构化任务单元 | 2 | 9 |
| | | 依赖门控 | 1 | 9 |
| | | 成员选择与并发治理 | 4 | 8 |
| | | **小计** | **2.3** | **8.7** |
| D3 | 生命周期与状态治理 | 状态机与迁移收口 | 2 | 10 |
| | | 重放·恢复·续跑 | 2 | 9 |
| | | 超时·幂等·TTL | 6 | 8 |
| | | **小计** | **3.3** | **9.0** |
| D4 | 通信与上下文共享 | 代理间消息与共享上下文 | 2 | 9 |
| | | 会话历史接力 | 7 | 8 |
| | | 对外流式通道 | 8 | 8 |
| | | **小计** | **5.7** | **8.3** |
| D5 | 结果聚合与质量门 | 结果聚合 | 5 | 8 |
| | | 冲突消解 | 1 | 8 |
| | | 评审·验收门 | 1 | 9 |
| | | **小计** | **2.3** | **8.3** |
| D6 | 人在环与审批治理 | 审批链与分级 | 1 | 10 |
| | | 裁决安全 | 1 | 9 |
| | | 治理回灌与沉淀 | 1 | 8 |
| | | **小计** | **1.0** | **9.0** |
| D7 | 记忆与知识接入 | 知识检索接入 | 8 | 8 |
| | | 跨会话记忆与个性化 | 6 | 8 |
| | | 数据工程与摄取 | 8 | 6 |
| | | **小计** | **7.3** | **7.3** |
| D8 | 可观测性与调试 | trace 采集与结构化 | 7 | 9 |
| | | 实时协作可视化 | 9 | 6 |
| | | 台账·审计·效率判据 | 4 | 9 |
| | | **小计** | **6.7** | **8.0** |
| D9 | 安全与隔离 | 认证与授权 | 7 | 8 |
| | | 多租户隔离与数据围栏 | 1 | 8 |
| | | 基础设施防护与合规 | 9 | 5 |
| | | **小计** | **5.7** | **7.0** |
| D10 | 成本·部署·工程化 | 成本核算与治理 | 7 | 8 |
| | | IaC·CI/CD | 9 | 6 |
| | | 测试覆盖 | 2 | 9 |
| | | 开发体验与文档 | 7 | 7 |
| | | **小计** | **6.3** | **7.5** |
| | **合计** | | **44.6** | **81.6** |

### 4.3 逐维评注

**D1 编排模式与拓扑（4.0 vs 8.5）**
- 对方：仅监督者一种模式且拓扑静态写死在 IaC 里（1 监督者 + 4 协作者，`multi-agent/index.ts:189-237`）；协作关系=一句话指令 + 历史接力开关；前端的协作图是「展示」而非「定义」。模式多样性 3、拓扑表达 5。
- 本仓：蜂群派生（`swarm.py:326 spawn`）、固定团队整体派活（`swarm.py:718 dispatchTeam`，名册序/id/名映射为步间依赖 `:759-791`）、房间直发、外部代理编入（`swarm.py:1902 _resolveExternalMember`）、名册选人四步 fallback（`swarm.py:835 _resolveTeamMember`）多形态并存且共用同一治理闸；事件带 lineage 谱系（`swarm_event_log.py:83`）。模式多样性 9、拓扑表达 8（拓扑可运行时构造，但无可视化编辑面）。

**D2 任务分解与派发（2.3 vs 8.7）**
- 对方：任务=自然语言文本，分解在平台/模型内隐式完成，无结构化载体（2）；无依赖门控，串/并行只是提示词建议（1）；并发行为不可控不可测（4）。
- 本仓：`TaskUnit` 结构化任务书（goal/expectedResult/acceptanceCriteria/requiredInputs/artifactOwnership/reviewMode/dependencies/untrustedPayload，`task_unit.py:21`，容错解析 `:66`）；spawn 内依赖门（防环 `swarm.py:525-531`、前置失败即时拒 `:537-544`、未满足登记 blocked 不占槽 `:572-584`、终态结算放行 `:1335-1364`）；派发前治理三明治（深度/并发/预算/冷却/错峰，`swarm.py:286-302,463-495`）。三子项 9/9/8。

**D3 生命周期与状态治理（3.3 vs 9.0）**
- 对方：无状态机，会话由平台 sessionId + 30 分钟空闲 TTL 承载（2）；函数级限流退避重试与知识库巡检是仅有的恢复手段，run 级无重放/续跑（2）；函数超时/TTL/幂等靠平台默认（6）。
- 本仓：`RUN_STATUS_TRANSITIONS` 迁移表 + `transitionRun` 唯一收口（非法迁移抛错、同态幂等、合法迁移落 status_changed 因果事件，`swarm_support.py:54-148`）——满分 10；账本重放 `replayRunTailStatus`（`:155`）+ 启动收敛 `reconcileSwarmRunsAtStartup`（`:173`，`api/app.py:974-976` 调用）+ 漂移校正 `reconcileRunFromEvents`（`swarm.py:1013`）+ 续跑权威单点 `takeForResume`（`agent_run_store.py:414`）——9；审批等待超时、邮箱 messageId 幂等 + 死主回收（`mailbox.py:83-85,184`）、候选 CAS 幂等——8。

**D4 通信与上下文共享（5.7 vs 8.3）**
- 对方：代理间通信是平台黑盒，仓库不可控（2）；历史接力开箱即用但粒度不可调（7）；对外流式是生产级单通道——网关订阅 + 每帧落库 + 限流退避（8）。
- 本仓：父邮箱两阶段确认/优先级/幂等/死主回收（`mailbox.py:51`）+ 唯一写点 `pushParentMail`（`swarm.py:2723`，抽查属实）+ 信封投影带下钻指针（`swarm.py:2660`）+ 房间黑板（`room_bus.py:79`）+ room 作用域共享记忆（`swarm.py:228,2359-2364`）——9；任务驱动召回注入 member 提示词（`swarm.py:2383-2396`）——8；SSE/WS 事件广播 + 前端断线续传（`useSessionSync.ts:131`）+ member 浮窗（`useSubAgentWindows.ts:37`）——8。

**D5 结果聚合与质量门（2.3 vs 8.3）**
- 对方：监督者按提示词把子代理结果汇总成一篇回答——有聚合但不可控（5）；无冲突消解（1）；无评审/验收门（1）。
- 本仓：member 报告先落候选（`swarm.py:1126 _submitResultCandidate`）→ CAS 合入（`candidate_merge.py:182 mergeCandidate`，baseRevision 乐观锁，抽查属实）→ merged 才可 completed（`swarm.py:2461-2467`）——8；同 key 同基准冲突双保留互标并升级人工裁决（`candidate_merge.py:148,246`）+ 房间处置 `applyRoomCandidateAction`（`swarm.py:1264`）——8；验收门（判定→回炉一次→诚实降级，`acceptance_gate.py:101-132`）+ 评审门（P0-P3 结构化评审逐条修正，`review_gate.py:71-120`）+ APEX 量规任务集（`apex_tasks.py:29`）——9。

**D6 人在环与审批治理（1.0 vs 9.0）**
- 对方：代理域内无任何审批/人审机制（唯一 ManualApprovalStep 在部署流水线，`pipeline.ts:150`）；三子项各 1。
- 本仓：审批链 L0/L1/L2 分级只升不降 + 危险命令至少 L1（`approval_chain.py:34-44,77`）；裁决单源 `decideSwarmApproval` 幂等 + 只认 source=swarm（`:415-425`）+ 裁决人租户校验 fail-closed（`:448-461`，抽查属实）+ 安全审计落盘（`:158-245`）；父邮箱/房间双通道上墙（`:347-349`）；治理回灌 `applyProjectGovernanceDecision`（`tool_executor.py:87`）与团队沉淀 `applyTeamProposalDecision`（`teams_api.py:288`）。三子项 10/9/8。

**D7 记忆与知识接入（7.3 vs 7.3，平手）**
- 对方：4 个向量知识库语义检索 + text2SQL 结构化查询 + schema few-shot 注入（8）；会话属性个性化 + 行为/偏好知识库（6）；数据目录 + 查询引擎 + 摄取自动化三件套（8）。
- 本仓：memory_search/knowledge_search/knowledge_graph 工具面（`builtin_tools.py:111,128`、`tool_executor.py:6154`）+ 任务驱动召回（`swarm.py:2383-2396`）+ 反向 MCP 检索面（`mcp_agent_tools_server.py:155,184`）（8）；记忆域体系 + room 作用域 + 会话档案（8）；企业源同步可靠性已落（见 `docs/04-plans/2026-11-19-enterprise-datasource-mcp-plan.md` 关联批次），但 text2SQL 型结构化分析面未建设（6）。**本仓强在记忆治理与多代理共享，对方强在结构化数据工程与摄取自动化。**

**D8 可观测性与调试（6.7 vs 8.0）**
- 对方：trace 全量结构化落库 + callerChain（7）；React Flow 实时协作图 + TraceModal + 逐步耗时/最终响应检测——全场最强单项（9）；有日志/链路追踪但无业务级台账审计（4）。
- 本仓：H-4 事件账本（seq/causation/lineage，`swarm_event_log.py:83`）+ span trace trace_id 落台账（`swarm.py:2133-2182`、`agent_run_store.py:113-124` v4）+ 外部代理帧账本与 tool_call 脱敏镜像（`frame_log.py`、`acp_member.py:181-213`）——9；前端有浮窗栈/状态卡/事件订阅（`useSubAgentWindows.ts`、`TeamPage.vue:9-16`）但无协作拓扑图级可视化——6；agent_runs 台账 + 审批安全审计 + 项目协作档案五类记录 join 封卷（`projects_api.py:460-570`）+ 轨迹效率判据（`benchmark/multi_agent/runner.py:199-201`）——9。

**D9 安全与隔离（5.7 vs 7.0）**
- 对方：托管身份服务 + owner 隔离 + IAM 最小化（7）；无多租户概念（1）；防火墙双层 + 合规扫描 + 加密 + 访问日志（9，云托管形态红利）。
- 本仓：JWT + 属主/管理员门 + 工具执行咽喉强制拦截先于治理审批不可 bypass（`tool_executor.py:1487-1514`）+ 管理面 admin 门（8）；租户红线收口——发起跨租户拒（`swarm.py:1935-1941`）、teams 404 不泄露存在性（`teams_api.py:160-188`）、agent_runs tenant 列 v6（`agent_run_store.py:149-163`）、进程池键六元组含租户（`process_pool.py:31-32,75-78`）、裁决人租户校验、WS 订阅腿归属校验（`session_sync.py:148-164`）（8，仍有项目/房间未租户化等在途缺口见 §5.3）；应用层安全较全，但基础设施层无 IaC 级防护自动化（5，自托管形态下部分由部署环境承担）。

**D10 成本·部署·工程化（6.3 vs 7.5）**
- 对方：成本透明表 + 预算建议（7）但无运行时记账反馈环；IaC + 流水线 + 交互式 CLI（9）；后端测试 0 行 + 前端 476 行（2）；README 完整、demo 场景清晰（7）。
- 本仓：usage 记账 + 预算闸拒派（`swarm.py:1807 _over_budget`）+ member 成本归因（`swarm.py:2220-2232`）（8，外部代理 cost_source 标记未落地见 §5.3）；CI 守卫体系 + 测试纪律但无 IaC（6）；核心链路 26 个测试文件 + 词汇表对齐钉子（`LEDGER_TO_WINDOW_STATUS`，`useSubAgentWindows.ts:116-119`）+ A/B 纪律（9）；docs 分层 + AGENTS.md 纪律但上手曲线更陡（7）。

---

## 5. 差距与领先面分析

### 5.1 本仓领先面（对方结构性空白）

1. **可控的编排内核**：结构化任务书、依赖门控、状态机收口、账本重放——对方全部交给了平台黑盒，仓库内既不可控也不可测。
2. **结果质量工程**：候选 CAS 合并、冲突双保留升级、评审门、验收门、APEX 量规——对方只有「监督者汇总」。
3. **人在环治理**：分级审批、裁决租户校验、安全审计、治理回灌——对方完全缺位。
4. **多租户与外部代理治理**：租户红线七处收口 + neuacp 外部代理全生命周期（能力双闸 `catalog.py:60,175`、审批泵 `acp_member.py:118`、进程池租户键、SSH 远程 `ssh_transport.py:43`）——对方为单租户封闭演示。
5. **测试与守卫纪律**：核心链路 26 个测试文件 + 词汇表对齐钉子 + A/B 自证纪律——对方后端测试 0 行。

### 5.2 对方领先面（本仓可借鉴）

1. **实时协作可视化**（D8 单项 9 vs 6）：把代理协作过程画成图，是人感知多代理系统的最短路径。
2. **知识摄取自动化**：事件触发 + 部署钩子 + 周期巡检三件套，保证知识不过期。
3. **结构化数据 text2SQL 面**：schema few-shot + SQL 查询引擎，让代理能答「数据里有什么」。
4. **基础设施合规自动化**：合规扫描 + 显式抑制清单 + 默认加密/备份。
5. **成本透明**：面向部署者的静态成本测算表。

### 5.3 本次梳理钉实的本仓在途落差（供台账核对）

1. **外部成员验收/评审判定通道未接线**：设计裁定外部成员交付物「不降级 skipped」（`docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md:174,485`），但 `swarm.py:1984` 构造 `NeuacpMemberAdapter` 未传 `verify_channel`（`acp_member.py:59,66` 默认 None，全仓无注入点）→ `swarm.py:2430` 取到 None → 验收/评审走 judge_unavailable 降级（`acceptance_gate.py:122-132`）。**对方对照教训：平台托管导致「无法测」；本仓有通道却不接，属应修落差。**
2. **`cost_source=external` 与台账 `model=external:{tool}` 未落地**（同计划文档 `:15,:215,:489`）；全仓无 `cost_source` 实现，`agent_runs` 无 model 列。当前外部代理「不计 token」是结构性结果，非显式标记。
3. **候选板/审批登记为进程内态**（`candidate_merge.py:19-20`、`approval_chain.py:697-703` 自注跨进程不可查）——H-4 已留痕，缺一个可查询投影。
4. **租户化三处遗留**：团队沉淀未传 tenantId（`teams_api.py:266` 自注）、主回合租户未落列（`agent_run_store.py:154` 自注）、项目/房间未租户化（`collaboration_isolation.py` 无 tenant 字段）。
5. **ZCode 插件形态单向管道**：运行中无逐工具审批/改参（计划文档 `:269`）。

---

## 6. 借鉴清单

### 6.1 P1（高价值，建议近期采纳）

| # | 借鉴项 | 对方证据 | 本仓落点 |
|---|--------|----------|----------|
| P1-1 | **蜂群协作过程拓扑可视化**：把 H-4 事件账本 + span trace 投影成代理协作图（节点=代理/run，边=委派/依赖/审批，动画=消息流，逐步耗时），复用 `/console/chat/runs` 与既有事件读面，不新建事实源 | `traceParser.ts` + `AgentFlowPanel`（React Flow） | NeurUI 运行详情/TeamPage 新视图；后端只需一个只读投影端点 |
| P1-2 | **外部成员验收判定通道补线**：把 `verify_channel` 接进 `NeuacpMemberAdapter` 构造链，让外部成员交付物走同一验收/评审门，消除 judge_unavailable 降级 | （反面教训：对方因平台托管而根本无法做质量门） | `swarm.py:1984` 构造点 + `acp_member.py:59`；配合 acceptance_gate 现有判定循环 |
| P1-3 | **知识摄取「部署钩子 + 兜底巡检」双保险**：部署/启动后立即同步一次 + 周期巡检补跑（带指数退避），补齐企业源/知识库同步的最后一公里 | `kb-sync-checker/index.py:119-189` + 部署尾 custom resource | 既有 TaskScheduler/企业源同步链上加启动钩子与巡检任务 |

### 6.2 P2（有价值，中期排期）

| # | 借鉴项 | 对方证据 | 本仓落点 |
|---|--------|----------|----------|
| P2-1 | **成本透明表进文档**：逐服务/逐代理月成本测算 + 预算建议写进部署文档 | README.md:115-140 | 部署文档 + `cost_source=external` 落地时一并补 |
| P2-2 | **text2SQL 只读分析档**：OpenAPI 动作组 + 数据目录 + schema few-shot 注入，作为企业数据源「只读分析」的轻量路径 | `schema.json` + `instructions.txt` `<athena_schemas>` | 企业数据源 MCP 方案（`docs/04-plans/2026-11-19-enterprise-datasource-mcp-plan.md`）的补充档位 |
| P2-3 | **候选板可查询投影**：候选/审批登记落库（或 H-4 投影读面），消除「重启后 submitted 卡诚实报不存在」 | trace 落文档数据库 + TTL，可随时回放 | `candidate_merge.py` 持久化；H-4 已有原始留痕 |
| P2-4 | **trace 解析坚持服务端投影**：对方 2106 行前端解析器与平台私有 trace 结构强耦合，是反面前车；本仓 H-4 自有 schema，应继续服务端出投影、前端只渲染 | `traceParser.ts` 2106 行防御性分支 | 前端新增可视化时约束：解析逻辑不进浏览器 |

### 6.3 不照搬

1. **平台托管编排路线本身**——路由/委派/汇总不可测不可控，与本仓治理深度相斥；本仓差异化恰在对方省略的那一半。
2. **前端重解析**——2106 行客户端 parser 绑定平台私有 trace 结构，升级即碎。
3. **单租户封闭形态**——多租户是本仓核心资产，对方无此概念。
4. **场景化提示词约束**（如「回复不超过 100 词」）——演示场景专属，不通用。

---

## 7. 局限与复核说明

- 参照系为演示级 Guidance：其「简」部分是形态使然（示范平台模式，非完整 harness）。评分已按「仓库内可见、可控、可测」口径校准——不把平台黑盒能力记到仓库头上，也不因「演示项目」身份过度扣分；D9c/D10b 两处受云托管 vs 自托管形态影响，已单独注明。
- 参照系最近推送为 2026-01-08，本报告基于 main 快照静态研读，未做云端部署实测；托管平台侧行为（路由质量、并发委派实际表现、trace 结构稳定性）不在可测范围内。
- 本仓侧证据由本次专项梳理产出（16 个方面逐条 file:line），并对状态机、CAS 合入、裁决租户校验、验收循环、父邮箱单源写点五处关键论断做了二次抽查核实；复评时请以当时代码为准。
- 关联既有文档：`docs/08-research/reference_w_swarm_orchestration_comparison_2026-11-15.md`（蜂群编排前次对照）、`docs/04-plans/2026-11-19-acp-coding-agent-team-integration-plan.md`（外部代理接入计划，D2/D6 裁定出处）、`docs/04-plans/2026-11-19-enterprise-datasource-mcp-plan.md`（企业数据源方案，P2-2 落点）。
