# G3 修正方案 —— 工具批次并行调度与能力声明单源

> ## ⚠️ 状态更新（2026-09-27，基线对齐至 `2a4023c6`）
>
> **本方案的 M1–M4 已落地**（MR #274 `63cfa177`、#278 `af8389c8`、#279 `47be5594`、#280 `a07e4fcd`）。
> 正文中下述数字**已过期**，仅作立项目击留痕，引用前以本横幅为准：
>
> | 正文断言 | 现值（`2a4023c6` 实测） |
> |---|---|
> | §1.2 覆盖 10/71 = 14%、`file_read` 不在清单 | 已改为逐工具声明：`concurrentSafe=True` 共 **19** 项，其中 **12 项资格生效**；**`file_read` 已声明且生效**（`writeScopes=("none",)`） |
> | §1.3 MCP/Skill/workflow 恒不可并行 | MCP 注册点已接声明通道（Issue #271 M4） |
> | §6.1 `tool_capability.py` 落 `tool_layers/` | 实际落在 **`neurova/core/tool_capability.py`**，判据函数 `isParallelEligible:131` |
> | §10.1 "先量后说"为待建 | 取数入口已成可重跑命令 `scripts/diagnostics/tool_parallelism_readout.py`，并由 `tests/unit/tools/test_tool_parallelism_readout.py`（16 例）钉住：三条形态各有 positive control、双 loop 的 `path` 分档不许合并、零样本守零、`no_data ≠ sparse` |
>
> **判据现状 = `no_data`（不是 sparse，未否证）**。原因已从"缺抓取"变为**版本差**：
> `neurova_tool_batch_shapes_total` 只存在于 `metrics.py:177`（#279 之后），
> 而承载真实流量的 `:9527` 实例仍运行改造前代码 ⇒ 该序列发不出来。
> **收口所需**：一个跑在 ≥ `47be5594` 之后、且承载真实流量的实例的 `/metrics`。
>
> **本方案 §4 的一个论点已被证伪**：我曾把"四份清单不可合并"列为设计约束。
> 落地实现确实未合并（正确），但它引入了一个我未预见的**新双源形态**——
> **7 个工具声明 `concurrentSafe: True` 却因 `writeScopes=("shared",)` 被
> `isParallelEligible` 判为不可并行**：`computer_screenshot`、`computer_dom_snapshot`、
> `computer_som_snapshot`、`browser_read`、`browser_dom_read`、`canvas_read`、`canvas_list_nodes`。
> 行为正确（共享外设读串行），但声明与推导给出**相反信号**，只看声明会误判为已并行。
> 属教义第 6 条口径下的待收项，建议单独立项（改法：这 7 项去掉 `concurrentSafe: True`，
> 或把"共享设备"表达成独立轴而非借用并行字段）。

---


> 立项时间：2026-09-26 · 取证基线：`c55e1f37` · 关联缺口：对标文档 §5 G3
> 关联方案：G1 [`2026-09-26-tool-loop-iteration-repair-plan.md`](2026-09-26-tool-loop-iteration-repair-plan.md)、
> G2 [`2026-09-26-goal-gate-wiring-repair-plan.md`](2026-09-26-goal-gate-wiring-repair-plan.md)
> 关联台账：`scripts/ci/toolLoopDeadlines.txt`

---

## 0. 结论先行

> **本节数字是 2026-09-26 立项时的现场，已被 M1–M4 落地推翻——以顶部横幅为准。**
> 保留原文是为了留"当时为什么判断要改"的击点，不是现状描述。

现在的批次并行是**一票否决制**：一轮里的多个工具调用，只要**有任何一个**未被登记为并发安全，
**整轮全部串行**。登记清单只有 10 项，而内置工具有 71 个——**覆盖 14%**。
其中最讽刺的一条：`file_read` **不在这份清单里**。

本方案换掉这个判据：把"能不能并发"从**一处硬编码名单**改成**每个工具自己声明的能力属性**，
调度侧按属性分组。默认仍为串行（fail-closed），因此**在有人开始声明之前，本方案零行为变更**。

