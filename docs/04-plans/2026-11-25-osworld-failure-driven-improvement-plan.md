# OSWorld 失败驱动的 computer_use 改进方案（2026-11-25）

> 依据：[osworld_failure_analysis_2026-11-25.md](../08-research/osworld_failure_analysis_2026-11-25.md)
> （子集 50 实测：均分 0.560、通过率 56.0%，22 个失败归为 M1–M5 五类模式）。
> 本方案把失败教训细化为可实施卡；全部落点在本仓既有设施上扩展
> （R6 单一事实源，不新造平行体系），每卡带红绿验收与 live-verify。
> 状态：**方案备稿，未开工**——待拍板后排期。

## 0. 范围与原则

- 改进对象是**本仓** `neurova/computer_use/`、`neurova/benchmark/cua_eval.py`
  与相关提示词面；OSWorld harness（F:/osworld）是外部基准设施，不改不入仓。
- 遵守修复教义：每卡先红后绿（R3）、根因处修（R1）、live-verify（R4）、
  净 LOC 逐条列去向（R2）。
- 涉及**模型可见文本**（工具描述/提示词）的卡，按测试纪律先提交 eval case
  （红→绿），case 标注来源=本次 OSWorld 失败分析。

## 1. P0 卡（评测口径正确性，直接服务下次跑分）

### C1 动作空间纪律：非法动作显式记 `invalid_action`

- **证据**：M1——`30e3e107`（109 步 Basic 宏）、`847a96b6`（bash）、
  `f918266a`/`23393935`/`51f5801c`（裸 python）等 ≥7 个失败任务。
- **根因**：harness 对非 pyautogui 代码静默 no-op，模型得不到"此路不通"
  的反馈；评测口径也无法区分"动作无效"与"动作有效但目标未达成"。
- **落点**：`neurova/benchmark/cua_eval.py`（`ToolExecutorEpisodeAdapter`
  与 `runCuaTasks` 行级事实）。
- **改动**：
  1. adapter 解析 episode 动作序列时按白名单校验（pyautogui 原子操作：
     click/type/paste/scroll/key/drag/set_value 等）；非白名单代码块记
     `invalid_action`（行级字段 + 聚合计数），不再当作已执行；
  2. `runCuaTasks` 聚合输出增 `action_invalid_total` 与逐任务
     `action_invalid` 计数；Baseline 对比时可按"剔除 invalid 后的有效步数"
     复算效率。
- **红绿验收**：红灯——构造含 `bash\ncode /x` 与 `basic\nSub x` 的假
  episode，断言 adapter 产出 `invalid_action` 计数且该步不计入有效执行；
  对现实现先跑红（当前会当普通文本放行）。绿灯后同套转绿。
- **live-verify**：用 F:/osworld 冒烟轮真实 traj 回放喂 adapter，断言
  `30e3e107` 的宏步被标 invalid、`2373b66a`（PASS 短任务）零误标。

### C2 多 run 聚合：均值±方差与逐任务翻转标记

- **证据**：M5——`5cfb9197` 冒烟 1.0（3 步）/子集 0.0（6 步假 DONE），
  同任务同配置跨 run 翻转。
- **根因**：单 run 读数把模型上游非确定采样当成了确定结论。
- **落点**：`neurova/benchmark/cua_eval.py` 新增
  `runCuaTasksRepeated(tasks, episodeFn, repeats, ...)`（同文件扩展，
  复用 `runCuaTasks`，不另起 runner）。
- **改动**：N 轮聚合输出 `per_task`（每轮得分列表、均值、翻转标记
  `flipped=True` 当存在轮次间 0/非0 分歧）与总览（mean、std、pass_rate
  区间）；`repeats=1` 时行为与现版一致（零破坏）。
- **红绿验收**：红灯——假 episodeFn 两轮分别返回 1.0/0.0，断言
  `flipped=True` 且均值 0.5；现实现无此能力先红。
- **live-verify**：对冒烟 10 任务用真 adapter 跑 repeats=2（成本标注），
  断言 `5cfb9197` 被标 flipped。

### C3 假 DONE 治理：核验先于结算

- **证据**：M2——6 个失败任务声明 DONE 判 0（DONE 声明假完成率 30%），
  其中 4 个 ≤6 步即结算。
- **根因**：结算点没有"目标状态核验"这一步，模型可以凭部分完成即宣布。
- **落点**（两处，均为根因位）：
  1. **cua_eval 行级事实**：episode 终态若含完成声明但无核验证据
     （如结算前最后一步不是截图/对照类动作），行级记
     `done_without_verify=True`，聚合输出计数——先让评测能看见该信号；
  2. **本仓 agent 结算纪律**（模型可见文本，先 case 后修）：computer_use
     任务收尾提示词加"声明完成前必须先截屏核对任务目标并逐条确认"
     的强制步骤；配套 eval case：对"无核验即 DONE"的轨迹文本判不合规、
     对"先核验后 DONE"判合规。
