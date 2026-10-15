# 任务级环节证据 —— `attribution_hit_rate` 升级成"改对地方没有"（ModularRSI M-E 后半·第二刀）

> **性质**：实施票面（未开工）。上游对照报告
> [`modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md`](../08-research/modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md)
> §4 M-E / §7.1-Q4；第一刀已落地（`36987c02`，台账 §6-251）：环节轴已扩进
> `agent/capability_gap.py` 单源（`false_completion` / `loop_stalled`，用途表 `_GAP_PURPOSE`）。
> 本票面记的是**第二刀**，其前提条件与落点均为 2026-10-16 工作树实测。

---

## 0. 一句话

现在归因只回答"候选预测会涨的那几道题涨没涨"；要它回答"**它说修的那个环节，是不是真的被它修好了、
有没有顺手把别的环节弄坏**"，缺的是**每条评测任务的环节证据**与**候选的环节声明**这两样，
而后者今天根本不存在。

## 1. 实测前提（决定这刀能切多深，别按想象开工）

1. **只有真臂能产环节证据**。环节 kind 的投递点是**环出口求值**
   （`agent/loops/base.py:evaluateLoopExit` → `_recordHarnessGapFromExit`，第一刀加的）。
   模拟臂（`eval/service.py` 的 `SimulatedAgent`）不跑环、没有门控 ⇒ 每任务环节证据**恒为空**。
   这不是缺陷，是结构。所以本票面**不得**被实现成"给模拟臂编一个环节标签"。
2. **真臂今天只在双臂试评路径上**。`api/endpoints/text_evolution_api.py:279-289` 才构造
   `TextArmAgentExecutor`；进化主路径 `eval/service.py:368` 走
   `resolveEvolutionExecutor(agent=None)` ⇒ 回落模拟臂。故收益面先是 `ab_compare`，
   要覆盖进化臂得先把生产装配切到真臂（前作 P1-C 那条线，另批）。
3. **收件箱语义是轮次级且读取即消费**（`capability_gap.detectCapabilityGap` 的既有契约，
   文件头明写"读取即消费，避免下一轮无据重放"）。要在一次评测里逐条取证据，
   必须新增一个**不消费**的读数口，不能把消费点往前挪——挪了就破坏既有语义。
4. **`_evaluate` 的明细是五元组**：`runner.py:366 details.append((ex, score, output, feedback, failed))`，
   消费点实测 **8 处**（`runner.py:374,472,525,532,597,608` + `service.py:ab_compare` 里的
   `zip` 双解包 + `calibration` 传入的 `evaluate_fn`）。加一个字段就是改一次公开形状，
   两侧解包都要动——**要么走旁路，要么一次改全**，不许出现"一半调用点带新字段一半不带"。
5. **候选没有环节声明**。`eval/mutator.py:73-101` 只把最低分失败样本喂 prompt，
   产出的候选是一段正文，**不携带任何"我改的是哪个环节"的记录**；
   `history_ledger.attribution_hit_rate`（`:184-203`）现在吃的 `predicted` 是 **task_input 字符串列表**。

## 2. 设计裁定（要人拍的一条，选项已带代价）

**"候选声称修哪个环节"由谁给？**

- **甲 让 LLM 自报**（变异器 prompt 里要求输出 `target_environment`）。零检测成本，
  但这就是 M-D 刚退役掉的那类东西：`difficulty` 也是 LLM 自报、未经校准、没人验证，
  最后成了只写不读的空转字段。拿它当判据输入，等于把未校准标签钉进 accept 面。
- **乙 从证据反推**（**推荐**）：候选是由哪几条失败用例喂出来的，那些用例运行时的环节证据
  取并集就是它"声称要修的环节"。声明因此**长在实测证据上**，与仓内一路的
  "判据取数必须来自写侧真产出"一致；代价是它表达的其实是"生成时看到的环节分布"，
  要在票面与代码注释里写清这个语义，别读成"模型自己认为修的是哪个环节"。
