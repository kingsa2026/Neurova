# 两份 FlowOrchestrator 的「先比后合」档案（2026-10-18，批 83 只读取证）

> 台账 D5（line 6088）登记的那条「两份 FlowOrchestrator 未比对」在此量清。
> 本卷**只读**：不改任何代码或测试。判定单位是**符号**，不是文件（本仓实测两份文件里都有半区死半区活）。
> 复算标记：✅＝主会话独立复算；◑＝子代理取证（给 `file:line`／commit，主会话未复算）。两者不混在同一个置信度里汇总。

---

## 一、范围与方法

比较对象（题面给的"两份同名类"）：

| 落点 | 行数 | 顶层符号数 |
|---|---|---|
| `neurova/collaborate/workflow/orchestrator.py` | 340 | `FlowOrchestrator`:19、`get_orchestrator`:338 |
| `neurova/core/flow_orchestrator.py` | 870 | 13 个类 ＋ `get_flow_orchestrator`:848、`process_conversation_flow`:853 |

方法：反向守卫前置 → 严格 AST 通道复算（相对导入按包路径解析）→ 剔九类伪命中 → 四条 git 配方取证 →
逐符号能力清点 → 现役替代验实质 → **运行时探针**（真 `create_app()` ＋ 真端点 ＋ 计数 wrapper ＋ 每个零读数配正控）。

执行事故如实记三处：
1. 主会话第一版通道复算的谓词太松（把 `from neurova.core import X` 也算进来），core 侧一度读出 **239 处**；
   改成只认「解析后的模块全名」与「模块名绑定」两种通道后，真数是 **1 处**。
   ⇒ 一个错误的宽谓词不会报错，它只是把噪声读成消费者——**这正是"谁在用"最容易被读高的方向**（形态集 283/268 同族）。
2. 子代理把 `collaborate/workflow/models.py` 的 `FlowContext` 判进"死半区"——**不成立**：活的
   `scheduler.py:260` 真在 `context = FlowContext()` 构造并传给 handler（:103/:358 的签名契约）。
   主会话按 `grep -c` 现场抓到并改判。⇒ ◑ 不得直接进主表，逐条要过 ✅。
3. 主会话为两份实现跑的第一支运行时探针，把"正控"错挂在 `scheduler.get_scheduler` 上——
   端点是 `from ... import get_scheduler`（导入期绑定），monkeypatch 模块属性打不动它，
   那条正控恒 0 会被读成"调度器也没人调"。改为**显式各调一次**证 wrapper 能产生非零，
   `sys.modules` 在场性用同包活体 `scheduler`／`neurflow.execution_engine` 做正控。

---

## 二、结论概览（三态各自行数）

| 判定 | 对象（符号级） | 体量 |
|---|---|---|
| **删（候选）** | core 那份 13 符号整体（无任何生产通道）；collaborate 那份 `FlowOrchestrator`＋`get_orchestrator`；`workflow/models.py` 的 `FlowPhase`/`FlowEvent` 与 `FlowContext` 的编排方法群 | 870＋340＋约 120 行，另加两份专用测试 1005＋`test_refactor_imports.py` 相关格 |
| **接线** | **0 条**——需求不成立（见 §五） | — |
| **需人裁** | ①唯一全仓独有能力「按 `required_capabilities ⊆ capabilities` 为步骤挑 agent」；②`neurova/collaborate/models.py`(150)＋`template.py`(373) 这座相邻岛要不要与本次一起收 | 523 行 |
| **不可动（活）** | `workflow/models.py` 的 `FlowContext`（本体）/`ScheduledTask`/`compute_next_run`；`workflow/scheduler.py`(426) | — |

净 LOC 一律标**候选**：正式数字只能在退役批次按 `git show --numstat` 逐文件复算（本卷不动码）。

---

## 三、逐项比较（教义 第 7 条要求的那一格）