- **红绿验收**：红灯——eval case 对旧提示词文本失败；行级信号用假
  episode（DONE 且前一步非核验）断言 `done_without_verify=True`。
- **live-verify**：真后端起 computer_use 会话，跑一个带明确目标态的任务，
  对比加纪律前后"结算前核验动作"出现率。

## 2. P1 卡（能力增强）

### C4 屏幕指纹卡顿熔断

- **证据**：M3——`9bc3cc16`（dup=12）、`23393935`（dup=11）、
  `c288e301`（dup=7）：命令没进终端/界面无变化时模型反复重试到步数耗尽。
- **根因**：观测只有截图时，模型无法区分"动作未生效"与"生效但无视觉变化"，
  会话层也没有无变化检测信号。
- **落点**：`neurova/computer_use/evidence_frames.py`（已有
  `buildEvidencePair` 前后帧能力，R6 复用）+ 会话编排层（消费侧）。
- **改动**：
  1. evidence_frames 增 `framesDiffer(a, b, threshold)`：前后帧像素差分
     判定"画面是否变化"（纯函数、有界）；
  2. 会话层连续 N 步（默认 3）差分低于阈值 → 该步 ActionResult 附
     `stall=True` 元数据，并向模型注入一条系统提醒（"连续多次操作画面
     无变化：动作可能未生效，请换策略或先截屏确认状态"）；
  3. 阈值/窗口常量进会话配置，默认开、可关。
- **红绿验收**：红灯——两帧相同字节图断言 `framesDiffer=False`；会话层
  假帧序列连续 3 步无变化断言第 3 步产出 stall 提醒；现实现先红。
- **live-verify**：真桌面会话连续 click 同一空白区域 3 次，观察第 3 次
  结果带 stall 提醒且模型下一步换策略。

### C5 长文本输入引导（paste 优先）

- **证据**：M4——`f918266a` 75 步逐字符 typewrite 敲代码；`c288e301`
  同型。仓内已有 `computer_paste`（`actions.py:147`、
  `__init__.py:521`，且在 `FOREGROUND_DESKTOP_TOOLS` 名册）——缺的是
  引导与阈值。
- **根因**：工具描述未区分长短文本的正确用法；type_text 对长文本无提示。
- **落点**：`neurova/computer_use/actions.py`（`type_text`）、
  computer_type/computer_paste 工具描述（模型可见文本，先 case 后修）。
- **改动**：
  1. `type_text` 对 `len(text) > 200` 的输入在返回中附
     `suggest_paste=True` 与提示文本（不拒绝执行——语义仍成功，只加引导）；
  2. 工具描述改写：computer_type 注明"适合短文本；超过约 200 字符请改用
     computer_paste"；computer_paste 注明"长文本首选"。eval case 先行。
- **红绿验收**：红灯——eval case 对旧描述（无引导）失败；`type_text`
  201 字符返回缺 `suggest_paste` 先红。
- **live-verify**：真会话输入 300 字符到记事本，确认 paste 路径内容一致
  且无逐字符延迟。

### C6 规划器拆步两阶段接入（实验卡）

- **证据**：multi_apps 1/5、os/vs_code 各 2/5——跨应用长链任务是最大
  失分域；单模型直接出动作在长链上步数与注意力都不够。
- **思路**：发挥本仓规划/swarm 强项——规划器先读任务与首帧截图拆出
  带验收条件的步骤清单，执行器逐步执行并在步间回报；步失败可局部重规划。
- **落点**：`neurova/benchmark/cua_eval.py` 的 episode 适配层（新增
  `PlannerExecutorEpisodeAdapter`，与既有 `ToolExecutorEpisodeAdapter`
  并列、共享判据与 failure_class 口径）；规划提示词独立成模块。
- **红绿验收**：红灯——假规划器/执行器下，适配器能按拆步清单逐步驱动
  并在某步失败时触发重规划标记；先红后绿。
- **live-verify**：真后端 + 真 VM 跑 3 个 multi_apps 任务对比单阶段基线
  （成本标注；样本小只看方向，不作结论）。

## 3. P2 卡

### C7 脚本通道与 GUI 车道路由约定

- **证据**：M1 反例——`70bca0cc`/`01b269ae` 用 python/宏做只读验证 +
  GUI 做变更反而 PASS；`structured_edit`（T4 已落地）提供了 office 直写
  通道。缺的是"何时走直写、何时走 GUI"的显式约定。
