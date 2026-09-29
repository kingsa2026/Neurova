# G1 修正方案 —— 工具循环迭代化与轮次态归属

> ## 状态更新（2026-09-30 对齐至 `da843611` + `189fc321`）
>
> **本文是立项目击与判据来源，不是现状描述。** 正文中"仍开放/待落地"的判定已被实现取代：
>
> | 缺口 | 现状（逐条核实） |
> |---|---|
> | G1 递归→迭代 | 已闭合：`openai_loop.py`/`anthropic_loop.py` 自递归与 `_top_level` 归零；轮次态随调用传递；子代理深度上限有守卫用例 |
> | G2 出口验收 | 已闭合，且形状优于本文方案：**GoalGate 进默认装配**（`openai_loop.py:212-222`），出口求值点 `evaluateLoopExit`（`base.py:71`，ctx 带 `isLoopExit`）流式与非流式两路都接；续跑预算绑**独立配置键** `goal_max_continuations`——正是本文 §4.4 要求的单源约束。故 `set_goal_gate` 无生产调用方是设计结果，不是断点 |
> | G3 并发 | M1–M4 与逐工具裁决已落地（71/71）；收益判据仍 `no_data`（未否证） |
> | G4 超时即取消 | 已闭合：`TimeoutDisposition.ABORT`（`tool_coordinator.py:245`）返回 cancelled 形态并被 `is_policy_denial` 认作决策 |
> | G5 审批闭环 | 本文四断点链已由 `189fc321` / MR #339 落地；HTTP 活体三条未验 |
> | G7 缓存 | 重排已停；主动 cache marker 仍缺 |
> | G8 台账 | 15 条已处置，1 条为反向控制条目（标签口径 nit） |
>
> 引用本文行号前请对准当前 `HEAD` 复核——正文写于 `c55e1f37`，此后 loop/tool 轴有 138 个提交。


> 立项时间：2026-09-26 · 取证基线：`c55e1f37` · 关联缺口：对标文档 §5 G1
> 关联方案：[`2026-09-26-goal-gate-wiring-repair-plan.md`](2026-09-26-goal-gate-wiring-repair-plan.md)（G2）
> 关联台账：`scripts/ci/toolLoopDeadlines.txt`（`IterationGate` 等条目）

---

## 0. 结论先行：本方案推翻了 G1 原来的风险理由

对标文档把 G1 记作"递归 → 栈深度 ≈ 轮数"。**这个理由经实测站不住**，本方案把它换掉。

| 命题 | 实测结果 |
|------|---------|
| "每轮递归消耗的栈深度" | **约 2.03 帧/轮**（流式每轮 = wrapper + once 两层生成器） |
| "默认 `recursionlimit=1000` 下可持续轮数" | **493 轮** |
| "最激进合法配置下的轮数" | `MAX_ROUNDS = 200`（`security/agent_limits_settings.py:34`）⇒ 有效 `_max_tool_rounds = 200//2 = 100` ⇒ **占预算约 20%** |
| "仓内是否留下过栈溢出证据" | **没有**。全仓 `setrecursionlimit` / `RecursionError` 命中数为 0 |

**所以：递归深度不是 G1 的真实风险，也不构成紧迫故障。** 但同一个代码位置上确实躺着**三条更严重的缺陷**（§2），其中第一条单独就足以支撑"改成迭代 + 显式轮次态"的决定——只是理由要换。

**建议的动作**：把对标文档 §5 G1 的风险描述从"栈深"改判为"**轮次态归属错误**"，优先级从 §8 第 5 位提到第 3 位（在 G2、G5 之后）。

---

## 1. 实测：数据怎么来的

探针脚本（临时验证，按 `AGENTS.md` §4 **即用即删**，故内联在此，不落 `tests/`）：

```python
import sys, asyncio
sys.setrecursionlimit(1000)            # 与仓内默认一致
MAXR = 0; TC = 0

async def tool(n):                     # 模拟轮内被 await 的分派链深度
    return 0 if n <= 0 else 1 + await tool(n - 1)

async def once(rp, d):                 # 模拟 _predict_stream_once
    if d >= MAXR: yield "done"; return
    await tool(TC)                     # 本轮最深点
    async for ev in wrap(rp, d + 1): yield ev

async def wrap(rp, d):                 # 模拟 _predict_stream 包装层
    async for ev in once(rp, d): yield ev

# 对每个 maxr 求：多深才 RecursionError
```

