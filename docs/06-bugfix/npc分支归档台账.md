# NPC 分支归档台账（2026-09-25 · Issue #204）

> 本台账的**纪律出处**是 [`AGENTS.md`](../../AGENTS.md) §0「无人值守 AI 协作（NPC）必读」，
> 原文一句即全部依据：
>
> > **流水线配置随分支走，合并后必须收口。** 构建配置按触发分支加载：某个分支改动过
> > `.cnb.yml`（或自动 NPC 分支上跑过配置探测），**该分支每次产生构建都会重新执行它自己那一份**。
> > 于是分支一旦被归档而不清理，过期的配置会永久留着复现同一场失败——与任务内容、与主线代码都无关。
> > 两件硬动作：NPC 分支合并/废弃后，**立即删除该远端分支**……
>
> 本条不是"文档不齐"，是**写入 → 读取的环断在复核者这一环**：纪律写在 AGENTS.md 里，
> 而分支列表不在任何门禁的覆盖面内——悬空扫描只认文档路径与链接，CI 只跑代码与配置。
> 于是"看着写了纪律、其实无人复核"可以长期成立。本台账 + 常驻守卫把这条纪律
> 变成**可复算的读数**。

---

## 一、判定口径（唯一事实源：`scripts/ci/npc_branch_cleanup.py`）

两个 **git 事实**同时成立才算"应当删除"（`stale`）：

1. 该分支头出现在主线某个 merge commit 的**第二父位**（`mergedSourceTips()`）
   —— 即它正是某个已合并请求的源分支头，这就是"经 PR 合并进主线"这件事本身；
2. 该分支头已经是`origin/main` 的**祖先**（`git merge-base --is-ancestor`），
   即提交已在主线里，删掉不丢成果。

只有其中一个成立时判 `keep`：在途的分支可能还有可用的工作，删掉就是丢成果。

**为什么第 1 条不看分支名（2026-09-25 修正，本轮实测）**：
早先口径把「是不是 NPC 工作分支」等同于「名字是否以 `auto/` 开头」。而名字是
平台的产物、不是事实 —— 平台按合并请求的 `head.ref` 决定分支名，NPC 会话既可以建
`auto/*`，也可以建 `fix/*` / `fix-*`。于是同一形态（一个已合并的归档分支仍留在
远端）在一种命名下被拦、在另一种命名下被放行：实测
`fix-caliber-generated`（#217 的 head，作者是 NPC）已是 `origin/main` 的祖先，
而名字前缀口径给它 `keep`；同形态的 `auto/code-exec-sandbox-555c`（#212）
则被正确判为 `stale`。修法是把成员资格改挂在**合并事实上**，不是给名字加白名单。

第 1 条还天然排除仓库默认分支：`main` 的头是那些 merge commit 的**后代**，
永远不会成为其中任何一个的第二父。

**为什么用"是否为祖先"而不是"squash 后 sha 是否对得上"**：本仓的合并请求全部走
merge commit（`git log --merges` 可复核），原提交保留在主线历史里，`--is-ancestor`
即可回答；不存在 squash 形态，故不必为它另造判据。

## 二、复算入口（只读，碰网络的那一次只在这里）

```
python scripts/ci/npc_branch_cleanup.py            # 人读的逐行判定
python scripts/ci/npc_branch_cleanup.py --json     # 机器读数（含 stale 列表）
```

取数前置：本地远端跟踪引用需与远端一致，故先 `git fetch origin --prune`。
**常驻守卫不调它**——判据若依赖网络，CI 会因远端不可达而红，那是"判据随环境漂红"，
不是契约。守卫只对**纯判定函数**喂合成输入做正向与反向控制，
并校验本台账可读（`tests/unit/ci/test_npc_branch_cleanup.py`）。

## 三、本轮处置（Issue #204 会话遗留）

**背景**：Issue #204 的上一轮 NPC 会话把 200 轮配额跑满、被平台中止；它产出的
PR #206 已合并进主线，但**源分支未按 §0 删除**。本轮复核时另发现两条更早的同类遗留。

被删除的三条（删除前均已是 `main` 的祖先，读数由上面的脚本给出）：

| 分支 | 对应合并请求 | 删除前 sha（远端头） | 处置 |
|------|------|------|------|
| `auto/turn-ledger-cross-task-ba7c` | #206 | `3e5542cc` | 已删 |
| `auto/t10d-tool-turn-observability-90` | #207 | `863a15f5` | 已删 |
| `auto/perf-gate-load-free-1790243293` | #185 一族的合并 | `fa432766` | 已删 |

删除后复算读数：`应当删除 0 条：[]`。