- **落点**：`neurova/computer_use/structured_edit.py` 使用说明 +
  computer_doc_edit/computer_* 工具描述（模型可见文本，先 case 后修）+
  判据测试钉住描述含路由规则。
- **改动**：工具描述明确路由——"目标文件结构化字段（单元格/单元格区域/
  CSV 列）且路径已知 → computer_doc_edit 直写；需要人眼确认的界面状态 →
  computer_* GUI 动作；直写后必须回读校验"。eval case 先行。
- **红绿验收**：eval case 对旧描述（无路由规则）失败 → 改后通过；
  判据测试断言描述含两条路由规则与回读校验要求。
- **live-verify**：真会话改一个 xlsx 单元格走 doc_edit 直写 + 回读一致；
  改一个需要视觉确认的标题样式走 GUI。

## 4. 执行顺序与依赖

1. **C1 → C2**（同文件，先口径后聚合；C2 复用 C1 的行级事实）；
2. **C3**（行级信号与 C1 同批改 adapter 最省；提示词纪律的 eval case
   可并行）；
3. **C4 → C5**（都会话层，C4 先行因牵涉编排消费面）；
4. **C6**（依赖 C1/C2 的评测口径稳定后做 A/B）；
5. **C7** 随时可做（独立面）。

每卡独立提交：单任务单 commit，正文含红/绿实测输出、live-verify 证据、
净 LOC 与去向；不碰本方案外的在途文件（`--only` 逐文件点名）。

## 4.1 执行记录（2026-11-25/26 实施完毕）

| 卡 | commit | 实测 |
|----|--------|------|
| C1 动作白名单+invalid_action | `0b9ae7267` | 红灯 5/5→绿灯 14/14；A/B 基线 99=改后 99；live-verify 真实 traj 回放：30e3e107 宏任务 91 步标 invalid、2373b66a 零误标 |
| C2 runCuaTasksRepeated | `13d7d5cee` | 红灯 5/5→绿灯 19/19；真实 traj × repeats=2：std=0、翻转 0、invalid_total=182 |
| C3-1 done_without_verify 信号 | 原 `f043b36cd` 被并行 rebase 挤出→补登 `75466b760` | 红灯 6/6→绿灯 25/25；三域 124 passed |
| C3-2 核验纪律条目+eval case | `ed93c0d6f` | 先 case 后修（incident 来源 M2）；棘轮按协议同段等量删冗（净预算不升 1440）；伴生根修 view_budget 舍入公式（直乘截断→生产余数法单源）；三域 1590 passed 仅余 4 预存失败 |
| C4 StallGuard 卡顿熔断 | `bf3444013` | 红灯 ImportError→绿灯 9/9；A/B 证实 target_ops_passthrough/evidence_feedback 预存；manager 懒建记账器+6 动作打点+screenshot 信号注入 |
| C5 paste 优先引导 | `ed93c0d6f` 后独立提交 | 红灯 1F+4E→绿灯 12/12；两域 1008 passed；computer_type 描述+type_text>200 阈值信号 |
| C7 doc_edit 路由约定 | `150f6e4be` | 红灯 2F（缺"样式"标记）→绿灯；三域 1135 passed |
| C6 规划器拆步两阶段适配器 | `2c7b0c594` | 红灯 ImportError→绿灯 10/10（cua_eval 全文件 34/34 零破坏；benchmark+evals 193 passed）；live-verify L1 真桌面管线全链（首帧→3 步→终态，零 invalid 零 infra）；L2（OSWorld VM 3 任务 A/B）留排期 |

执行期坑（复跑必读）：
- **tool_executor.py 混有他会在途 hunk**：C4 用"HEAD+本卡 hunk"中间态构造
  + 精确暂存提交，工作树备份恢复——`--only` 仍会卷工作树全量状态，同文件
  混改时须按 hunk 级构造（C4 首次 amend 卷入 19 行在途改动已当场修正）。
- **棘轮预算**：rules_sections 加条目必须同段等量删冗（净预算不升）；
  markersPresent 是**全量命中**语义，判据标记收窄为核心标记勿堆备选。
- **测试公式对齐生产单源**：view_budget 的舍入公式缺陷被文本变化撞到
  4654×0.7 边界暴露——测试判据向生产余数法对齐（R6）。

## 5. 不做什么

- 不把 OSWorld harness/VM 镜像入仓；评测设施留在 F:/osworld。
- 不为"动作空间校验"新建独立服务/模块——白名单与计数都在 cua_eval
  既有 adapter 内扩展（R6）。
- 不在无 eval case 的情况下改任何模型可见文本（测试纪律第 5 条）。
- C6 实验卡不预设结论：若两阶段在真任务上无增益，按数据放弃并记录。