**关于收益数字的诚实声明**：真实墙钟收益取决于各工具的耗时分布，**我没有这个数据**。
本文因此只给两类结论：① 无需假设的确定量（并行度利用率，§1.2）；② 把"先量耗时分布再定收益"
列为验收前置（§10）。任何写进提交说明的加速百分比，必须在 §10 第 1 条量出来之后才允许出现。

---

## 1. 现状（逐行核实）

### 1.1 判据本身

`neurova/agent/loops/base.py:140-148`：

```python
from neurova.agent.tool_coordinator import is_concurrency_safe

use_parallel = len(tool_calls) > 1 and all(
    is_concurrency_safe((tc.get("function") or {}).get("name", ""))
    for tc in tool_calls
)
if use_parallel:
    outcomes = await asyncio.gather(*(self._execute_tool_call_worker(tc) for tc in tool_calls))
else:
    outcomes = [await self._execute_tool_call_worker(tc) for tc in tool_calls]
```

`tool_coordinator.py:61-71` 的 `_CONCURRENCY_SAFE_TOOLS`（10 项）+ `:83` 的大小写不敏感成员判定。
调用方注释自陈这是保守选择（`base.py:134-139`：混合批次的排序/共享状态复杂度不进热路径）——
**这个保守是有意的，不是疏忽**，所以本方案不是"修 bug"，是"把保守换成可声明、可审计的粒度"。

### 1.2 确定量：并行度利用率（无需任何耗时假设）

```
builtin 工具总数 = 71      并发安全清单 = 10（14%）
readish 语义（名字含 read/search/fetch/parse/list/get_/recall）= 20 个，其中仅 6 个被登记
未登记的纯读类：file_read, browser_read, browser_dom_read, file_list, file_search,
              rss_read, social_search, bilibili_search, voice_memory_search,
              list_agents, canvas_read, canvas_list_nodes, deep_research, get_datetime
```

| 批次形态<br>（`r`=已登记安全数，`w`=未声明数） | 当前实际并行度 | 分组后并行度 | 串行执行次数 |
|---|---|---|---|
| r=2, w=0 | 2 | 2 | 2 |
| r=1, w=0 | 1 | 1 | 1 |
| **r=2, w=1** | **1** | 2 | 3 |
| **r=3, w=1** | **1** | 3 | 4 |
| **r=6, w=1** | **1** | 6 | 7 |
| **r=10, w=1** | **1** | 10 | 11 |
| r=2, w=2 | 1 | 2 | 4 |

**读法**：`w ≥ 1` 一列全为 1——只要混进一个未声明工具，**这一轮已声明的那批一点并行都拿不到**。
典型场景"读三个文件 + 一次搜索 + 写一个文件"（r=0/w=4，因 `file_read` 未登记）当前完全串行。

### 1.3 MCP / Skill / workflow 工具**一律不可并行**

`is_concurrency_safe` 只查那 10 个名字。MCP 工具名形如 `mcp.{server_id}.{tool}`、
Skill 与 `workflow:{id}` 各有命名空间 ⇒ 它们的成员判定恒为 `False`。
**多路 MCP 检索（本就是最该并发的场景）当前必然整轮串行。**

---

## 2. 参照侧真实机制：把"可抄"与"别抄"分开

参照侧调度器把两件事捆在一起呈现，**逐行拆开后它们价值差很多**。

### 2.1 别抄：依赖图在工具轮是装饰性的

`runtime/methods/tools.ts:38-58` 是主循环喂给调度器的**唯一生产者**，其 `dependsOn` 字段：

```ts
return { toolCallId: tc.id, toolName: tc.name, dependsOn: [], /* ... */ };
```

**硬编码空数组。** 于是 `scheduler.ts:105-152` 的 `topologicalSort` 恒为全零入度直出、
`:204-226` 的 `validateNoCycles` 恒通过、`groupByParallel` 恒只在 level 0 分组。
真正干活的只有 `canRunInParallel` 这一段分类逻辑。
（依赖图**有**真实消费者的地方是工作流图调度器 `workflow/expert/parsers/graph-seed.ts:114-118`，
那是另一个子系统，与工具轮无关。）

