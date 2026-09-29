# ADR 0023: 接力判据加问第三问（中止可归因到配额吗，不只问"有没有被中止"）

- **Status**: Accepted
- **Date**: 2026-09-29
- **Decision Maker**: Issue #327 收口（承接 ADR 0022）

## Context

ADR 0022 定了接力判据的**事实源**：读平台在收尾期注入的事实，不读构建侧自造的真值。
事实源这一层的方向是对的，此后两次修法都在它上面做，v2 的判据形态是两条：

```yaml
if:
  - '[ "$CNB_PIPELINE_STATUS" = "error" ]'
  - 'case "$CNB_BUILD_FAILED_STAGE_NAME" in *"npc-go"*) true;; *) false;; esac'
```

两轮修法的**方向**相反，根因却是同一个：**拿一个只能回答「有没有被中止」的事实，
去回答「要不要续跑」**。

- 第 1 轮（ADR 0022 之前）：判据读不可靠输入（硬 SIGKILL 时
  `CNB_BUILD_FAILED_MSG` = 脚本最后一行 echo）——方向是**判据落空**；
- 第 2 轮（ADR 0022，v2）：判据改读确定性事实（失败 stage 名）——方向是
  **判据漏维度**：它答「是不是被中止在 Agent 那一格」，没答「这次中止是不是撞墙」。

漏掉的这一维度在真实构建里被放大成事故（构建 cnb-urv-1k3lagkdv，2026-09-29）：

```
Master[agent][36] finish with aborted, in=0 out=0 cache=0 total=0, duration=0.0s
Master[agent][36] stop with error: [LLM request error ...] Pipeline has been stopped, Agent aborted
```

第 36 轮 / 7.4 分钟 / 该轮一个 token 都没发出——**平台 AI 网关主动中止**。
四道上限一道都没触达（流水线整体 20h、Job、无输出 10 分钟、`maxTurns: 2000` 用掉 1.8%），
开工时的预算量尺自己写着 `verdict=continue`。而接力**真的触发了**。

后果是结构性的：「一次平台中止」被放大成**自动续跑链条**——每约 7 分钟拉起一轮
新的 `npc:go`，以完全相同的方式再被掐、再接力，无限循环。每一轮都真实计入 LLM
成本，而 Issue 上只会不断多出构建号（Issue #327 本身就是这么产生的）。

关键读数是：**撞满配额的正常收官与平台网关的外部中止，在收尾期的可见形态完全相同**
（都是 `CNB_PIPELINE_STATUS=error` + 失败 stage 是 `npc-go`）。两者只能靠
「中止时刻离配额墙还有多远」分开。

## Decision

**接力判据读三处，前两处答「有没有被中止在 Agent 那格」，第三处答「这次中止
可归因到某个配额吗」。三处同时成立才接力。**

第三处的事实源**不是新造的**：本仓已有运行时长预算量尺
`scripts/ci/npc_runtime_budget.py`（Issue #272，Agent 侧量尺），它按
`CNB_PIPELINE_MAX_RUN_TIME` / `CNB_BUILD_START_TIME` 算已用比例并给出四态判据。
本次只给它加一个**机器可读出口** `--predicate`（打印 `true` / `false` 一行），
判据即 `meetsQuotaWall()`（已用比例 ≥ `HALT_PCT`）：

```yaml
if:
  - '[ "$CNB_PIPELINE_STATUS" = "error" ]'
  - 'case "$CNB_BUILD_FAILED_STAGE_NAME" in *"npc-go"*) true;; *) false;; esac'
  - 'eval "$($NPX_PREDICATE)"'
```

四条不可让渡的口径：

- **阈值与解析只在一处**。`HALT_PCT` / 两个平台变量的解析留在量尺脚本里；
  `.cnb.yml` 写的是「怎么调用它」（`$NPX_PREDICATE` 由解释器探测段统一登记，
  python3 → python → node 三级降级与门禁脚本同一份），不出现第二份阈值。
- **量不出 ⇒ 不续跑**。两个平台变量缺失或解析失败时判据为 `false`。
  「量不出来」不得被转写成一次烧配额的接力（修复教义第 2 条）。
- **解释器形态不改判据**。node 分支经 `scripts/ci/run_gate_under_node.sh` 桥脚本，
  与 python 分支逐字等价（同一份 `NODE_IMPLEMENTATION`）。
- **四处命中点同批改**（`.cnb.yml` 的共用 Job 体 + issue 评论 + PR 评论 + 接力载体），
  同源形态，任一处漏改即与其余三处分叉。

## Consequences

- 判据从「被中止即续跑」收敛为「撞墙才续跑」：平台网关的外部中止不再拉链条，
  真撞满 `maxTurns` 的收官仍照旧接力（这是它的设计意图）。
- `HALT_PCT`（85%）成为**接力语义的一部分**：它此前是 Agent 的收尾纪律阈值，
  现在同时是「中止可归因到配额」的判据线。两者的分叉后果不对称——
  Agent 撞 85% 后仍有 15% 余量落盘回帖，而判据要的是「中止时确实贴着墙」，
  故取同一个数字是必要的：撞墙中止的读数必然 ≥ 85%，外部中止通常远低于它。
- 仍需 **live-verify**：判据的区分度只有在「真撞满配额」与「真被外部掐断」
  两种现场才成立，单测只能复算语义。本轮已复算七种场景（见 PR 描述），
  真撞墙那一侧的现场证据仍旧来自既有构建（`reached maxTurns limit` 一族）。
- 本决策**不**改门禁放行口径：`cnb:trigger` 的宿主事件白名单、`allowFailure`
  的适用范围（只放宽接力载体）都不动。

## 未验证

`CNB_PIPELINE_STATUS=error` 与「失败 stage 名」两处已在既有探针里被实测
（cnb-s4f-1k3c46us9 / cnb-m16-1k3f5s0ri）；第三处所读的两个时长变量此前只在
「开工前量尺」场景实测过，它们在**收尾期**是否仍可读，本决策按平台「环境变量」
篇的声明取用（同一 Job 内平台注入的环境变量在收尾 Stage 仍可解析），
尚未有「撞墙中止的收尾期读数」这一格的直接实测 —— 下一次真撞满配额的构建
即为闭环证据。
