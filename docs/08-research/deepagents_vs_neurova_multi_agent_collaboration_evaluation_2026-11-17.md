# deepagents vs Neurova 多 Agent 协作对照评测（2026-11-17 第三轮）

> 参照系：deepagents（LangChain 官方开源 agent harness，github.com/langchain-ai/deepagents，克隆件 `~/.zcode/tmp/deepagents-src` @ 7725f7b，核心包约 3.2 万行 Python，另有约 6.8 万行测试）。
> 被评方：Neurova 本仓**当前态**（P1–P3 升级批 + H 批改进落地后）。
> 维度体系与评分锚点与前两轮**完全同框**（[AutoSwarm 轮](autoswarm_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)、[CoworkOS 轮](coworkos_vs_neurova_multi_agent_collaboration_evaluation_2026-11-17.md)），分数可直接对比。

---

## 1. 摘要（结论先行）

**总分：Neurova 84/110（76.4%），deepagents 参照系 81/110（73.6%）**——七维廿二子项等权求和（§6 总分表）。Neurova 以 3 分险胜；至此四轮参照系座次：**CoworkOS 95 > Neurova 84 = AutoSwarm 84 > deepagents 81**。

双方形态不同：deepagents 是"**可扩展的单 agent harness 库**"（LangGraph 运行时 + middleware 栈 + 可插拔后端，不自带产品面/多渠道/工作流）；Neurova 是"**产品化的多渠道多 Agent 平台**"。deepagents 的多 agent 能力是"主代理把任务委派给隔离子代理"（同步 task / 异步 Agent Protocol），没有蜂群式自主组队。

关键结论：
1. **deepagents 的强项与 CoworkOS 高度同构**：上下文压缩纪律（非破坏性 summarization event + 媒体/二进制/blob 三层 offload + "重试请求必须严格变小"校验 + DeltaChannel 把 checkpoint 增长降到 O(N)）与评测体系（136 个 eval + TrajectoryScorer 轨迹效率断言 + LLM-as-judge + 25 模型矩阵 + Harbor/TerminalBench）是全库最强两面（D3、F2 双 5 分）。
2. **deepagents 的协作形成/执行协调反而偏弱**（A 10、B3=2）：任务委派是自由文本 description（无结构化任务单元/验收条件），无依赖门控，无并发上限——AutoSwarm 轮指出的同一批缺口它也有。
3. **它的独门价值在工程化封装**：HITL 审批粒度到"每次调用的路径参数"（exact/bulk 双判定 + 封堵 `path="."`、glob 重定向绕过）；技能 progressive disclosure（工具在技能被读取后才进入模型请求面）；profile 双层体系（Provider/Harness）做到模型无关且不可剔除必需脚手架。
4. **Neurova 险胜靠治理与协作形成**：E 维 13 vs 10（治理三明治硬闸 + 审批链 L0/L1/L2 + 台账审计 vs 对方无审计持久化、无资源治理）；A 维 14 vs 10（TaskUnit/验收门/评审相位/依赖门控 vs 自由文本委派）。
5. 可借鉴点（并入既有登记，不新开战线）：H-6 压缩纪律再获旁证；新增"轨迹效率判据（agent_steps/tool_calls 断言）""HITL 按参数粒度"两条入 I 系清单。

---

## 2. 评测框架与方法

与上两轮完全同框：7 维 22 子项（A 协作形成 20 / B 执行协调 25 / C 通信 15 / D 记忆与上下文 15 / E 治理安全 15 / F 观测评测 10 / G 异构互操作 10），锚点 0–5（0=无实现…5=机制化+测试+治理+实证闭环）。方法边界同前：静态代码级机制评测，deepagents 的公开 benchmark 数字（LangSmith dashboard）只作参照不换算。本次经两路分区精读（runtime 核心 / 治理与后端）+ 官方 ARCHITECTURE.md 交叉核对，行号指克隆件 7725f7b。

---

## 3. 参照系 A：deepagents 定位与机制

### 3.1 定位

LangChain 官方"opinionated agent harness"：三层栈 = LangGraph（运行时：状态/checkpoint/流式/interrupt）+ LangChain `create_agent`（agent 抽象）+ Deep Agents（默认 middleware 栈、backends、subagents、skills、profiles）。**不实现自己的 agent 循环**——`create_deep_agent()`（graph.py:1024-1046）最终调用 `langchain.agents.create_agent(...)` 并以 `recursion_limit=9_999` 收口。

### 3.2 核心机制