⇒ **本方案不实现拓扑排序。** 实现它等于为一个恒真的分支引入环检测、层级、错误路径三处复杂度。
若将来工具调用真需要依赖（如 `orchestrate_tools` 内层），那时再立项，且有真实生产者来验它。

### 2.2 可抄：把安全分级放进工具声明，并明确其组合语义

参照侧 `tools.ts:44-56` 的取值方式有两条值得照搬：

```ts
const sideEffectScope = entry?.permission?.sideEffectScope ?? metadata?.sideEffectScope;
readOnly: metadata?.readOnly === undefined
            ? undefined
            : metadata.readOnly && sideEffectScope === "none",
```

1. **`readOnly` 不是单字段，是与作用域的合取**——"只读但会触碰网络/系统"仍不算无副作用。
   这比本仓"一个布尔名单"表达力强，且能防住"标了 readOnly 却发网络请求"这类误登记。
2. **三态而非二态**：`undefined`（未声明）与 `false`（声明为不安全）分开走，
   未声明可回落到一个默认策略，声明了就尊重声明。

### 2.3 警示：它自己也把同一事实写了两份

参照侧 `scheduler.ts:233-243` 另有一份 `READ_ONLY_TOOLS` 名字硬编码集，与
`permission/service.ts:559-573` 的同类集**已经分叉**（前者缺 `Agent`/`Task`）。
⇒ 抄"声明进工具"这一条，**不要**抄它留了第二份名单的形态。

---

## 3. 真实缺陷清单

| # | 缺陷 | 证据 | 性质 |
|---|------|------|------|
| **A** | 一票否决：任一未声明 ⇒ 整轮串行 | `base.py:142-146` | 粒度过粗 |
| **B** | 覆盖面 10/71，且 `file_read` 缺席 | §1.2 | 保守默认未跟进 |
| **C** | 并发能力无法声明：MCP/Skill/workflow 恒不可并行 | `is_concurrency_safe` 只查固定名单 | **封闭性缺陷**（新工具永远进不来） |
| **D** | 判据是**运行期成员查询**，非装配期校验 | 无静态一致性守卫覆盖该清单 | 漂移无人拦 |
| **E** | 并行度无上限 | `asyncio.gather` 全量并发 | 缺护栏：一轮 20 个 MCP 调用即 20 并发 |

**B/C/D 是本方案要解决的主体；A 是它们的共同表现。**

---

## 4. 关键判断：仓内有四份工具安全清单，但它们是**四条不同的轴**

这是本方案最容易做错的地方，先实测再下结论：

```
_CONCURRENCY_SAFE_TOOLS(10)  ∩  _NON_REPRODUCIBLE_TOOLS(37)  =  ∅
```

| 清单 | 位置 | 回答的问题 | 轴 |
|------|------|-----------|-----|
| `_CONCURRENCY_SAFE_TOOLS` | `tool_coordinator.py:61` | 能否同时跑 | 并行安全 |
| `_NON_REPRODUCIBLE_TOOLS` | `builtin_tools.py:1074`（37 项，注释称"全量打标单源"） | 重放会不会制造新副作用 | 可重放性 |
| `READ_ONLY_TOOLS` / `HIGH_RISK_TOOLS` | `computer_use/runtime_policy.py:43,50` | 桌面操作要不要审批 | 审批风险 |
| `GuardThreatCategory` | `security/tool_guard.py:43` | 单条命令是否毁灭性 | 内容级威胁 |

**两轴不重合的真实例子**：`computer_screenshot` 在 `_NON_REPRODIBLE_TOOLS` 里（注释：
"瞬时快照，重放不回当时画面"），但它在副作用意义上**是**只读的——只是它操作共享设备，
并行会互相抢画面，所以并行轴上应当串行。**一个字段表达不了这两件事。**

⇒ 因此本方案**不合并这四份清单**（合并会造出一个语义混淆的上帝字段，反而违反教义第 6 条的**精神**：
单一事实源指的是"一个事实一处定义"，不是"所有清单塞一个文件"）。
正确做法是：**把事实下沉到工具声明，让每条轴成为声明的投影**。

