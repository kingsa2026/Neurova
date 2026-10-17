# `shared_core.ExecutionEngine` 死码子树溯源档案（2026-10-17）

> 只读档案。**本卷不改任何代码或测试**；判定靠证据，不靠试删。
> 触发源：简化审计台账 §6-300「其余仍开」那条登记的 `ExecutionEngine` plan/execute_tool 子树，
> 此前只写过"疑似整体无消费者"，未按核心原则第 7 条出五字段档案。本卷补齐。

## 1 范围与方法

范围：`neurova/shared_core/execution_engine.py`（现读 490 行）里 `ExecutionEngine` 的**方法级**符号，
加它们各自牵出的下游模块（`execution_engine/workflow_engine.py` 356 行、`execution_engine/execution_monitor.py` 496 行）。
判定单位是**符号**，不是文件（AGENTS §1 教义第 5 条／核心原则第 7 条）。

方法七步全跑：① 符号清点 → ② 测试侧反向守卫前置 → ③ 零消费者复算（剔九类伪命中）→
④ 来历（四条 git 配方）→ ⑤ 原功能逐能力 → ⑥ 现役替代**验实质**（含运行时探针）→ ⑦ 五字段档案＋三态判定。

**运行时探针**（不是 grep）：给 `ExecutionEngine` 全部 15 个方法加计数 wrapper、再包 `__new__`／
`_init_components`／工厂 `get_execution_engine()`，然后跑真 `create_app()` + lifespan + 真 HTTP 栈
（5 个 monitor 端点、工具列表面、`POST /tool-layers/tools/execute`、neurflow 执行端点）。
身份用生产签 token 函数 `create_access_token({'sub':…, 'role':'admin'})`（monitor 那三条要 `require_admin()`）。
数据根走 `isolatedDataRoot()` 单点；探针落仓库根 `.tmp_*`，跑完即删，仓内 `data/` md5 复证不变（`d1ef4e99bd9f`）。

读数（原文）：

```
READOUT {'constructs': {'ExecutionEngine.__new__': 1, 'ExecutionEngine._init_components': 1},
 'get_execution_engine_calls': 2, 'monitorRoutesRegistered': 5,
 'calls': {'execute_plan': 0, 'execute_tool': 0, 'execute_workflow': 0, 'get_execution_result': 0,
 'list_executions': 0, 'cancel_execution': 0, 'register_tool': 0, 'set_event_bus': 0,
 'get_execution_monitor': 2, '_execute_node': 0, '_execute_plan_nodes': 0, '_execute_simple_plan': 0,
 '_evaluate_condition': 0, '_get_next_node': 0, '_call_llm': 0}, …}
```

三条 monitor 路由在 `app.openapi()["paths"]` 里在册（`monitorRoutesRegistered: 5` 是 `/api/v1/monitor` 前缀的路径总数）。
另：`POST /api/v1/neurflow/workflows/{workflow_id}/execute` 打过去回 404，而 `execute_workflow: 0` ——
**neurflow 端点不经这把引擎**，"P1-7 收敛契约"那条转发入口在生产里没有一条来路。

## 2 结论概览（按符号，不按文件）

| 态 | 符号数 | 候选行量（AST `lineno..end_lineno` 求和，**未含**空行/装饰器，正式数字须按 `git show --numstat` 复算） |
|---|---|---|
| 删 | 13 个方法 + 1 个 dataclass | 246 |
| 需人裁 | 1 个方法 + 1 个模块级 helper（牵出 legacy 模块 356 行的退役范围） | 93 |
| 接线 | 0 | 0 |
| 在役（不许动） | 3 | `get_execution_monitor`(3)／`__new__`／`_init_components` |

在役面只有 `get_execution_monitor` 一条。但**它一旦成立就带着整把引擎的装配**：`_init_components`
每轮真服务里构造 1 次，其中 `ToolEngine()` 与 `WorkflowEngine()` 各被 new 出来供那三条死路使用——
批 68 量到的"真装配下 ToolEngine 构造 2 次"，第二把就是这里。

## 3 逐条档案（✅ ＝ 主会话按 import 通道独立复算）

### A1 `neurova/shared_core/execution_engine.py:136-244`（104 行）✅ plan 子树