- **middleware 栈**：基座（Filesystem → SubAgent → ParentNotifier → Summarization → PatchToolCalls → AsyncSubAgent）+ 调用方 middleware（按 name 就地替换/插位）+ 尾段（profile 附加 → Skills → prompt caching → Memory → HumanInTheLoop → UnsupportedContent/ModelRefusal → ToolExclusion）。必需脚手架（文件工具/子代理分发）不可被 profile 剔除（graph.py:266-269、1012-1022）。
- **Sub-agent**：`task` 工具（description + subagent_type）同步阻塞委派；**默认上下文隔离**（子代理只拿任务描述，`subagents.py:929-930`），可选 **fork 模式**继承父会话（系统提示逐字节一致以复用 prompt cache）；结果经 ToolMessage + `Command(update=...)` 合并回父（仅合并确有变化的字段，防并行冲突）；异步委派走 Agent Protocol 服务器（start/check/update/cancel/list 五工具 + interrupt|enqueue 策略），`_parent_notifier` 在**整个嵌套链最顶层**按 run 去重上报成败，父线程 idle 时以 `multitask_strategy="reject"` 唤醒。
- **上下文管理**：summarization 中间件（触发 85% 输入预算/上下文溢出异常兜底；**非破坏性**——原始消息留存，压缩以 event 记录、视图重建；内联媒体先上传为 sha256 路径引用；被驱逐消息以 XML 落 `/conversation_history/<session>.md`；溢出重试前校验"请求必须严格变小"）+ 大工具结果 offload（head+tail 预览 + 分段读取指引）+ blob 内容寻址存储（下载后 sha256 校验才信任）+ `compact_conversation` 手动压缩工具 + `DeltaChannel` reducer 让 checkpoint 增长 O(N)。
- **HITL**：文件系统 7 工具全部可配 allow/deny/interrupt 规则；interrupt 走 LangGraph 原生中断，恢复用 `Command(resume=...)`，决策四种（approve/edit/reject/respond）；判定粒度到**每次调用的路径参数**（exact 工具查"请求路径 + symlink 解析路径"，bulk 工具按搜索子树与规则锚点重叠判定，并封堵 `path="."` 与 glob 重定向绕过）。
- **Skills**：SKILL.md + YAML frontmatter，progressive disclosure（索引常驻，正文按需 read），`include_tools` 声明的工具在技能被读取后才进入模型请求面。
- **Memory**：AGENTS.md 式来源文件经 backend 拉取，按次注入 system prompt（含信任边界声明）；写入完全委托模型 `edit_file`（提示词含更新清单与"绝不存密钥"）。
- **Profiles**：ProviderProfile（模型构造）+ HarnessProfile（运行时行为：prompt/工具可见性/middleware/默认子代理），内置 anthropic×3/nvidia/openai:codex，第三方走 entry points。

### 3.3 实证

官方 evals：136 个 eval（8 类）+ TrajectoryScorer（轨迹步数/工具调用断言）+ LLM-as-judge + 多试验统计 + Harbor（Terminal Bench 2.0，五种沙箱）+ 25 模型矩阵，结果发布于 LangSmith dashboard。无消融实验。

---

## 4. 参照系 B：代码级分析要点

（两路分区精读，全部断言有 file:line 证据；完整证据链见克隆件。）

- **装配**：`graph.py:920-1004` 主栈两段式；`graph.py:750-811` 子代理栈独立装配（不含 SubAgentMiddleware → **默认不嵌套**）；`graph.py:853-918` 自动注入 general-purpose 子代理并继承主代理 tools/permissions。
- **委派**：`subagents.py:736-1028` task 工具（pydantic schema 拒绝模型发明的未知参数键——注释记录真实事故）；同步阻塞、无深度计数（靠 recursion_limit 兜底）；`_parent_notifier.py` 顶层去重上报（进程内 dict，上限 1000，多 worker 失效）。
- **异步面**：`async_subagents.py` 五工具 + 父代理每轮模型调用前后 `_apull` 轮询（每任务 5s 超时）+ idle 唤醒。
- **后端**：`BackendProtocol`（ls/read/grep/glob/write/edit/delete/upload/download × sync/async）；StateBackend（线程内）/StoreBackend（跨会话，namespace 隔离禁通配）/FilesystemBackend（virtual_mode 路径锚定 + symlink 真实路径双查 + O_NOFOLLOW）/LocalShellBackend（**无隔离宿主 shell**，docstring 大段安全警告：virtual_mode 在 shell 面前不构成安全边界）/BaseSandbox（execute 为唯一原语）/LangSmithSandbox/CompositeBackend（最长前缀路由）。
- **rubric.py（1439 行）**：运行时质量闸门——调用方传入 rubric 文本，独立 grader 子代理对 transcript 结构化评分（satisfied/needs_revision/failed + 逐 criterion 判定），不达标注入反馈继续循环（默认最多 3 轮）；criterion 名单首轮冻结防标准漂移、grader 少报降级、transcript 视为不可信观察。
- **弱点**：巨文件（filesystem.py 4000 行/180KB、summarization.py 2472 行、async_subagents.py 1771 行）；权限逻辑散布三处；审批**无独立审计持久化**（仅 trace/检查点间接留痕）；`_apull`/溢出裁剪等无界 `asyncio.gather`；父通知去重不持久；eval judge 单模型无交叉校验；HITL 集成测试偏薄（3 例对 7 工具×4 决策矩阵）。