---

## 5. 目标态

| 环节 | 现状 | 目标 |
|------|------|------|
| 事实源 | 4 份名字清单，各按名字硬编码 | 每工具一份 `ToolCapability` 声明（装配期落地，一处） |
| 判据 | 运行期名单成员查询 | 读声明的三态推导；未声明 ⇒ 串行（fail-closed，与现状同） |
| 批次 | 全或无 | 按能力分组：可并发项成组 `gather`（带上限），其余项单独成组串行 |
| 覆盖 | 仅 builtin 固定名单 | builtin / MCP / Skill / workflow 四条注册路径**都能声明** |
| 守卫 | 无 | 装配期校验 + 静态一致性用例（同 `TestSchemaDispatchConsistency` 形态） |

---

## 6. 设计

### 6.1 声明模型（三态 + 作用域合取）

```python
# neurova/tool_layers/tool_capability.py（新）
class WriteScope(str, Enum):
    NONE = "none"            # 不触碰外部状态
    WORKSPACE = "workspace"  # 只动本会话工作区
    GIT = "git"; NETWORK = "network"; SYSTEM = "system"
    SESSION = "session"      # 动本 agent 的会话态
    SHARED_DEVICE = "shared_device"   # 桌面/浏览器/画布等共享外设

@dataclass(frozen=True)
class ToolCapability:
    """工具自身能力的声明。缺省即最保守——未声明不可并行、不算只读。"""
    readOnly: bool = False
    destructive: bool = False
    concurrentSafe: bool = False
    writeScopes: frozenset[WriteScope] = frozenset({WriteScope.SESSION})
    serializesWith: frozenset[str] = frozenset()   # 与哪些工具互斥（见 §6.3）
```

**并行资格推导（唯一一处，取代 `is_concurrency_safe`）**：

```python
def isParallelEligible(cap: ToolCapability) -> bool:
    """三态合取：与参照侧同一纪律——readOnly 必须同时是"无写作用域"。
    SHARED_DEVICE 永不并行：截图/DOM 快照读的是同一个外部设备的瞬时态，
    并发会互相拿到对方的画面（§4 的真实教训）。"""
    if cap.destructive or not cap.concurrentSafe:
        return False
    return cap.readOnly and cap.writeScopes <= {WriteScope.NONE}
```

> **为什么不新增第五份清单**：本模块只定义**形状与推导**，不定义**成员**。
> 成员一律落在各工具的声明处（`_BUILTIN_SCHEMAS` 旁 / MCP 注册点 / Skill 元数据），
> 是"每工具一处"，不是"集中一份大名单"。

### 6.2 分组调度（不含拓扑）

```python
def planToolBatches(toolCalls, caps, *, maxParallel: int) -> List[ToolBatch]:
    """把一轮调用切成批次：连续的并行资格项合成一批（受 maxParallel 截断），
    其余每项自成一池批。保持原声明顺序，回装契约不变。"""
```

- **保序约束不动**：现有"按原 `tool_call` 顺序回装"（`base.py:106-108`）是前端配对契约，
  分组只改变**执行时序**，不改变**回装次序**。`asyncio.gather` 本身保序，逐批串接后仍按原索引落位。
- 串行项仍逐条走 `_execute_tool_call_worker`，**执行链一行不改**（治理、hook、超时、审计全在咽喉里）。
- 本函数是纯函数 ⇒ 可静态测，不碰运行时。

### 6.3 互斥声明 `serializesWith`（解决"名单装不下的那类"）

`SHARED_DEVICE` 之外还有真互斥：两个 `run_code` 并行会抢同一解释器态；
`git` 并行会抢同一 `.git/index.lock`。这类"彼此只与特定对象冲突"的关系，
布尔字段表达不了，`serializesWith` 用**工具名集合**表达，分组时把冲突项拆到不同批。