| 轮内分派链深度 `TC` | 可持续轮数 | 说明 |
|---|---|---|
| 0 | **493** | 纯循环形态 |
| 30 | **479** | 每轮减去约 30/2 = 15 轮 |
| 100 | **444** | 同上，线性抵扣 |

**读法**：可持续轮数 ≈ `(1000 − TC) / 2.03`。即分派链深度与嵌套轮数**共享同一预算**，
`TC` 越大，允许的嵌套越浅——这个抵扣关系是**线性且可预测**的，不存在"突然爆炸"。

### 1.1 探针的三个已知失真（不要把上面的数字外推）

1. 探针的每轮是 2 帧；真实 `_predict_normal` 非流式路径每轮是 **1 帧**（`openai_loop.py:434` 直接 `return await self._predict_normal(...)`），
   所以**非流式的深度余量比测得的更大**。
2. 真实分派链深度远大于 30/100——`tool_executor` 的六臂回退链 + 治理 + 沙箱 + hook 未计入实测。
   `TC` 的真实值**只有活体打点才知道**（§8 验收线第 4 条要求量它）。
3. 探针未计 `chat_pipeline` 在 loop 之上的 await 层数。

即便按悲观外推（`TC=200`），可持续轮数仍有 ≈394 轮，**远高于合法配置上限 100**。
这是本方案判定"深度非风险"的依据。

---

## 2. 真实缺陷（三条，均已核实到行）

### 缺陷 A · 轮次态挂在 loop 实例上，跨会话共享 ← **这才是改迭代的理由**

轮次控制状态全部是 `self.` 上的可变实例属性：

```
openai_loop.py:80   self._tool_rounds = 0        # 注释自称"递归深度计数"
openai_loop.py:87   self._stagnation_count = 0
openai_loop.py:88   self._round_user_key = None
openai_loop.py:228  self._tool_rounds = 0        # 在 predict_step 入口重置
openai_loop.py:231  self._stagnation_count = 0
openai_loop.py:267  self._round_user_key = md5(...)
openai_loop.py:99-135  self._gate_runner         # DoomLoop 窗口等会话级态
```

而 loop 实例是 **per-agent 单例**：`agent_core.py:974` `a.loop = a.loop_manager.get_loop()`、`:1099` 同源。
`chat_pipeline.py` 与 `agent_core.py` 中**未发现任何 RLock/Lock 序列化 `chat`**。

**推论（标注为假设，须由 §8 第 1 条红测证伪或证实）**：同一 agent 实例上并发进行两个会话时，
A 会话在 `predict_step` 入口的 `_tool_rounds = 0` 会清零 B 会话正在累加的计数
⇒ **轮次上限对 B 失效**（可无限续轮），`_stagnation_count` 与 `DoomLoopGate` 窗口同样互相污染
⇒ 死循环检测会把 B 的正常调用误判为 A 的重复签名。

这条与"多渠道同 agent"的既有形态直接相关，**是真实可达路径的概率不低**。

对照参照侧的做法：一个 `RegularTurnLoopState` 显式对象贯穿整轮（其 `turn-loop-state.ts:76-128` 声明约 30 个字段），
循环函数接 `state` 为参数，**无任何跨请求实例态**。这不是风格差异，是归属差异。

### 缺陷 B · 子代理嵌套无深度上限

`SwarmManager` 的硬限只有两个，都**不管深度**：

```
swarm.py:113  MAX_ACTIVE_CHILDREN = 5      # 管的是广度（同时活跃数）
swarm.py:172  if active_children >= MAX_ACTIVE_CHILDREN
swarm.py:~95  MAX_TASK_CHARS               # 管的是任务串长度
```

子代理经 `swarm.py:518` `response = await agent.chat(...)` **重新进入整条 loop**，
且 `swarm.py:500` 附近注释明确"子 Agent 使用自身 llm_config（独立模型/人设是蜂群的前提）"——
即子代理拿到的是**完整工具面，包含 `spawn_subagent` 本身**（该工具仅在 `tool_coordinator.py:51` 配了 600s 超时，未被任何禁用清单覆盖）。