- 原功能：按 `plan` 字典逐节点执行——`execute_plan`(:136) 建 `ExecutionResult` 记账 → `_execute_plan_nodes`(:167)
  认 `execution_order` 或顺序跑 → `_execute_simple_plan`(:182) → `_execute_node`(:187) 分 `tool`/`workflow`/`condition`
  三种节点；`_evaluate_condition`(:225) 判条件；`_get_next_node`(:215) 取下一节点。
- 关键入口：`ExecutionEngine.execute_plan:136`（全仓无第二处入口）。
- 来历：`7835c367`(2026-06-04「pyc骨架恢复 - 全量导入修复」) 引入骨架，`806c7047`(2026-06-06「145 个文件」批量) 补体。
  **形态＝引入即未接线**：`git grep "\.execute_plan(" 65309f6b -- 'neurova/*.py'` 只命中
  `multi_agent_manager.py:220` 的 `self._plan_orchestrator.execute_plan(...)`，那是**另一个类**（PlanOrchestrator），
  历史里从来没有一把经 `shared_core.ExecutionEngine` 调它。
- 现役替代：**成立，且是超集**。`collaboration/neurflow/execution_engine.py` 做拓扑分层（:437/:526）、层内并发
  （:512 注释与 `asyncio.gather`）、**真** condition 分支（:588-597，走 `safe_eval_condition`）、loop 迭代与检查点。
  对照之下本子的 `_evaluate_condition` 是桩：`variable_check` 分支把 `variable`/`value` 读出来丢弃、恒返 True（:234-242），
  连"条件"这一维都没实现。plan 的 schema（`{"nodes":[…], "execution_order":[…]}`）在仓内**没有生产者**——双向断点。
- 判定：**删**。`_get_next_node` 连本文件内都没被调用过（全仓 grep 0 命中）。

### A2 `…/execution_engine.py:246-282 + 407-413`（44 行）✅ `execute_tool` 与 `register_tool`

- 原功能：`execute_tool`(:246) 经实例内那份 `ToolEngine` 跑一次工具并记一条 `ExecutionResult`；
  `register_tool`(:407) 把 `(name, func, description)` 委托给同一份 `ToolEngine`。
- 关键入口：`ExecutionEngine.execute_tool:246`、`ExecutionEngine.register_tool:407`。
- 来历：同 A1（骨架批量事件）。`register_tool` 的消费者早先在批 70 那一批被摘（台账 §6-297/§6-298：
  咽喉"优先使用 ToolEngine"那一档恒不命中，唯一写入者就是这里），装配链已退役；`git log -S` 复算一致。
- 现役替代：**成立**。工具执行的真咽喉是 `tool_executor._execute_tool_core`（治理预检＋票据＋hooks＋`on_tool_executed`
  都在它身上，批 69/70 两批刚收口）；对外入口是 `POST /api/v1/tool-layers/tools/execute`
  （`api/endpoints/tool_layers.py:500`）。探针读数 `execute_tool: 0` 而 `POST …/tools/execute → 200 code=1`
  ——请求确实真跑了，但**不经这把引擎**。
- 判定：**删**。留下它等于留第二把无治理的 `ToolEngine` 入口（教义第 7 条判据：同一功能仓内只剩一处被消费）。

### A3 `…/execution_engine.py:291-372 + 426-436`（93 行）✅ `execute_workflow` 与 `_load_neurflow_workflow` — 需人裁（裁的是退役范围，不是要不要）

- 原功能：两段式转发——先按 `workflow_id` 从 neurflow storage 取已发布工作流执行（:311-339，meta `source="neurflow"`），
  取不到则回退实例内的 legacy `WorkflowEngine`（:341-372，meta `source="legacy"`），两边都没有 ⇒ `ValueError`（:343）。
  `_load_neurflow_workflow`(:426) 是那个"storage 可注入"的取数口。
