# ADR 0022: 接力判据的事实源（读平台在收尾期注入的事实，不读构建侧自造的真值）

- **Status**: Accepted
- **Date**: 2026-09-25
- **Decision Maker**: Issue #189 收口

## Context

「NPC 用满轮数配额后自动开启下一轮」这件事需要一个判据。同一处判据改过三轮，
每轮都被下一个真实构建推翻 —— 而每一轮的守卫都是绿的。

**第 1 轮：燃料由 Agent 在最后一轮自己写。**
`npc:go` 撞 `maxTurns` 时平台只把 Agent 中止，**不执行任何收尾指令或工具调用**
（构建 cnb-2e8-1k341d9s1：201 轮 / 3191326ms；cnb-2v8-1k34htd2p：200 轮 /
2362852ms）。Agent 没有机会写，读端 `if` 恒假、收尾 Stage 每次 `skipped`，
用户在 Issue 上没有任何回音。

**第 2 轮：燃料改由构建侧在 Agent 开工前无条件写。**
门禁的判据是 `CNB` 非空（真实构建里恒真），于是
`##[set-output turnLimitReached=1]` → `exports` → Pipeline 级环境变量，
收尾 `if` 恒**真**。空轮防护全失效 —— 未撞顶的正常收官也照拉下一轮：

```
cnb-2q8-1k3buskao  Agent stage success（1774s，未撞顶）→ 拉 cnb-lga-1k3c0itrj
cnb-kdg-1k3bv22ct  Agent stage success（3977s，未撞顶）→ 拉 cnb-fln-1k3c2rjk7
```

两轮的错误方向相反，根因是同一个：**该变量回答的是「上一轮是否用满配额」，
而这个事实在构建侧根本不存在** —— 它的唯一得知时点是收尾期。

## Decision

**接力判据读平台在收尾期注入的事实，构建侧不产出任何被 `if` 消费的真值。**

平台「环境变量」篇声明 `endStages` 内可读：

| 变量 | 含义 |
|------|------|
| `CNB_PIPELINE_STATUS` | 流水线构建状态（`success` / `error` / `cancel`） |
| `CNB_BUILD_FAILED_MSG` | 流水线构建失败的错误信息 |

真 `npc:go` 撞 `maxTurns: 1` 的读数（构建 cnb-s4f-1k3c46us9 / cnb-p2q-1k3c2g7u3）：

```
PROBE_STATUS=[error]
PROBE_MSG=[Agent aborted: reached maxTurns limit (1)]
PROBE_STAGE=[force-maxTurns-abort]
```

判据形态（全仓一处）：

```yaml
if:
  - '[ "$CNB_PIPELINE_STATUS" = "error" ]'
  - 'case "$CNB_BUILD_FAILED_MSG" in *"reached maxTurns limit"*) true;; *) false;; esac'
```

两个条件必须同时成立。**只看 `status` 不够**：`stages` 失败的原因有很多种
（门禁红、依赖装不上、脚本报错），只有"用满轮数"才该续跑 —— 把任何失败都接成
新一轮，等于把真故障转写成烧配额。

## Consequences

- 门禁脚本（`scripts/ci/npc_turn_handoff_gate.py`）自本决策起**不再写任何接力标记**。
  它保留的职责是构建环境自证（工作区可写、`$PWD` 是否与 `$CNB_BUILD_WORKSPACE` 同址），
  探针文件名 `.npc-workspace-probe` 带 `probe` 就是为了一眼看出它没有下游消费者。
- 接力载体（`api_trigger_npc_handoff`）自己也要有 `endStages`：否则接力只有一跳，
  第一轮撞顶拉起的第二轮若再撞顶，链条即断 —— 与最初那个断点同形，只是往后挪了一格。
- 人设不再教"往某个文件写标记"；改为点明判据读哪两个平台变量，并显式禁止 Agent
  自造状态文件（那是平行判据的唯一入口）。
- 本决策**废除**第 2 轮的产物：`turnLimitReached` 变量、`exports` 映射、
  `.npc-turn-handoff` 文件协议。保留常量只为反向钉住"它们不得再出现"。

## 为什么保留了旧守卫而不是删掉

跟随错误设计的守卫必须**改判据**，不能沉默删除 —— 它们曾经全绿，却服务了一个
错误的设计（"必须输出 `##[set-output turnLimitReached=1]`"）。本决策把同一批守卫
反过来说：门禁不得输出该标记、Job 不得透传它、人设不得提该文件。
删掉它们等于把这段历史从判据里抹掉，下一个人会再犯一次。

## 未验证

本次改动的端到端确认需要**下一轮真撞满配额的构建**：收尾 Stage 若由 `skipped`
变为 `executed` 且拉起了下一条 `api_trigger_npc_handoff`，即为闭环。
本地已复算平台 `if` 语义的四种场景（撞顶 / 正常收官 / 门禁红 / 用户新发 @），
但那是语义复算，不是平台端到端实测。