⇒ **嵌套深度 D 无上界**。按 §1 的抵扣关系，真实总深度 ≈ `Σ_层 (轮数 × 2) + 最底层分派链`；
成本侧更是按层乘性放大。**深度守卫缺失比栈溢出风险严重得多。**

（对照：参照侧是**结构性**封顶——子配置写 `subagents:{enabled:false}` → 端口为 `undefined` → handler 抛 `ConfigurationError`，深度硬顶 1。
本仓的 `MAX_ACTIVE_CHILDREN` 是"可配的广度限制"，两回事。）

### 缺陷 C · 三份 loop 各有一份终止/预算/门控语义，且已经漂移

| | 非流式 | 流式 | Anthropic |
|---|---|---|---|
| 位置 | `_predict_normal:337` | `_predict_stream:438` + `_predict_stream_once:566` | `predict_step:34` |
| 续轮方式 | `:434 return await` 自身 | `:742 async for … in self._predict_stream` 互递归 | `:101 return await self.predict_step(..., _top_level=False)` |
| 轮次上限 | `_max_tool_rounds`（可配） | 同 | **硬编码 `> 10`**（`:81`） |
| 门控 | 只判 TERMINATE（`:398`） | TERMINATE + INTERRUPT（`:680-694`） | **不调门控** |
| 门控 ctx 键 | 缺 `round_reply`/`round_usage`/`goal` | 全 | — |

第三份拷贝的 `predict_step` 递归**经公有入口**，靠 `_top_level=False` 才不重置计数（`:51-52`）——
这个保护是有效的（本方案初稿曾假设"重置导致上限失效"，核对后**证伪**，见 §3），
但公有入口自递归本身就是脆弱装配：任何新增的 per-request 初始化都会被多跑一遍。

**漂移不是风险预测，是已发生的事实**：G2 方案 §1 RC-3 记录的"非流式 `TokenBudgetGate` 恒不可触发"，
就是三份语义各写一遍的直接产物。

---

## 3. 本方案自身的误判记录（防止结论被二次误用）

| 初判 | 核实结果 | 错因 |
|------|---------|------|
| "G1 的风险是栈深度" | 实测 493 轮预算 vs 合法上限 100 轮 ⇒ 非风险 | 未测量即定性 |
| "`anthropic_loop` 经公有 `predict_step` 递归 ⇒ 计数被重置 ⇒ 轮次上限恒不触发" | **证伪**。`:101` 递归传 `_top_level=False`，`:51-52` 据此跳过清零 | 只看了递归调用的目标函数，没看它传的参 |
| 对标文档 §9 更正 #6 已记一次同类错误 | 本轮再次踩"从组件形态正推结论" | 同一方法论毛病第二次出现 ⇒ 说明它不是偶发，**凡是"某机制失效"的断言，必须先找到它的反证参数再下笔** |

---

## 4. 目标态

一句话：**轮次态从"agent 实例属性"迁到"每次调用显式传递的 state 对象"，循环从三份递归收敛为一份迭代。**

| 环节 | 现状 | 目标 |
|------|------|------|
| 状态归属 | `self._tool_rounds` 等 6+ 个实例属性 | `TurnRunState` 显式对象，`predict_step` 创建、逐轮传递、随轮释放 |
| 控制流 | 三份递归（其中两份互递归） | 一份 `while` + 一份"单轮"函数，流式/非流式共用同一单轮 |
| 相位 | 无 | 轻量不变量（非完整状态机，见 §5.3） |
| 嵌套 | 无深度上限 | 深度进 `TurnRunState`，超限**结构化拒绝**（不抛裸异常） |
| 出口守卫 | 无（G2 已记） | 与 G2 的 `evaluateLoopExit` 共用同一份，**一处接入两条路** |

**不做**：不照抄参照侧 30 字段状态对象、不上通用状态机框架。见 §5.3。

---

## 5. 设计

### 5.1 切片 A（最高优先，独立价值）：`TurnRunState` 抽取

把轮次态从 `self` 迁出。命名按 `AGENTS.md`（PascalCase 类、camelCase 函数）：