- 关键入口：`ExecutionEngine.execute_workflow:291`。
- 来历：`53875590`(2026-09-04「并行批次落库 — OpenOcta/Utopia 启发落地一批」) **同一笔**里同时引入这段转发与
  它自己的契约测试 `tests/unit/workflow/test_engine_consolidation.py`（`git log --diff-filter=A` 复算同一 hash）。
  形态＝**自产自销**：`git grep "\.execute_workflow(" 806c7047 -- 'neurova/*.py'` 只命中本文件 :207 的**内部**调用
  （`_execute_node`，而它属 A1 死路）；生产侧从来没有外部调用者，探针读数 `execute_workflow: 0` 亦同向。
- 现役替代：neurflow 那一条**成立**（真引擎、真端点、真 storage）。它牵出的 legacy 模块
  `execution_engine/workflow_engine.py`（356 行）自己声明 deprecated 与"迁移完成后整体删除"，
  但它的**唯一**生产引用就是这里的 :121/:124——把 A3 删掉，那 356 行连同 NodeType/WorkflowInstance 一起成为孤儿。
  该模块 docstring 还写着"仅存量模板（agent/templates）与既有测试引用"：`grep -rn "WorkflowEngine" neurova/agent/` **0 命中**，
  `templates` 目录里也没有——**那句消费者陈述是假的**（命中面三类的"散文"那一类，落地那批要一并改）。
- 判定：**需人裁**，且裁的是范围而不是要不要：
  - **甲｜只收 shared_core 这侧**（A3 93 行 + A1/A2/A4/A5）：legacy `workflow_engine.py` 暂留但自此零引用，
    台账登记为"下一个退役对象"。代价＝把 356 行孤儿留到下批，命中面分两批扫。
  - **乙｜同批连 legacy 模块一起退**（再多 356 行 + 其专用测试与 `test_execution_engine_reset.py:79` 那格形状断言）：
    教义第 7 条"比-取-接-退"一步闭环，不留第二份表示。代价＝单笔改动面大，A/B 选择集要含 `tests/unit/workflow`
    与 `tests/unit/execution`，且 `test_engine_consolidation.py` 六格随转发入口一并退役。
  - 推荐**乙**：甲会正好留下本档案在诊断的那个形态——"实现还在、能到它的路全没了"。
  - 不可逆点：`WorkflowEngine` 的 `NodeType.PARALLEL`/`CONDITION` 线性链语义（:272-274）删后无回；
    但仓内今天没有任何数据经它（其 `register_workflow` 的生产调用者为零，测试自注册自跑），故实际风险为零。

### A4 `…/execution_engine.py:32-77 + 374-405`（76 行）✅ 执行台账那一面（`ExecutionResult` 与三个读口）

- 原功能：`ExecutionResult` dataclass（:32-77，含 `to_dict`/`from_dict`）＋ `_executions` 字典 ＋
  `get_execution_result`(:374)/`list_executions`(:378)/`cancel_execution`(:390) 三个读口。
- 关键入口：写侧只有 A1/A2/A3 三处；读侧就是这三个。
- 来历：同 A1。`get_execution_result` 的字符串在历史里变过号：`66cfa0fb`(2026-09-29 T-09 死码处置批) 与
  `1a5ea211`(2026-09-23 T-01 判据基础设施) ——那是**别模块同名符号**的变动，本类的读口从未被外部取用。
- 现役替代：执行记录这件事在本仓的真落点是 `core/agent_run_ledger`（运行台账）与 neurflow 的 `event_recorder`／
  `checkpoint`；这份进程内 dict 既非单源也不落盘。三个读口 import 通道复算全 0。
  **同名陷阱**：`ExecutionResult` 在 `neurova/execution_layers/__init__.py:96` 有**另一个类**，
  按类名 grep 会把运行时那半的在役符号误算成消费者（本档案按 import 路径计数，已剔）。
- 判定：**删**。写侧随 A1/A2/A3 一起没，`_executions` 就恒空。
  ⚠ 联动项（不许做成恒真空守卫）：`reset_execution_engine()`(:455-489) 的第三层"清 `_executions`"届时变成恒空动作，
  而它**在役**——`tests/conftest.py:156` 的 autouse 隔离夹具每测试后调它。落地那批必须把清理契约改判成
  两层（模块缓存＋类级 `_instance`），并由合成样本继续钉"清完再取是新对象"；
  现有判据 `tests/unit/execution/test_execution_engine_reset.py`（在册子集，`protected_tests.txt:139`）需同批改判。