### 2026-09-25（Issue #197 批收口）

| 分支 | 对应合并请求 | 处置 |
|------|------|------|
| `auto/ast-scan-text-cache-and-relpath-memo` | #215 | 已删（已合入主线，删除前为 `main` 的祖先） |

### 2026-09-25（判据改由合并事实给出，本轮）

本轮修了判定口径本身（原因见第一节）：成员资格不再看分支名，改看
"分支头是否是主线某个 merge commit 的第二父"。改完立刻多暴露出两条此前
被名字前缀口径放行的归档分支，连同旧口径已报出的一条一并删除：

| 分支 | 对应合并请求 | 删除前 sha（远端头） | 处置 |
|------|------|------|------|
| `auto/code-exec-sandbox-555c` | #212 | `b1d2057e` | 已删 |
| `auto/relay-not-a-gate-217` | #226 | `0fbb5068` | 已删 |
| `auto/skill-name-domain-migration-189` | #225 | `7c129eea` | 已删 |

三条在删除前均由判据给出双事实读数（第二父命中 = 真；是 `main` 的祖先 = 真）。
删除后复算读数：`应当删除 0 条：[]`。

另有一处**漏判**在本轮被记录、不当作已消解：`fix-caliber-generated`（#217 的 head，
作者是 NPC）是旧口径下典型的漏判形态（不叫 `auto/*` 却被合并）。它在本轮开始前
已被另一会话删除，故不再出现在远端；它的合并提交 `0cc0719a` 仍在主线历史里，
作为该形态的**常驻反证样本**留在守卫
`tests/unit/ci/test_npc_branch_cleanup.py::TestCriterionIsMergeFactNotBranchName::testRealRepoMergeRecordYieldsNonAutoPrefixedSourceBranch` 中。

**本台账不登记「当前保留哪些分支」**（此前 §3 有一张这样的表，已删）。原因是
**它自己会过期且无人刷新**：那条表里的 4 行到本轮实测已有 3 行失效
（`auto/issue197-judgement-registration`、`auto/issue197-registration-guard-recover`、
`auto/t11a-uncap-generations-90` 对应提交已合入或分支已删），而 §4 原本就写明
"分支列表本身**不**入台账——它每次 fetch 都在变，抄进文档就立刻过期"。
规则与行为不一致，且没有任何判据拦它——这类"看着登记了、其实早已失效"的行
比不登记更坏：读者会把过期状态当事实。
现由常驻判据
`tests/unit/ci/test_npc_branch_cleanup.py::TestLedgerIsReadableInRepo::test_ledger_records_dispositions_not_live_branch_state`
钉住：台账里出现的每条分支行必须带**已完成**的处置标记（已删 / 已合入 / 已归档），
写"未合并 / 在途"这类当下状态即红。当前在途分支一律**现算**：

```
python scripts/ci/npc_branch_cleanup.py            # 人读
python scripts/ci/npc_branch_cleanup.py --json     # 机器读数
```

### 2026-09-25（#218 后续复核，本轮）

复算入口（先 `git fetch origin --prune`）：`应当删除 5 条`。五条均为 `main` 的祖先，
处置如下：

| 分支 | 处置 |
|------|------|
| `auto/ast-scan-one-shot-retention` | 已删（已合入主线） |
| `auto/branch-archive-fact-criterion` | 已删（已合入主线） |
| `auto/cnb-header-count-single-source-9c14` | 已删（已合入主线） |
| `auto/npc-handoff-predicate-158` | 已删（已合入主线） |
| `auto/t11e-rollup-90` | 已删（已合入主线） |

同轮另删一条**未合并**的并行分支：`auto/relay-criterion-from-pipeline-status`
（其 PR #234 已关闭）。删它的理由不是「已合并」，而是**同一根因只能有一份实现**：
#233 已就「接力判据改读平台在收尾期给出的事实」做了更完整的实现（含 ADR 0022），
两份并存会让 `.cnb.yml` 同一段互相冲突，也无人能判断哪份是事实源（教义第 6 条）。

删除后复算读数：`应当删除 0 条：[]`（`keep` 的未合并分支照旧保留）。

## 四、与既有纪律的关系（不新造平行体系）

- 本台账只承接**一条**纪律（§0 的"合并后立即删分支"），不复制 §0 的其它条款；
- 判定口径与复算入口各只有一处（模块内的 `classifyBranches` 与本文件的第一节），
  守卫做"重算 + 比对"，不复制判据；
- 分支列表本身**不**入台账——它每次 fetch 都在变，抄进文档就立刻过期。
  台账只登记**判定口径**、**复算入口**与**每轮处置的结论与理由**。