| 维度 | collaborate 那份 | core 那份 |
|---|---|---|
| 语义颗粒 | 流程实例簿记：创建/启动/逐步执行/完成/失败/取消/列出＋统计 | 12 相位**仿真流水线**：会话→上下文→记忆缓存→写→检索→工具→反馈→经验→进化→睡眠→冲突→元认知 |
| 正确性 | `start_flow` 校验真做（`WorkflowDefinition.validate`）；但先 PLANNING 立刻被 EXECUTION 覆盖，无规划工作；`_find_agent_for_step` 无注册者时静默跳步，`start_flow` 仍 `return True` | `_run_phase` 里两个占位相位恒返 ctx 却记 `success=True`，把元认知 quality 抬高；`retrieve()` 的 `query` 形参体内从未使用＝检索假实现；`evolve()` 只吐两条硬编码中文串，不改任何技能或参数 |
| 覆盖面 | 步骤依赖门（运行期完成态）、按能力分配 agent（**全仓独一**）、超时字段读了吗——**没读**（`TaskStep.timeout_seconds` 全程未取） | 覆盖面最大，但每一项都有现役实现且更强（§四） |
| 可测性 | 专用测试 0 档；只有形状检阅 `test_refactor_imports.py:118-121` | 专用测试 1005 行 81 格**今天全绿**，但抽样即见"枚举 13 个值存在""枚举数量=13"这类**只断形状**的格；且**不在受保护子集**（CI 不拦） |
| 调用方（✅ 复算） | **1 处**＝包门面 `workflow/__init__.py:9` 再导出（导出面≠消费者） | **1 处**＝`tests/unit/core/test_flow_orchestrator.py:22`（自家测试） |
| 运行时（✅ 探针） | **在 `sys.modules` 里**（门面连带），但 17 条 workflow/neurflow 路由跑完 `get_orchestrator` 计数 **0**；显式调一次⇒1（正控） | **不进 `sys.modules`**；5 路真端点＋17 条路由后 `get_flow_orchestrator`/`process_conversation_flow` 计数 **0** |
| 可替代性 | 事件面/依赖门/DAG 校验 → neurflow 全有更强等价；仅"按能力挑 agent"独一 | 12 项能力逐项有现役实现（§四） |

**比完的结论**：这不是"两个都在服役、挑一个留"。两份都是**同一场脚手架期留下的骨架**，
其中一份（collaborate）被门面连带加载所以"看着活着"，另一份（core）覆盖面最广但每项能力都已被
现役实现取代且实现里有多处假做。**真正的取舍不在两份之间，而在"这份独有能力要不要留"**（§五）。

---

## 四、现役替代（验实质，不看存在）

| 能力 | 现役落点与在路证据 | 覆盖判定 |
|---|---|---|
| 工作流/DAG 执行 | `neurflow/execution_engine.py:162 WorkflowExecutor`＋`get_workflow_executor():1548`；装配于 `api/app.py:1061-1072`、`neurflow_api.py`、`neurflow_triggers.py:48,296`、`collaboration_api.py:900,951,1046`、`agent_core.py:946-948`；`/api/v1/neurflow/*` **54 条路由**（本轮现读）；环检测/Kahn 拓扑/图校验在 `dag.py:18-138,168-189,212-271` | **超集** |
| 睡眠巩固 | `memory_layer/sleep.py:116 SleepConsolidation`（`agent_core.py:1363/1374` 构造、`post_chat_pipeline.py:3130` 每 10 回合、`api/endpoints/sleep.py` 13 端点）＋写回 `sleep_writeback.py:19`（≥2 源才新增、按闲置降温） | core 那份**合并/降温/写回全缺**；仅"否定词四策略表"独有不落盘 |
| 元认知 | `meta_cognition_layer/self_model.py`＋`ledger.py`，`/v1/metacognition` 注册于 `endpoints/__init__.py:295`，实调 `metacognition_api.py:164`；相位成功率的现役等价是 `core/metrics.py`（`app.py:711` Prometheus）与 `core/agent_run_ledger.py` | **维度不同，部分缺**（不是等价替代） |
| 工具反馈 | `tool_executor.py:1107 execute_tool` ＋ `agent/loops/base.py:214`→metrics | 超集 |
| 经验/进化 | `evolution/skill_experience.py`（`agent_core.py:1610`、`skill_pool_api.py:684/709/720`，带 DB 与审批闸）、`evolution/experience_feedback.py:379` | 超集 |
| 消息流转/上下文 | `conversation_context.py:40`（`agent_core.py:638`）、`context/builder.py`（装配于 `context/orchestrator.py:1135`、`injector.py:1016`）、缓存单源 `core/cache.py:374` | 超集 |
| 记忆存取/冲突 | `memory_layer/manager.py:2415 add_memory`/`:1670 recall`；`memory_layer/conflict.py`、`knowledge_sharing.py:41-44` keep_both/supersede_old | 超集 |
| 按能力给步骤挑 agent | **无替代**。`neurflow/models.py:86 provider_capability` 是模型供应商选择，不是 agent 分配；`protocols/capability_discovery.py` 的 CapabilityMatch 只被 `agent/matrix/agent_matrix.py:17,136` 取用（另一座岛，未接入编排） | **零替代** |