### A5 `…/execution_engine.py:415-419 + 284-289`（11 行）✅ `set_event_bus` 与 `_call_llm`

- 原功能：`set_event_bus`(:415) 把总线转交给 `ExecutionMonitor`；`_call_llm`(:284) 是占位符，
  打一条 warning 后返回字符串 `"LLM 调用未实现"`。
- 关键入口：`ExecutionEngine.set_event_bus:415`。
- 来历：同 A1。
- 现役替代：`_call_llm` 零替代但**它本来什么都不做**（纯占位，无能力可失）；`set_event_bus` 的下游
  `ExecutionMonitor.set_event_bus`（`execution_monitor.py:202`）本身还在，只是没人经这里喂——见缺陷 D1。
- 判定：**删**（`set_event_bus` 属"死路 + 唯一注入口"，D1 另批处理；`_call_llm` 属"空壳无功能"）。

## 4 事件分组（这批不是渐进腐烂，是四次批量事件的未收尾）

| 事件 | 形态 | 本档案里落在哪 |
|---|---|---|
| `7835c367`(2026-06-04) pyc 骨架恢复 | 从 .pyc 反推全量导入，骨架即未接线 | A1/A2/A4/A5 的出生 |
| `806c7047`(2026-06-06) 145 文件批量更新 | 批量补体，从不接消费方 | A1/A2 补全 |
| `53875590`(2026-09-04) 并行批次落库 | 转发 shim 与它自己的契约测试**同笔**入库 | A3 自产自销 |
| `4a3c9380`(2026-09-04) 解除 `tests/` 整目录忽略、809 测试入库 | 私人笔记形状升格为"看起来有覆盖" | `shared_brainstem` 那类 test-only 面（见 D3） |
| `efa1bae0`(2026-10-12) 三套零接线编排器退役（§6-157/§6-166） | **只删了消费方，留下被孤立的实现** | D3：`multi_agent_manager` 仍留注入参数与 docstring 宣称 |

清退顺序建议按事件反向：先收 shared_core（A1-A5），再收它牵出的 legacy 模块（A3 乙），最后收
`multi_agent_manager` 那条恒不命中支路（D3，独立一批）。

## 5 审计中发现的缺陷（单列，不与收口捆绑）

- **D1 · 监控器的事件总线只写不读**。`ExecutionMonitor._event_bus` 在 `execution_monitor.py:198` 置 None、
  :202-204 有 setter，**全文件再无第二处读取**；唯一注入口 `ExecutionEngine.set_event_bus` 零消费者（探针 `set_event_bus: 0`）。
  ⇒ 执行监控今天不发一条事件，`alerts`/`connections` 那几个端点读的是内存告警表，不是事件流。
  属 AGENTS §2「只写不读的字段即断点」——要接（把总线真接进 monitor 的告警产生处）还是要删，是**产品语义**，出三态票等裁。
- **D2 · `variable_check` 恒返 True**（:234-242）。今天因 A1 全死而不咬人，随 A1 退役即消失，不必另修（记此防复现形态）。
- **D3 · `MultiAgentManager` 是一个没有调用方的共享组件壳**。`initialize_shared_components`(:97) 全仓零调用
  （只有测试类名 `TestInitializeSharedComponents` 提到）；`_plan_orchestrator` 恒 None ⇒ `:221-223` 那条
  "共享小脑执行"支路恒不命中；而 `:6` 的 docstring 仍宣称"所有 Agent 共用 PlanOrchestrator（小脑）、
  ExecutionEngine（脑干）和 Infrastructure（脊髓）"。`shared_brainstem` 只存在于 `4a3c9380` 那次批量入库的测试里。
  ⇒ 散文陈述与实状不符 ＋ 恒不命中支路，另批处理。
- **D4 · `neurova/tool_executor.py:5602` docstring 与代码不符**（批 73 已登记，此处只作同族互引）。
- **D5 · `neurova/core/flow_orchestrator.py` 在 `neurova/` 内零引用**（**未深扫**，见第 7 节）。

## 6 复算方法与伪命中（为什么"疑似"今天才敢定）