> 这是本方案唯一"超出参照侧"的一处（参照侧靠 `sideEffectScope` 粗分 + 一刀串行）。
> **但它是新造的抽象**——风险见 §8 D-3，建议先只上 `SHARED_DEVICE`，
> `serializesWith` 留到有第三个真实案例时再启用。

### 6.4 并行上限（缺陷 E）

`maxParallel` 取**单源配置键**（建议默认 4），且落地后必须在
`scripts/ci/toolLoopDeadlines.txt` 的阈值可达性轴上机器算出 **`single_source`**；
算出 `scaled_*` 即视为实现有误——同一约束在 G1 §5.4、G2 §4.4 已各立一次，
原因相同：`IterationGate` 就是栽在同一键双尺度上。

### 6.5 迁移与兼容

| 步骤 | 动作 | 行为变化 |
|------|------|---------|
| M1 | 落 `tool_capability.py` + `planToolBatches`，`base.py` 接上 | **无**（此时无人声明 → 全串行，与现状一致） |
| M2 | 把现有 10 项 `_CONCURRENCY_SAFE_TOOLS` **逐条翻译**为声明，**删除该清单** | 无（等价）；清单归一，消除双源 |
| M3 | 补 `file_read` / `file_list` / `file_search` / 各 `*_read` 共 14 项声明 | 收益兑现点 |
| M4 | MCP 注册点接声明（默认串行，允许 server 侧配置放开） | 覆盖缺陷 C |
| M5 | `_NON_REPRODUCIBLE_TOOLS` 与 `runtime_policy.READ_ONLY_TOOLS` 改为**从声明投影**（语义对齐者才改；不对齐的保留） | 需逐条论证，见 §8 D-2 |

M2 之后 `_CONCURRENCY_SAFE_TOOLS` 必须**物理消失**——留着就是第五份清单的反面教材：
"两边都留着、加个同步脚本"正是教义第 6 条明令禁止的处置。

---

## 7. 并行化前必须逐条排除的危害（含本仓已踩过的先例）

| 危害 | 本仓现状 | 结论 |
|------|---------|------|
| ContextVar 在 `gather` 子任务里 `set()` 落不到父上下文 | **已解决并有实测记录**：`core/turn_context.py:77-90` 用可变对象 `TurnElapsedAccumulator` 按引用跨任务共享，docstring 明写"不可变 float 的 `set()` 落不到父轮次的上下文" | ✅ 已有正确范式，新并行路径**必须照此形态**（可变对象共享，禁不可变值 set） |
| 工具在轮内写 ContextVar | 实测：`set_turn_*` 写点全在 `chat_pipeline`（轮首装配），**工具执行路径内无写点** | ✅ 无冲突 |
| 结果回装错序破坏前端配对 | `base.py:106-108` 显式按原序回装 | ✅ 分组不动这条即可 |
| 超时转后台与并行交织 | `tool_coordinator.run_with_timeout` 超时后转后台并塞 `_pending_hints`（`:119-154`），一轮内多项同时转后台时 hints 汇聚未验证 | ⚠️ **须测**（§9 用例 `testMultipleBackgroundConversionsInOneBatch`） |
| 桌面/沙箱作用域并发绑定 | `tool_executor._sandbox_scope` 是 context-manager 绑定，宿主 guest desktop 为共享态 | ⚠️ 已由 `SHARED_DEVICE` 一律串行挡住 |
| 连接池/SQLite 并发 | `core/connection_pool.py` 已开 WAL，多线程走 RLock | ✅ 已有保障 |
| 成本账本并发写 | `cost_tracking` + `set_llm_cost_context` 走 ContextVar；工具并行轮不发起 LLM 调用 | ✅ 本方案不涉及 |
| 子代理并发放大 | `spawn_subagent` 不在声明集内 ⇒ 保持串行；`SwarmManager.MAX_ACTIVE_CHILDREN=5` 仍生效 | ✅ 不与 G1 深度守卫打架 |

---

## 8. 决策点

