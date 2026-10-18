# `neurova/collaborate/` 整座岛档案（2026-10-18，批 84 只读取证）

> 起因：§6-311（D5 比卷）在"未覆盖"里明写着——相邻岛 `collaborate/models.py`(150)＋`template.py`(373)
> 复算到"只有彼此＋门面再导出＋形状检阅"，但**没做运行时反证故不判**。本卷把整座包量清。
> 只读：不改任何代码或测试。判定单位是**符号**。复算标记 ✅＝主会话独立复算／◑＝子代理取证未复算。

---

## 一、范围与方法

对象＝`neurova/collaborate/` 全部 6 个源码文件（`git ls-files | xargs wc -l` 口径，共 1672 行）：

| 文件 | 行数 | 公共符号 |
|---|---|---|
| `__init__.py` | 21 | 门面再导出 |
| `models.py` | 150 | `TemplateType`、`AgentRole`、`TaskStep`、`WorkflowDefinition` |
| `template.py` | 373 | `CollaborationTemplate`、`TemplateManager`、`get_template_manager` |
| `workflow/__init__.py` | 24 | 门面再导出 |
| `workflow/models.py` | 338 | `FlowPhase`、`FlowEvent`、`FlowContext`、`ScheduledTask`、`compute_next_run` |
| `workflow/orchestrator.py` | 340 | `FlowOrchestrator`、`get_orchestrator` |
| `workflow/scheduler.py` | 426 | `AgentScheduler`、`get_scheduler`、`register_action_handlers` |

方法：AST 按符号清点外部取用（区分"门面再导出"与"真消费者"）→ 反向守卫 grep → **运行时探针**
（真 `create_app()` ＋ 真端点 ＋ 计数 wrapper ＋ 正控）→ **拖拽实证**（只 import 活模块，看岛是否被带进
`sys.modules`）→ git 配方取证 → **双源分叉按字节比对**（difflib 量化，不靠"看起来一样"）。

---

## 二、结论概览

- **活（不可动）**：`workflow/scheduler.py` 三个符号 ＋ `workflow/models.py` 的 `ScheduledTask`/`compute_next_run`/
  `FlowContext`（本体）＝约 **764 行**。生产通道＝`api/endpoints/scheduler.py:29-30,298,405` 与
  `api/endpoints/agent_package.py:68,110`（✅ 复算）。
- **死（候选退役）**：`models.py` 4 符号 ＋ `template.py` 3 符号 ＋ `workflow/orchestrator.py` 2 符号 ＋
  `workflow/models.py` 的 `FlowPhase`/`FlowEvent` 与 `FlowContext` 的**编排方法群**＝约 **929 行**。
- **接线 0 条**：需求侧全都有现役承载（模板＝`agent/templates/collaboration_template.py`；
  角色→成员派发＝`agent/team.py` 经 `api/endpoints/acp_api.py:151-162` 可达；
  流程执行＝neurflow 的 54 条路由；定时/触发＝本包活的 `scheduler` 自己）。
- **需人裁的不是"要不要留这块能力"，而是"退役范围画在哪条线"**（§五甲／乙／丙）。

净 LOC 一律标**候选**，正式数字只能在退役批次按 `git show --numstat` 逐文件复算。

---

## 三、逐项档案（五字段）

### C1 `neurova/collaborate/models.py`（150 行）✅
- 原功能：`TemplateType`:13（模板分类枚举）、`AgentRole`:23（角色枚举）、`TaskStep`:38（步骤声明，含
  `timeout_seconds`/`required_capabilities`/`input_requirements`/`output_produces`/`optional` 等字段位）、
  `WorkflowDefinition`:71（步骤表＋`validate()`：重复 step_id／未知依赖检测在 `:113` 起）。
- 关键入口：`TemplateType`、`AgentRole`、`TaskStep`、`WorkflowDefinition`（无工厂函数）。
- 来历：`1832a12b`(2026-06-03) **一笔建整个 `neurova/collaborate/` 包**（`--stat` 实测 7 档 ＋1434 行）
  ⇒ **引入即未接线**；此后无接线、也无"接入后被摘除"的提交可寻。