```python
# neurova/agent/loops/turn_run_state.py（新）
@dataclass
class TurnRunState:
    """一次 chat 调用的轮次态。生命周期 = 本次 predict_step，不跨请求存活。

    存在理由：这些计数原先挂在 loop 实例（per-agent 单例）上，
    同 agent 并发会话会互相清零彼此轮次预算与死循环窗口。
    """
    toolRounds: int = 0
    maxToolRounds: int = 10
    stagnationCount: int = 0
    roundUserKey: Optional[str] = None
    gateRunner: "GateRunner" = None          # per-request 构造，不再复用实例字段
    nestingDepth: int = 0                    # 缺陷 B 的落点
    continueBudget: Dict[str, int] = field(default_factory=dict)
```

装配点：`predict_step` 入口构造（取代 `:228/:231/:267` 三处实例赋值），
沿调用链显式传给 `_predict_normal` / `_predict_stream_once` / `handle_tool_calls` / `evaluateLoopExit`。

**收口要求**：`_gate_runner` 现有两份构造（`openai_loop.py:99-103` 与 `:124-135`）必须在本切片合并为
`buildGateRunner()` 单函数——这与 G2 方案的 C1 是**同一个动作**，两案在此处必须合流，
不得各建一份（`AGENTS.md` 教义第 6 条）。

### 5.2 切片 B：递归 → 迭代

非流式（`:434`）改法最直接——尾递归改 `while`。

流式麻烦在生成器委托：`async for ev in self._predict_stream(...)` 会把整条链嵌住。
改法是**把嵌套层拉平为外层循环**，`_predictStreamRound` 只提供"单轮"，不自我调用：

```python
async def _predict_stream(self, request_params):
    state = ...                                 # 切片 A 的 TurnRunState
    while True:
        outcome = await self._runOneStreamRound(request_params, state)   # 单轮，无自递归
        if outcome.kind == "final":
            yield outcome.doneEvent; return
        # continue / gateTerminate / overflowRetry 各自就地处理，不新增栈帧
```

`_predict_stream` 现有的溢出恢复包装（`:438`→`:454`→`:516`/`:563` 的二次递归）也要并入同一 `while`，
否则溢出重试仍是嵌套的。

Anthropic 侧（`:101`）同批改，并**删掉 `_top_level` 这个参数**——它是为绕开"公有入口自递归"而生的补丁，
迭代化后该问题不存在，保留即第二份控制通道（教义第 6 条）。

### 5.3 切片 C：轻量不变量，**不**上状态机

参照侧的 `TurnMachine` 有 9 个相位 + 非法转移抛错。本仓**不建议照搬**：三条 loop 现在缺的是
"状态归属正确"，不是"相位可证明"。建议只立两条断言式不变量，代价近零：

```python
def assertRoundInvariant(state: TurnRunState) -> None:
    """每轮入口自检。违例即点名是哪个计数被跨会话污染——把缺陷 A 变成可观测事实。"""
    if state.toolRounds > state.maxToolRounds:
        raise ...   # 说明上限判定被绕过，而不是静默继续
```

并在 `TurnRunState` 上加 `turnId` 与创建者 `agentId` 指纹，
使"两个不同 turn 的 state 被交叉使用"在开发期即红。

> 若后续要做 G5（审批真阻塞）与 G2（出口守卫），相位机的价值才上升——
> 那时再引入，且引入的是**本仓自己的**相位定义，不是移植。

### 5.4 切片 D：子代理深度上限（缺陷 B）

```python
# swarm.py spawn()
if parentState.nestingDepth >= MAX_SUBAGENT_DEPTH:      # 建议 1（与参照侧同档）或 2（D-2 决策）
    return self._rejection("depth_limit", f"子 Agent 嵌套深度已达上限 {MAX_SUBAGENT_DEPTH}")
```

要点：
- 走**既有 `_rejection` 通道**（`swarm.py:319`），返回 `{"rejected": True, "swarm_rejection": ...}`；
  该形态已被 `security/governance.py:68 is_policy_denial` 识别为"决策而非故障"，
  不会误触熔断器。**不新造第二种拒绝形态。**