| # | 决策 | 我的推荐 | 代价 |
|---|------|---------|------|
| **D-1** | 默认（未声明）策略 | **fail-closed 串行**，与现状一致 | 收益要靠逐条声明挣，没有"默认放开"的白捡 |
| **D-2** | 要不要合并 §4 的四份清单 | **不合并**，只投影；且 M5 只对语义真正对齐者动 | 强行合并会造出"重放性"和"并行性"混一轴的上帝字段，`computer_screenshot` 就是反例 |
| **D-3** | 上不上 `serializesWith` | **先不上**（§6.3 已限定为备选） | 新抽象且无第三方验证；等第三个真实互斥案例再启用 |
| **D-4** | MCP 工具默认 | **串行**，由 server 配置显式放开并行 | 放开=信任第三方 server 无副作用，这个信任不该默认给 |
| **D-5** | 要不要做拓扑排序 | **不做**（§2.1 已证参照侧那里它也是装饰） | 省掉约 −120 LOC 与环检测错误路径 |
| **D-6** | `maxParallel` 取值 | 4 | 上限越高越吃连接池/设备竞争；4 已在典型"读 3~4 个文件"场景吃满收益 |

> D-2/D-5 是我主动**收窄**的地方——参照侧形态里有两处看起来该抄，
> 一处语义不成立（合并清单），一处是装饰（拓扑）。收窄的理由都写在正文，可反驳。

---

## 9. 红→绿测试（`tests/unit/tools/`，全部 `test_` 前缀）

转绿前不得进 `scripts/ci/protected_tests.txt`。

### 9.1 现状取证（红灯，先证明粒度过粗）

| 用例 | 断言 |
|------|------|
| `test_fileReadIsCurrentlySerialized` | 钉住现状：`is_concurrency_safe("file_read") is False`。M3 落地后本用例**改判为 True 并反转注释**，不许静默删除 |
| `test_mixedBatchLosesAllParallelism` | `[web_search, file_read]` 走 `planToolBatches` 前（或走现判据）并行度 == 1 |
| `test_mcpToolNeverParallelEligible` | `mcp.srv.tool` 恒不可并行（缺陷 C 的现状钉桩） |

### 9.2 目标行为（绿灯）

| 用例 | 断言 |
|------|------|
| `test_declarativeCapabilityReplacesNameList` | 静态：`_CONCURRENCY_SAFE_TOOLS` 符号在 `neurova/` **恰 0 次命中**（M2 收口自证，教义第 6 条） |
| `test_readOnlyRequiresNoWriteScope` | `readOnly=True` 但 `writeScopes={NETWORK}` ⇒ 不可并行（§2.2 合取语义） |
| `test_sharedDeviceNeverParallel` | `computer_screenshot`/`computer_dom_snapshot` 恒不可并行（§4 反例钉桩） |
| `test_batchPlanPreservesDeclarationOrder` | 分组打乱执行时序后，回装序列仍等于原 `tool_calls` 顺序 |
| `test_parallelFailureDoesNotAbortSiblings` | 一批内某项抛错，其余项照常返回（沿用 `base.py:152-156` 的既证契约到分组场景） |
| `test_maxParallelCapsGroup` | 12 个可并行项 + `maxParallel=4` ⇒ 切成 3 批，单批不超 4 |
| `test_maxParallelThresholdIsSingleSource` | 台账机器算 `single_source`；`scaled_*` 即红（§6.4 自证） |
| `testMultipleBackgroundConversionsInOneBatch` | 同批两项都超时转后台 ⇒ `_pending_hints` 收齐两条、不互相覆盖（§7 待测项） |
| `test_contextVarSharingSurvivesGather` | 并行批内 `add_turn_tool_elapsed` 累加后，父上下文读到合计（钉住 §7 第一条范式不被新代码破坏） |

**禁止写法**：不得用 `MagicMock` 冒充工具声明（必须走真实 `ToolCapability` 构造）；
不得手工把阈值传进 `planToolBatches` 来绕过配置单源——**判据必须从配置键起**，
否则测的是参数而非装配（`AGENTS.md` 教义第 3 条点名项）。

---

## 10. 验收线