- 现役替代：同名四件套在 `neurova/agent/templates/collaboration_template.py:21,31,46,79` 各有一份，
  **且那一份被真消费**（`agent/team.py:25` 取 `AgentRole`）；neurflow 另有一套语义不同的
  `WorkflowDefinition`（`collaboration/neurflow/models.py`）——**同名词不同物，已按伪命中剔除**。
  `TaskStep.timeout_seconds` 等四个字段位在全仓**没有任何生产者**（`collaborate/workflow/orchestrator.py`
  是唯一读者，而它自己也是死的）。
- 判定：**删**（有现役实现顶上，且这一份从未被接进活链路）。若乙案要保留"按能力派步骤"的 schema，
  那一项属于 C2/C3 的范围，不构成本档保留理由。

### C2 `neurova/collaborate/template.py`（373 行）✅
- 原功能：`CollaborationTemplate`:22（角色分配 `assign_role`:60/`unassign_role`:65/`get_role_agents`:56、
  能力汇总 `get_required_capabilities`:72、结构校验 `validate`:79、序列化 to_dict/to_json/from_dict/from_json）；
  `TemplateManager`:201（注册/注销/取/列（按类型与标签双索引）/搜索/克隆）；`get_template_manager`:362（懒建单例）。
- 关键入口：`TemplateManager`、`get_template_manager()`。
- 来历：同 `1832a12b`，引入即未接线。
- 现役替代：**不是"另一份实现"，是同一份的双胞胎**——与 `agent/templates/collaboration_template.py`
  的 `CollaborationTemplate`＋`TemplateManager` 段逐行比对：**350 行里 346 行相同**，`difflib` 相似度 95.7%，
  差异全是文件头与活支多出的预设模板（活支相对死支 ＋146/−9）。
  活支在演进、死支自 2026-06-03 冻结。真消费链在活支侧（`agent/team.py:25`）。
- 判定：**删**——这是教义 第 6 条的纯双源（同一事实两份定义），且**"取长补短"无事可做**：
  活支已是死支的超集。合并动作＝删除，不需要迁移。
- 附注（要认的不对称）：活支那份的 `get_template_manager()` 同样**零生产消费者**——那是
  `agent/templates/` 的另一格（本卷不判，登记为 D20）。

### C3 `neurova/collaborate/workflow/orchestrator.py`（340 行）✅
- 见 §6-311 档案（`audit-reports/flow-orchestrator-comparison-2026-10-18.md`）：真通道 1 处＝包门面；
  `get_orchestrator` 在 17 条 workflow/neurflow 路由上计数 **0**（显式调一次即 1＝正控）；
  无 agent 可派时静默跳步仍 `return True`。
- 本卷只补一条**新事实**（§6-311 未涵盖）：它**在每次 app 启动时被拖进 `sys.modules`**（见 C5）。
- 判定：**删**（唯一独有能力"按 `required_capabilities ⊆ capabilities` 挑 agent"已在 §6-311 单独出票，
  不在此重复判）。

### C4 `neurova/collaborate/workflow/models.py`（338 行）✅ 半区文件
- 活半区：`ScheduledTask`:240、`compute_next_run`:198 → `api/endpoints/scheduler.py:29,298` 真消费；
  `FlowContext`:47 的**本体**→ 活的 `scheduler.py:260` 真在 `context = FlowContext()` 构造并传给 handler
  （签名契约在 `:103/:358`）。**上一场的子代理把 `FlowContext` 误判进死半区，已改判**——
  ◑ 不得直接进主表，这条就是那条纪律的现场用例。
- 死半区：`FlowPhase`:15、`FlowEvent`:29，以及 `FlowContext` 的编排方法群
  （`add_event`:81、`set_phase`:94、`complete_step`:107、`is_step_completed`:129、`to_dict`:173 等）
  ——外部按名取用只有 `tests/unit/test_refactor_imports.py:130-141,173-175` 的形状检阅。
- 判定：**接线不可、整删不可** ⇒ 需人裁的是**切法**：退役死半区要求 `FlowContext` 瘦身成
  "调度器用得上的那几个字段"，这是改现役符号的形状，必须走红→绿＋A/B（不属"删文件"那一类）。