按名字 grep 一定得不出这份结论，本档案剔除的伪命中：

1. **三个同名 `execution_engine`**：`neurova/shared_core/execution_engine.py`、`neurova/execution_engine/`（包）、
   `neurova/collaboration/neurflow/execution_engine.py`。按文件名片段过滤会把三份混成一份。
2. **`ExecutionResult` 两份类**：`shared_core` 这份 vs `execution_layers:96` 那份（批 73 刚退役传输半区的那个文件）。
3. **`execute_tool` 五个同名**：`api/endpoints/tool_layers.py:500`（真咽喉端点）、`builtin_tools.py:1632`、
   `agent/native_tool_dispatch.py:95`、`agent/tool_execution_manager.py:465/513/559`——都不是本类方法。
4. **`list_executions`／`cancel_execution`／`execute_workflow`** 命中点全在 neurflow（storage 与 API 端点），另属其主。
5. **`register_tool`** 八个同名定义（`builtin_tools`、`flow_orchestrator`、`evolution/*`、`collaborate/workflow`）。
6. **`.execute_plan(`** 命中 `PlanOrchestrator`，不是本类（历史复算见 A1）。
7. **「有测试」当活证据**：`test_tool_engine_integration.py:225-260` 两格只断"能创建 / 委托注册得到"（形状），
   且该文件在册子集 `protected_tests.txt:28`——**在册不等于在产**。§3 的每条判定都以 import 通道＋探针读数为准。
8. **门面再导出**：`neurova/execution_engine/__init__.py:__all__` 只出九个 ToolEngine 名，**不含 WorkflowEngine**，
   所以 legacy 模块只能被路径直取（生产侧唯一路径就是 `shared_core:121`）。
9. **动态装载**：`import_module`/`__import__`/字符串路径扫过，本模块无一。

## 7 未覆盖与存疑

- `execution_engine/tool_engine.py`（第二把 ToolEngine）在 A2 之后的剩余消费者面未深扫；已知 `tool_layers.py:44`
  `get_tool_engine()` 自用，批 69/70 已收其守卫与装配链。
- `shared_core/infrastructure.py`（"脊髓"）与 `core/multi_agent_manager.py` 的整体存活度未扫（D3 只证到无人调注入函数）。
- `neurova/collaborate/workflow/orchestrator.py`（FlowOrchestrator，含 `get_orchestrator()`）与
  `neurova/core/flow_orchestrator.py` 是两份同功能实现，**未比对**（教义第 6/7 条的下一个对象），D5 的"零引用"因此只到存疑。
- 探针只覆盖一条真装配路（`create_app()` + lifespan + 7 个 HTTP 请求）；console REST/WS、渠道路由、移动端配对
  三条入口未跑——它们也不 import 本模块（import 通道复算为 0），但那是静态证据。
- 候选行量按 AST `lineno..end_lineno` 求和，正式净 LOC 须按 `git show --numstat` 逐文件复算并分池。

## 8 落地路线建议（若点单）

1. **批 75**：A1＋A2＋A4＋A5（shared_core 侧收口）。判据形态三条：主格钉"这十三个符号不再是 `ExecutionEngine`
   的成员、且全仓无 import 通道取用"；交付锁钉 `get_execution_monitor` 那条活路**两侧同读数**（形态集 278：
   退役类批次红的那格只证形状，中性要靠另一格取两侧同读数）；联动格把 `reset_execution_engine` 的清理契约改判成
   两层并继续钉"清完再取是新对象"（防做成恒真空守卫，形态集 251）。
   同批退役其专用测试：`tests/integration/test_tool_engine_integration.py` 两格＋`protected_tests.txt:28` 那条
   （若整档只剩这两格则整档摘除；按符号判，不按文件判）。
2. **批 76**：A3 取乙——转发入口连同 `execution_engine/workflow_engine.py` 356 行整体退役，
   `test_engine_consolidation.py` 六格随迁，假陈述的 docstring（"存量模板引用"）同批改。
3. **D1 单独先立红灯**再接线或删除，不与退役捆绑。
4. 每批都要重跑本卷第 1 节那份探针的等价形态（计数 wrapper 打在真方法上），证"退役前后 monitor 那条活路读数不变"。