- `MAX_SUBAGENT_DEPTH` 必须是**单源配置键**，且落地后在 `scripts/ci/toolLoopDeadlines.txt`
  的阈值可达性轴上机器算出 **`single_source`**；若算出 `scaled_*`，即视为实现有误
  （同一约束见 G2 方案 §4.4，原因相同：`IterationGate` 就是栽在双尺度）。
- 深度值经 `TurnRunState.nestingDepth` 传递 ⇒ **依赖切片 A 先落地**。

---

## 6. 与 G2 的依赖顺序

两案在**同一处**交汇，顺序不能反：

| | 依赖 | 说明 |
|---|---|---|
| G2 的 C1（门控装配收口 + ctx 键补齐） | 与 G1 切片 A **是同一个动作** | 必须合并成一片做，不得两案各改一次 `_gate_runner` 构造 |
| G2 的 C2（出口求值点） | 受益但不依赖 G1 | 递归形态下出口守卫要在**两处**写；G1 切片 B 后只需**一处**。**若 G1-B 先做，G2-C2 改动量减半** |
| G1 切片 D（深度上限） | 依赖 G1 切片 A | 深度要随 state 传 |
| G2 的续跑预算 | 依赖 G1 切片 A | 续跑计数若仍挂 `self.`，等于把缺陷 A 扩大到新维度 |

**推荐总顺序**：`G1-A（含 G2-C1）` → `G1-B` → `G2-C2/C3/C4` → `G1-D` → `G1-C` → G3/G4/G5。

---

## 7. 决策点

| # | 决策 | 我的推荐 | 代价 |
|---|------|---------|------|
| **D-1** | 缺陷 A 是否成立（并发同 agent） | **先证伪再动手**：§8 第 1 条红测就是这个证伪工具 | 若测不出串扰，切片 A 降级为"整洁性重构"，优先级下调 |
| **D-2** | `MAX_SUBAGENT_DEPTH` 取 1 还是 2 | **1**（当前无任何上限，1 已是巨大收紧） | 2 会把成本放大 2 倍且深度收益存疑 |
| **D-3** | 是否引入相位状态机 | **不引入**，只做 §5.3 两条不变量 | 状态机是净增代码与认知负担，当前无消费者 |
| **D-4** | 流式溢出重试是否并入 `while` | **并入** | 不并入则仍留一处嵌套，切片 B 的收益打折 |
| **D-5** | `_top_level` 参数删除 | **删** | 需同时改所有调用点；保留即第二份控制通道 |

> D-1 我不替你判——它决定是否值得动 loop，所以我把证伪手段排在方案里而不是结论里。

---

## 8. 红→绿测试设计（`tests/unit/agent/`，全部 `test_` 前缀）

**转绿前不得进 `scripts/ci/protected_tests.txt`。**

### 8.1 缺陷 A 的取证红测（D-1 的判据，最先写）

| 用例 | 断言 |
|------|------|
| `test_concurrentTurnsDoNotShareToolRoundCounter` | 同一 agent 实例上交叠驱动两次 `predict_step`，A 的入口清零**不得**影响 B 正在累加的 `_tool_rounds`。用真实 loop + 计数替身（禁 `MagicMock` 冒充业务对象） |
| `test_doomLoopGateWindowIsPerTurnOnConcurrentTurns` | 同上，交叠时 B 的正常重复调用不得被 A 的签名判为死循环 |
| `test_stagnationCountIsPerTurnNotPerAgent` | `_stagnation_count` 跨 turn 不残留（现仅靠 `:231` 入口重置，交叠即失效） |

### 8.2 迭代化结构红测

| 用例 | 断言 |
|------|------|
| `test_streamLoopFrameDepthIsConstant` | 活体量：驱动 N=1/10/50 轮，`inspect` 取每轮同相位处的栈深，**三档深度差为常数**。这条同时否证"深度风险"并证实"迭代化确实拿平了栈" |
| `test_noSelfRecursionInToolLoops` | 静态：`openai_loop.py`/`anthropic_loop.py` 中不出现 `self._predict_normal(` / `self._predict_stream(` 的自调用形态；`_top_level` 字样归零 |
| `test_gateRunnerAssembledInSinglePlace` | 静态：`GateRunner([` 在 loop 模块内出现**恰一次**（教义第 6 条自证） |
| `test_threeLoopsShareOneRoundBudgetSource` | 非流式/流式/Anthropic 三条路的轮次上限来自同一可配来源；**Anthropic 侧不得留硬编码 `> 10`** |