### C5 两个门面 `__init__.py`：整座岛挂在**每次启动路径**上 ✅（本卷最有价值的一条）
- 实测：干净子进程里**只**`import neurova.collaborate.workflow.scheduler`（那是活的、被端点真用），结果
  `neurova.collaborate`、`neurova.collaborate.models`、`neurova.collaborate.template`、
  `neurova.collaborate.workflow.orchestrator` **全部进 `sys.modules`**。
  机制：包门面 `collaborate/__init__.py:8-9` 与 `workflow/__init__.py:8-9` 无条件再导出整座岛，
  而 Python 导入子包必先执行父包 `__init__`。
- 后果量化：一次 `import scheduler` 连带执行 **929 行死码的模块体**（含 4 个 dataclass、
  2 个枚举、2 个单例工厂、`from neurova.core.logger import get_logger` 等）。这不是"占地方"，
  是**每次进程启动都在付出的真实成本**＋下一个人读 `neurova/collaborate` 时被引导成"这里有协作实现"。
- 判定：**接线**（唯一一条）——门面自身不是死码，它做错的是"把死码声明成公共面"。
  修法与退役同批：门面只再导出活符号（`AgentScheduler`/`get_scheduler`/`register_action_handlers`/
  `ScheduledTask`/`compute_next_run`/`FlowContext`），死符号连同定义一并退。

---

## 四、事件分组

整座包只有**一次出生事件**：`1832a12b`(2026-06-03「feat: 完善项目结构，确保所有功能模块完整提交」)
一笔 ＋1434 行、7 档同时创建，门面再导出**同笔写进**——即"门面把死岛挂上启动路径"不是后来漂变的，是出生时就这样。
此后本包只被机械扫过：`7835c367`(06-04 pyc 骨架恢复，与 §6-308 那座岛、core 那份编排器同号)、
`7f8c7660`(06-25)、`d63b3c66`(2026-10-07 懒建单例双检锁收口——**又给死码修了一遍**)。

**未完成事件的指纹**：同一批里 scheduler 一支后来被接进端点（活了），orchestrator/template/models 一支
从没接上（死了）——所以"整包收干净"不能一刀切，必须按符号切（C4/C5 就是这条线)。

---

## 五、三态票（推荐乙）

- **甲｜只删两档整文件**：`models.py`(150)＋`template.py`(373)＋`workflow/orchestrator.py`(340) ＝ **−863 行**，
  加改门面与 `test_refactor_imports.py` 相关形状格。
  留 `workflow/models.py` 原样（含它的死半区）。代价：`FlowPhase`/`FlowEvent` 还在，
  `FlowContext` 还挂着一群没人调的编排方法——**门面问题只解决三分之二**。
- **乙｜甲 ＋ `workflow/models.py` 按符号切半区（推荐）**：同批把 `FlowPhase`/`FlowEvent` 与 `FlowContext`
  的编排方法群退役，`FlowContext` 瘦身到调度器实际用的字段面。候选 −929 行（含甲的 863）。
  差别要说清：**切到 C4 就是改现役符号** ⇒ 必须"先立判据（钉住 scheduler 用得到的那几个字段与行为）
  →再瘦→A/B→活体"，不能当删文件做。这一条也是本票唯一有回归面的一半。
- **丙｜只做门面**：把两个 `__init__.py` 改成只导出活符号（岛仍在，但不再挂在启动路径上）。
  它修的是 C5 那一条，最省；死码本体留着，下一场批量事件仍会把它当现役。

**决策影响面**（乙）：改的是"协作模板/工作流步骤声明/流程编排"这三件事在仓库里的**唯一表示**归属——
退役后：模板＝`agent/templates/collaboration_template.py`（已含活消费链）、步骤与角色 schema＝同处、
流程执行＝`collaboration/neurflow/*`（54 条路由）、定时与触发＝本包活的 `scheduler.py`。
数据流不变：`api/endpoints/scheduler.py` 的 `ScheduledTask` 仍从 `collaborate/workflow/models.py` 取，
`agent_package.py` 仍取 `get_scheduler`。不可逆点＝`TaskStep.timeout_seconds`/`input_requirements`/
`output_produces`/`optional` 四个字段位随 C1 一并消失；若将来要做"带超时与数据契约的步骤编排"，
重建要从 schema 起（今天这四个字段位**无任何生产者，也无任何读者**——唯一的读者就是死的 orchestrator）。