- **丙 不做声明**，只把"每任务的环节证据"接进去，读数从"预测题涨没涨"扩成
  "各环节的涨/跌分布"， accept 判定仍不看它。范围最小，但拿不到"改对地方没有"的判据。

## 3. 落地形状（按乙案写，另两案只改取值来源）

1. `agent/capability_gap.py`：新增 `peekCapabilityGapKinds()` —— **只读不消费**，
   返回本轮收件箱里的 kind 去重清单；`detectCapabilityGap` 的消费语义一字不改。
2. `evolution/eval/runner.py`：在 `_evaluate` 的逐条执行处（`350-369`）为每条用例取一次
   环节证据，**经旁路返回**而不是塞进五元组——把 `_evaluate` 的返回改成
   `(avg, details, envByTask)` 会炸 8 个解包点；改不动就把旁路挂在 runner 实例上按
   `id(example)` 键存，并在 `run()` 结束时清理（不挂就变成跨轮残留，那正是本仓记过的形态）。
   > 若宁可改元组：那就**一次改全 8 个点**，且 `ab_compare` 的 zip 双解包要同批改判。
3. `evolution/eval/history_ledger.py`：`attribution_hit_rate` 增加
   `by_environment: {kind: {predicted, hit, regressed}}` 分组读数；
   `unpredicted_regressions` 从"平铺 12 条"改成分环节看（今天它只入账不拦，
   见对照报告前作 §3.4，这条不变）。
4. 判定面**先不接**：读数进台账与 `/rsi/status`，accept/reject 不读它——
   与 M-C/M-B 同一档位（先让读数站住，再谈进判）。要进判据必须同批改判
   `testHarnessGapEvidenceStaysOutOfSynthesis` 与本票面的蕴涵格。

## 4. 红灯设想（转绿前不入 `protected_tests.txt`）

- 造两条用例：一条真臂运行中触发假完成（goal 门开火）、一条触发环停滞（doom_loop 开火）；
  断言旁路读数按任务给出正确 kind（当前根本没有这条读数 ⇒ 红）。
- 断言 `peekCapabilityGapKinds()` **不消费**：peek 两次都有，之后 `detect` 才清空
  （反向钉：若谁把 peek 实现成消费，这一格红）。
- 断言候选的"声称环节"确实来自证据集合并、而不是恒空或恒全（注入空证据时必须为空 ⇒
  防"兜底成一个默认环节"那种假数据）。
- 断言 `attribution_hit_rate` 的分组读数与总体命中数**可对账**
  （`sum(by_environment[k].hit) == len(hits)`），防"另起一份互不相等的口径"。
- 模拟臂路径：断言环节读数恒为空且**不报错**、不污染分组（这条防的是最坏的一种：
  给没跑环的臂编出环节标签）。

## 5. 影响面与不可逆点

- 文件：`agent/capability_gap.py`、`evolution/eval/runner.py`（含 8 个解包点之一半）、
  `evolution/eval/history_ledger.py`、`evolution/eval/mutator.py`（只在选甲案时动）。
- 台账：`history_ledger` 记录新增字段，**旧记录无该键 ⇒ 分组读数为空**，
  不得把"空"读成"没退化"（三态纪律，同 `parameter_activity`）。
- 不可逆点：若第 2 步改元组而不一次改全，会出现两半解包并存的中间态；
  若甲案被采纳，未校准标签就进了证据面——那正是本仓 M-D 刚清掉的东西。
- 关联：与 M-C（`model_under_test` 分键）同属"评测面加维度"，两者可共用一次
  `_evaluate` 侧的读数改造，**不要各起一套旁路**。

## 6. 验收顺序建议

先做丙案（只接证据与分组，不碰声明），拿到几轮真实分组读数后，再决定乙案的声明是否进判据；
甲案不推荐，写在此处只为让"为什么不用 LLM 自报"有据可查。