（以上除标 ✅ 的行外，均属 ◑ 子代理取证：给了 file:line 与调用链，主会话未逐条复算。）

---

## 五、三态票

**甲｜只退"死的那一半"，独有能力留在原地不接**（最小、语义无变化）
删 core 那份 870 行＋其 1005 行专用测试；collaborate 那份 `orchestrator.py`(340) ＋ `workflow/models.py`
的 `FlowPhase`/`FlowEvent` 与 `FlowContext` 编排方法群；同批改 `test_refactor_imports.py` 里被这些路径钉住的形状格。
保留 `FlowContext` 本体、`ScheduledTask`、`compute_next_run`、`scheduler.py`。
"按能力挑 agent"这项能力**随 orchestrator 一起消失**，且今天无人需要它（0 调用方）。
代价：以后要做"多 agent 按能力分工执行 DAG"时，得在 neurflow 侧新建，而不是从这两百里挑一份接上。

**乙｜甲 ＋ 把这项独有能力并进 neurflow（推荐）**
在 neurflow 的节点/执行器上补"按 `required_capabilities ⊆ agent capabilities` 为节点挑 agent"，
落点候选：`neurflow/models.py:86` 已有 `provider_capability` 字段位（语义要分清，别混用）、
派发侧与 `agent/team.py` 的角色→成员（经 `api/endpoints/acp_api.py:151-162` 可达）对齐。
先立判据再动手，走"能力字段单源＋真派发闭环"的形状。
代价：这是**新增能力**（净 LOC 为正），要产品侧认这条需求；比甲多一批。

**丙｜两份都留，只把假做改如实**
把 `start_flow` 的"无 agent 可派仍 return True"、core 的占位相位记 success、`retrieve()` 不看 query、
`evolve()` 的硬编码建议等改成显式 `not_supported`/点名缺失。
它治谎不治岛：岛还在，门面还在连带 import 一份没人调的编排器，下一场批量事件还会拿它当"现役"。

推荐 **乙**；若需求不被产品认领，退到 **甲**（甲不含任何"以后可能要"的预留）。

**决策影响面**（乙）：接线后实现的是"多 Agent 按能力分工执行同一张 DAG"；数据从节点声明的
`required_capabilities` 来，经能力注册表（今天**没有任何生产者往里注册**——`register_agent`/`register_step_handler`
全仓零调用，两张表按构造恒空）到 agent 选择，落进执行结果；影响 `neurflow/execution_engine.py`、
`neurflow/models.py`、`agent/team.py`、`api/endpoints/neurflow_api.py`。不接线留下：这项独有能力仅存于 340 行骨架里，
随退役永久消失。不可逆点＝骨架与 `collaborate/models.py` 的 `TaskStep.required_capabilities` 字段一并删除后，
重建要从 schema 起。

---

## 六、事件分组（这条最有价值的产出）

两份不同名文件**同出一场批量事件**：`1832a12b`(2026-06-03) 一笔建整个 `neurova/collaborate/` 包
（`--stat` 实测 7 档 ＋1434 行，门面 `workflow/__init__.py` 的再导出**同笔**写进）；
core 那份建档于 `7835c367`(2026-06-04「pyc 骨架恢复 - 全量导入修复」)——**同一个号也正是 D3 那座岛的出生事件**（§6-308）。
即：这两份"重复实现"不是渐进腐烂，是同一次骨架期一次性提交留下的未收尾。

来历形态（git 实证，主会话复算关键几条 ✅）：
- collaborate 支：`git log -S "get_orchestrator" -- neurova/` **仅命中 `1832a12b` 一笔** ⇒ **引入即未接线**，
  没有"接入后被摘除"的提交可寻。
- core 支：逐符号 pickaxe 命中集恒为 `{7835c367, 8a91e721, 4a3c9380}`，且
  `from neurova.core.flow_orchestrator import` 这条 import 只由 `4a3c9380`(2026-09-04 测试入库) 添加
  ⇒ 15 个符号**全部"从未被接进活链路"**（◑，主会话未逐符号复跑）。
- 两份后来都**吃过维护成本**：`d63b3c66`(2026-10-07) 懒建单例双检锁收口把两个工厂都改了、
  `b84434cf`(2026-09-21) token 尺子收口扫到了 core 的 `_count_tokens`（✅ 见各笔）。
  ——死码不只是占地方，它每年要被机械修一遍。

---

## 七、跨模块共性