### 8.3 深度守卫红测

| 用例 | 断言 |
|------|------|
| `test_subagentSpawnIsDepthBounded` | 构造 depth+1 层派生链，第 depth+1 次必须拿到 `swarm_rejection`，**且 `is_policy_denial` 认它为决策**（不误触熔断） |
| `test_depthThresholdIsSingleSourceInLedger` | 台账机器算 `single_source`；算出 `scaled_*` 即红 |
| `test_nestingDepthTravelsWithTurnState` | 深度经 state 传递，不挂 agent/loop 实例属性 |

---

## 9. 规模与净 LOC

| 切片 | 生产新增 | 生产删除 | 净 |
|------|---------|---------|-----|
| A `TurnRunState` | ~90 | −40（散落的实例属性读写与两份装配） | **+50** |
| B 迭代化 | ~120 | −90（三处递归 + 互递归包装 + `_top_level`） | **+30** |
| C 不变量 | ~35 | 0 | **+35** |
| D 深度守卫 | ~30 | 0 | **+30** |
| 合计 | | | **约 +145** |

去向逐条如上，进提交说明（教义第 2 条：净新增为正须逐条列明）。
测试另计约 +400 LOC，不计入门禁。

**运行成本增量：0。** 本方案不新增任何 LLM 调用——与 G2 相反（G2 有验收调用成本）。

---

## 10. 验收线

1. **缺陷 A 活体自证**：真实起后端，同 agent 并发两会话，其中一个故意跑满长工具轮；
   修前应观测到轮次上限被绕过或死循环误判，修后不得复现。命令与输出原文进提交说明（教义第 4 条）。
2. **栈深实测**：`test_streamLoopFrameDepthIsConstant` 绿，并把修前/修后三档深度数字写进提交说明。
3. **`TC` 真实值**：活体打点量出轮内分派链实际深度，回填本文 §1.1 第 2 条的空位——
   **本文留了一个已知未量项，收口时要么补上、要么显式保留为未知**。
4. **台账一致**：深度阈值条目入 `toolLoopDeadlines.txt`，判据与阈值可达性两轴均由机器算出且为 `single_source`。
5. **零回归**：三条 loop 在改前改后跑同一组工具轮用例，终止行为逐条比对（教义第 3/4 条）。
6. **D-1 若被判伪**：切片 A 降级、本文 §2 缺陷 A 改判为"假设未成立"，并**如实改写本节**而非删除。

---

## 11. 风险与回退

| 风险 | 处置 |
|------|------|
| 流式生成器拉平改变事件产出次序，前端 `tool_call`/`tool_result` 配对错位 | `buildToolRoundMessages` 是两路共用的成块点，保持其调用位不变；`test_streamEventsKeepDeclarationOrder` 钉住次序。NeurUI 侧另跑 `npx vue-tsc --noEmit` + vitest |
| `_top_level` 删除影响未搜罗全的调用方 | 先 `grep -rn "_top_level"` 定集合，逐点改；**这是公有 `predict_step` 签名，属外部可见面**，须在提交说明点名 |
| per-request 构造 `GateRunner` 带来分配开销 | 每轮一次 dict 级开销，远小于一次模型往返；且这是正确性所需 |
| 并发串扰（缺陷 A）实际不可达 | 见 D-1；不可达则切片 A 降级为整洁性重构，B/C/D 仍各自独立成立 |
| 与 G2 在两案交汇处冲突 | §6 已定合流点；两案不得并行开改 `_gate_runner` |

**回退**：四片各自独立可回退；A 与 B 之间无破坏性接口变更（`predict_step` 外部签名不动，只删 `_top_level`）。

---

*本文 §1 的实测数字可用内联探针在任何 Python 3.12 环境复现；其余结论逐行对准 `c55e1f37`，
复验命令：`grep -n "_tool_rounds\|_stagnation_count\|_gate_runner" neurova/agent/loops/*.py`、
`grep -n "MAX_ACTIVE_CHILDREN\|agent.chat(" neurova/agent/swarm.py`、
`grep -n "_top_level" neurova/agent/loops/anthropic_loop.py`。*