---

## 5. Neurova 现状基线

与上轮（CoworkOS 轮）相同，不再重复：蜂群派生主干 + 治理三明治 + TaskUnit/验收门/评审相位/依赖门控 + 审批链 L0/L1/L2 + span trace/事件账本 + 邮箱两阶段确认 + 机械完成闸门 + 多渠道/工作流/定时任务两翼；已知短板为压缩纪律、记忆准入、轨迹级评测判据（见 H 系登记）。

---

## 6. 逐维评测

> 每子项：deepagents 证据 → 得分；Neurova 现得分沿用上轮（括号内为 AutoSwarm 轮分数）。

### A. 协作形成
- **A1 团队组成与角色分配**：deepagents 子代理由调用方声明式定义 + 自动 general-purpose 兜底，无动态组队/贡献辩护 → **3**。Neurova 单层 spawn + list_agents 辅助（上轮 2）→ **2**。
- **A2 任务单元结构化**：deepagents task 工具仅 {description, subagent_type}，自由文本 → **2**。Neurova TaskUnit 七字段（2→）**4**。
- **A3 验收条件**：deepagents 无子代理结果验收门；rubric 中间件是调用方可选的循环自评（criterion 级、冻结防漂移）→ **3**。Neurova 验收门挂蜂群终态（3→）**4**。
- **A4 依赖与评审关系**：deepagents 无依赖门控；rubric 是可选自评非监督评审 → **2**。Neurova 依赖门控+评审相位（2→）**4**。

**A：deepagents 10/20，Neurova 14/20（上轮 9）。**

### B. 执行协调
- **B1 共享执行状态**：LangGraph checkpoint/interrupt/可恢复 + DeltaChannel O(N) → **5**。Neurova 内存 _runs+SQLite 台账+启动收敛（2→）**4**。
- **B2 单元生命周期**：异步五工具全生命周期 + 状态 reducer，但同步 task 无独立生命周期记录 → **4**。Neurova 6 态单源（3→）**4**。持平。
- **B3 依赖门控与前沿并行**：均无 → deepagents **2**，Neurova（1→）**4**。
- **B4 事件驱动交互与阻塞升级**：deepagents 父通知 + idle 唤醒 + 轮询补齐（无推送面）→ **4**。Neurova 邮箱回灌+escalate+卡死看门狗+审批链（3→）**4**。持平。
- **B5 结果集成**：deepagents ToolMessage+state 合并（无候选/CAS）→ **3**。Neurova integrationReport（2→）**3**。持平。

**B：deepagents 18/25，Neurova 19/25（上轮 14）。**

### C. 通信基础设施
- **C1 寻址/路由/邮箱**：deepagents 线程/命名空间 + Agent Protocol 远端任务，无持久邮箱 → **4**。Neurova 邮箱+广播+ACP（4→，H-1 后可靠性增强）**4**。持平。
- **C2 实时性**：deepagents 流式 + turn 边界轮询 → **3**。Neurova SSE/WS 流式+广播 → **4**。
- **C3 可靠性语义**：deepagents checkpoint 可恢复 + 异步结果持久在图状态，但父通知去重不持久、无两阶段确认 → **4**。Neurova 两阶段确认+台账闭合（3→）**4**。持平。

**C：deepagents 11/15，Neurova 12/15（上轮 11）。**

### D. 记忆与上下文共享
- **D1 跨 agent 上下文共享**：deepagents 隔离/fork 双模式 + state 合并 → **4**。Neurova 三通道回流 → **4**。持平。
- **D2 共享黑板/工作记忆**：deepagents 文件系统即共享黑板（后端可跨会话）+ 记忆注入，无检索 → **4**。Neurova 上下文池+MemCore → **4**。持平。
- **D3 历史压缩与成本**：deepagents 全库最强实践（非破坏性摘要事件/三层 offload/严格变小校验/O(N) checkpoint/prompt caching 协同）→ **5**。Neurova 3（持平上轮）。

**D：deepagents 13/15，Neurova 11/15（上轮 10）。**

### E. 治理与安全
- **E1 权限/审批（人在环）**：deepagents 按参数粒度 interrupt + 4 决策 + deny 规则 + 封堵两类绕过，但无审计持久化 → **4**。Neurova 审批链+governance ASK（3→）**4**。持平。
- **E2 工具面收窄**：deepagents profile 排除 + 技能渐进披露工具 + 路径权限 → **4**。Neurova 白名单+执行咽喉（4）**4**。持平。
- **E3 资源治理**：deepagents recursion_limit=9999、无并发上限、无预算闸 → **2**。Neurova 治理三明治 → **5**。**Neurova 明确优势**。