1. **门面再导出把死码伪装成"在场"**：collaborate 那份因为 `__init__.py:9` 而进了 `sys.modules`，
   纯 grep `sys.modules` 会判它"活着"；只有计数 wrapper 才分得开"加载"与"被调用"。
2. **"有专用测试"最容易被读成活证据**：1005 行 81 格全绿，但抽样即见枚举形状断言，且**不在受保护子集**——
   既不被 CI 拦，也不证明有任何生产者。
3. **形状检阅档是退役的隐性债**：`test_refactor_imports.py` 断的是"从新路径 import 得到"，
   它把 8 个待退役符号钉成"不许消失"的样子，退役时必须同批改判，否则留下恒真守卫。

---

## 八、审计中发现的缺陷（单列，不折算成简化收益）

以下都随退役批次一并消失或被现役实现覆盖，**但必须先立红灯再动**，且不与收口捆同一次改动：

- D11 `core/flow_orchestrator.py:304` `MemoryCoordinator.retrieve(query,…)` 的 `query` **体内从未使用**
  （只按 category/温度过滤）＝挂了检索签名不做检索。（✅ 主会话亲读）
- D12 `:440 evolve()` 的"进化"只返回两条硬编码中文串，不改任何技能/参数/DB。（✅）
- D13 `:770/:774` 两个占位相位恒返 ctx 而 `:731` 仍记 `success=True` ⇒ 元认知 quality 被空相位抬高。（◑）
- D14 `:469` 睡眠协调器：相似度用字符集 Jaccard(`:572`)、冲突判定用剥"不"后的二元组(`:502-508`)
  ⇒ **两套口径自相矛盾**；四策略里 latest/keep_both/flag 全产 `merged_content=None`，无写回面。（◑）
- D15 `:372` `user_rating` 默认 0.5 使 `should_learn` 恒 False ⇒ 反馈链路永不触发。（◑）
- D16 `collaborate/workflow/orchestrator.py:117→262-264` 无 agent 可派时静默跳步，
  `start_flow:125` 仍 `return True` ⇒ **依赖缺失却报成功**；`:264` 还覆写 `create_flow:72` 传入的 participants 角色映射。（✅ 读码确认）
- D17 同文件 `TaskStep.timeout_seconds`／`input_requirements`／`output_produces`／`optional`
  在这份编排器**全程未读** ⇒ 超时与数据契约是装饰。（◑）
- D18 `workflow/models.py` 的 `Severity` 全仓仅作字段默认值(`:57`)，无任何赋值点 ⇒ 死字段。（✅ 按包含关系：本模块唯一通道是自家测试）

---

## 九、未覆盖与存疑

- `NeurUI/src` 侧是否**间接**展示这两份的读数（本卷只查了 Python 通道与 OpenAPI 路由，未反查前端 API 契约名）。
- `neurova/collaborate/models.py`(150)＋`template.py`(373) 这座相邻岛：主会话复算到"只有彼此＋门面再导出＋
  `test_refactor_imports.py:76-106` 形状检阅"，**但没做运行时反证**，故本卷不判它——登记为 §五甲/乙落地时的范围问题。
- core 那 12 项相位在真实链路里的**等价覆盖率量化对比**（只做了定性：逐项有现役实现）。
- `4a3c9380` 之外是否还有被 squash 掉的接线尝试（未查 reflog／远端分支）。

---

## 十、复算方法与伪命中（九类逐条过）

同名词不同物（`collaboration/neurflow/models.py` 另有一套 `WorkflowDefinition`；`context/orchestrator.py` 的
`ContextOrchestrator`、`evolution/rsi/orchestrator.py` 的 `RSIOrchestrator`、`neurflow/execution_engine.py:162`）、
相对导入指向同名他文件（`from .models import` 在 `collaboration/` 里命中的是自家 models）、
docstring/注释提及（`idle_tracker.py:272`、`test_dreamReportSeamIsNotFabricated.py:40`、
`protocols/__init__.py:12`）、门面再导出≠消费者、动态装载（`import_module`/`__import__` 58 处候选逐条读，
无一命中这两个模块）、按文件判死（本卷全部按符号裁定）、"有测试"当活证据（1005 行档抽样）、
包/文件同名遮蔽（无）、"诚实空"自辩注释（未遇）。
体量口径：`git ls-files <path> | xargs wc -l`（源码文本行）。
反向守卫：`tests/` 里 flow/orchestr 相关「不得删/不是死代码/防止误删」**0 命中**（✅）。