---

## 六、审计中发现的缺陷（单列，不折算成简化收益）

- **D19 包门面把整座死岛挂在每次进程启动路径上**（✅ 拖拽实证，C5）。这与 §6-42/批 43 那族
  "门面 None 占位符/零消费者再导出"同根因，但本条的危害不是"门面说谎"，是**启动成本与读者预期**。
- **D20 `agent/templates/collaboration_template.py:502 get_template_manager()` 零生产消费者**（✅ 按名复算：
  除自家模块与 `agent/templates/__init__.py` 再导出外无取用）。它是 C2 那份活支的双胞胎，
  所以本条只在"模板能力到底有没有人用"这一问上有意义——**登记，不在本卷判**（判它要先证明
  需求侧有没有"协作模板注册表"这条产品能力，属产品语义）。
- **D21 双源分叉无守卫**：两份 `CollaborationTemplate`/`TemplateManager` 350 行里 346 行相同，
  仓库里没有任何判据拦"同一份逻辑被复制第二份"（教义 第 6 条靠自觉）。要落成会红的格子，
  形状应是"同一 `class` 名＋同一方法集合的实现在全仓不超过一处"——**这类判据容易把
  合理的同名单子类一起抓进来，写之前得先量命中面**（本卷未量，登记）。

---

## 七、未覆盖与存疑（原样列出，不并进主表）

- 前端：`/api/v1/builder/templates` 由 `api/endpoints/builder.py`（prefix `/v1/builder`）服务，
  未逐条确认它是否与"协作模板"是同一业务概念；若是，则 C2 的替代还有一处（更支持退役）。
- `collaborate/workflow/scheduler.py` 的活度只证到"端点 import 且路由在册"，**未跑计数 wrapper**
  （它有没有被真触发过是另一问；本卷只要求它"活着所以不动"）。
- `tests/unit/collaboration/*`、`tests/unit/projects/test_teams.py` 与 `test_collaboration_isolation.py`
  到底测哪一份实现，未逐档核。
- D21 那条守卫的命中面未量。

---

## 八、复算方法与伪命中（逐类过）

同名词不同物（neurflow 的 `WorkflowDefinition`／`agent/templates` 的 `AgentRole` 与 `collaborate/models.py`
的是两套；`protocols/__init__.py:12` 是 docstring 示例不是 import——真 import 在 16-24 行）；
相对导入指向同名他文件（`collaboration/**` 里的 `from .models import WorkflowDefinition` 命中自家 models，
不是 `collaborate/models.py`）；包门面再导出≠消费者（本次**全部按"外部按名取用"重算，把 `__init__.py` 单列**）；
按文件判死（C4 就是反例）；"有测试"当活证据（`test_refactor_imports.py` 本轮现数 **29 格**：24 格是
`assert X is not None`，其余是 `callable(...)`／枚举值这类形状断言——**没有一格触行为**）；
动态装载（`import_module`/`__import__` 候选逐条读，无一指向本包死半区）；
注释/docstring 提及（`agent/team.py:4` 的"复用 collaboration_template.AgentRole"是沿革说明，
真通道在 `:25`）。体量口径＝`git ls-files <path> | xargs wc -l`。
反向守卫：`tests/` 里 template/collaborat 相关「不得删」**0 命中**（✅）。
**受保护子集（✅ 逐条 `grep -c "^<path>$"` 现读，本卷第一版此处写错过、已纠）**：本包相关的四档测试
**一档都不在册**——`tests/unit/collaboration/test_workflow_scheduler.py` 0、`tests/unit/test_refactor_imports.py` 0、
`tests/unit/api/test_scheduler_api_auth.py` 0、`tests/unit/api/test_notifications_negative_screen_bridge.py` 0。
⇒ 退役死半区 CI 不会红；但同一件事也说明**活的那一半同样没有 CI 保护**，所以退役批次里
"CI 没红"不能当"改对了"的证据，必须另立判据（这条与形态集 256"没有产物留痕的读数一律当没跑过"同族）。