**E：deepagents 10/15，Neurova 13/15（上轮 13）。**

### F. 可观测与评测
- **F1 台账/trace/事件**：deepagents LangSmith 零侵入 tracing + rubric 评估记录，无本地台账 → **4**。Neurova 台账+trace_id+事件账本（3→）**4**。持平。
- **F2 基准评测 harness**：deepagents 136 eval + 轨迹效率断言 + LLM-judge + Harbor + 25 模型矩阵 → **5**。Neurova harness 已建但无轨迹级判据、真基线仅口径基线（2→）**3**。

**F：deepagents 9/10，Neurova 7/10（上轮 6）。**

### G. 异构与互操作
- **G1 多模型/多 provider**：deepagents 任意 LangChain chat model + 双层 profile + 25 模型实测矩阵 → **5**。Neurova 多 provider+渠道 → **4**。
- **G2 互操作协议**：deepagents MCP + Agent Protocol（异步子代理）+ ACP 目录 → **5**。Neurova ACP+MQTT+握手+MCP 客户端 → **4**。

**G：deepagents 10/10，Neurova 8/10（上轮 7）。**

### 6.x 总分表（四轮参照系汇总）

| 维 | Neurova（AutoSwarm 轮） | **Neurova（现）** | deepagents | AutoSwarm | CoworkOS |
|---|---|---|---|---|---|
| A 协作形成 | 9 | **14** | 10 | 20 | 13 |
| B 执行协调 | 14 | **19** | 18 | 23 | 18 |
| C 通信 | 11 | **12** | 11 | 11 | 14 |
| D 记忆与上下文 | 10 | **11** | 13 | 5 | 13 |
| E 治理安全 | 13 | **13** | 10 | 9 | 10 |
| F 观测评测 | 6 | **7** | 9 | 7 | 9 |
| G 异构互操作 | 7 | **8** | 10 | 9 | 10 |
| **合计** | 70 | **84（76.4%）** | **81（73.6%）** | 84 | 95 |

---

## 7. 差距与改进点（I 系，并入既有登记）

| # | 改进点 | 参照系做法 | 与既有登记的关系 |
|---|---|---|---|
| I-1 | **轨迹效率判据**：eval 断言"步数/工具调用次数"而非只判结果 | TrajectoryScorer：`.expect(agent_steps=N, tool_calls=M, tool_calls=[...])`，效率以 feedback 上报 | 并入 H-7 基线体系（harness 增加轨迹判据维度） |
| I-2 | **HITL 按参数粒度**：审批判定到每次调用的路径参数，exact/bulk 双判定并封堵绕过 | `_fs_interrupt.py` 谓词 + LangGraph interrupt/resume 四决策 | 并入审批链（现有 L0/L1/L2 之上加参数级 when 谓词） |
| I-3 | **技能渐进披露工具**：`include_tools` 声明的工具在技能被读取后才进入请求面 | skills.py `_plan_disclosure` + wrap_tool_call gate | 新增（本仓技能当前只注入提示词） |
| I-4 | **压缩纪律再获旁证**：非破坏性摘要事件 + offload + "重试必须严格变小" | summarization.py | 即 H-6（已登记待独立方案） |
| I-5 | **checkpoint 增长 O(N)**：DeltaChannel reducer | `_messages_reducer.py` | 远期（依赖运行时状态底座改造） |

**不可照搬项**：LangGraph/LangChain 运行时依赖（本仓自研运行时与产品面不同源）；recursion_limit=9999 + 无并发上限（治理三明治是本仓正确取舍）；审批无审计持久化（本仓台账/审计方向更对）；巨文件与三处散布的权限逻辑是反面教材。

---

## 8. 结论

1. deepagents（81/110）是"**库形态的优秀 harness**"：上下文工程与评测体系满分级，但协作机制（结构化任务单元/依赖门控/资源治理）与产品面（多渠道/工作流/观测台账）缺位——它验证了"middleware 组合 + 可插拔后端"路线的工程上限，也暴露了该路线在多 agent 协作机制上的天然空白。
2. Neurova（84/110）连续第二轮稳住对开源 harness 参照系的优势（AutoSwarm 84、deepagents 81），对 CoworkOS（95）的差距仍集中在执行可靠性工程与评测体系——与 H 系登记方向一致，无需改道。
3. 三轮累计的方法学收获：AutoSwarm 给机制、CoworkOS 给可靠性、deepagents 给封装纪律与评测判据；Neurova 的下一阶段应把 H-6（压缩纪律）与 I-1（轨迹判据）做成落地方案。