1. **先量后说**（本方案的硬性前置）：从既有观测面拉真实工具耗时分布——
   `metrics.record_tool_execution`（Prometheus 直方图）与 `turn_context.get_turn_tool_elapsed()`
   两条源。**量出来之前，提交说明里不得出现任何加速百分比。** 若量出多工具批次的占比低于 ~5%，
   则本方案收益不成立，**应据此放弃 M3 之后的一切**并如实记录否证结果。
2. **活体验证**（教义第 4 条）：真后端起一个"读 3 个文件 + 1 次 web_search + 1 次写文件"的任务，
   修前修后各跑 ≥5 次，记录墙钟与轮数；证据原文进提交说明。
3. **零行为回退证明**：M1/M2 两步各自跑同一组既有用例，
   并行度与执行结果**与改前逐条一致**（等价迁移不得夹带行为变化）。
4. **清单归一证明**：`_CONCURRENCY_SAFE_TOOLS` 全仓 0 命中（§9.2 首条），且其原 10 项
   逐项在声明处可查到等价条目——**一项都不能丢**（丢了就是静默收窄覆盖面）。
5. **台账一致**：`maxParallel` 条目入册，判据与阈值可达性两轴均由机器算出且为 `single_source`。
6. **顺序契约无回归**：NeurUI 侧工具调用/结果配对展示在并行批下无错位（跑 `npm run test` + `npx vue-tsc --noEmit`）。

---

## 11. 规模与净 LOC

| 切片 | 新增 | 删除 | 净 |
|------|------|------|-----|
| 声明模型 `tool_capability.py` | 70 | — | +70 |
| `planToolBatches` + `base.py` 接入 | 60 | −18（旧 `use_parallel` 段） | +42 |
| M2 翻译 10 项 + 删清单 | 25 | −12 | +13 |
| M3 补 14 项声明 | 40 | — | +40 |
| M4 MCP 声明接入 | 45 | — | +45 |
| 合计（M5 另计） | | | **约 +210** |
| 测试另计 | ~380 | | 不计入门禁 |

**运行成本增量：0 次 LLM 调用。** 与 G1 同（纯调度侧）；G2 才有模型调用成本。

**主动省掉的**（相对照抄参照侧）：拓扑排序 + 环检测 + 依赖字段 ≈ **−120 LOC**、
`serializesWith` ≈ −35 LOC（D-3 决定先不上）。

---

## 12. 风险与回退

| 风险 | 处置 |
|------|------|
| 误声明某工具有副作用 ⇒ 并行造成数据竞争 | 每条声明必须带**依据行**（读实现后写"为何可并行"），评审逐条核；`isParallelEligible` 的合取判据让"标 readOnly 但有写作用域"自动失效——**声明错也并不上行**，这是双层防护 |
| MCP 第三方 server 被过度信任 | D-4 默认串行，放开需 server 级显式配置且入台账 |
| 并行批内日志交错，排障变难 | 咽喉已按 `tool_call_id` 打标；M3 上线前先在活体验证里读一遍交错日志确认可读性 |
| 收益不足（§10.1 量出来多工具批次很少） | 明确允许**止步于 M2**：M1+M2 本身已是"消除双源 + 打开封闭性"的净收益，不依赖并行收益兑现 |
| 与 G1 切片 A 冲突 | 二者都改 `base.py` 的这一段。按 G1 §6 的批次顺序，**G1-A 先行**，本方案 M1 在其之上落地 |

**回退**：M1 之后每一步独立可回退；总开关走 `agent_limits_settings` 单键
（关则退回旧判据一个版本周期，再随 M2 一并删除——**开关不得长期留存**，否则又是"只写不读的配置"）。

---

*本文数字均可复算：`grep -n "_CONCURRENCY_SAFE_TOOLS" -A 12 neurova/agent/tool_coordinator.py`、
`grep -n "_NON_REPRODUCIBLE_TOOLS" -A 30 neurova/builtin_tools.py`、
`sed -n '140,150p' neurova/agent/loops/base.py`；§1.2 的覆盖率与交集可用
`_BUILTIN_SCHEMAS` / 两份 frozenset 直接求集合运算复现（本文用项目解释器实测）。*
