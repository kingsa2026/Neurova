# -*- coding: utf-8 -*-
r"""NPC 单轮输出预算的纪律守卫（Issue #306）。

## 用户看到的"空转"

Issue #306：`@kingsa2026/neurova(DSCoder-max)` 连着几轮"跑了半小时，Issue 上
没有回音、分支上没有提交"，流水线却一律报 `success`。逐轮复算**六条**同形构建的
末轮读数（`cnb build get-build-stage ... --stageId stage-3`，字段取自 AI 请求明细）：

```
cnb-t13-1k3im568q  46 轮 / 1352s   末轮 finish with length, in=2109  out=32000
cnb-p3m-1k3j7bd05  31 轮 /  316s   末轮 finish with length, in=3630  out=32000
cnb-q0r-1k3j7r965  31 轮 /  689s   末轮 finish with length, in=2783  out=32000
cnb-dc6-1k3j9phhs  37 轮 / 1031s   末轮 finish with length, in=2897  out=31998
cnb-90f-1k3if9qm1  46 轮 / 1338s   末轮 finish with length, in=2117  out=32000
cnb-mm8-1k3iu5fr8  36 轮 /  931s   末轮 finish with length, in=1683  out=31999
```

每一轮的读数都用严格解析复算（`^Master[agent][\d+] … finish with …`，
并校验轮号 1..N 连续、与 `done. N turns` 一致 —— 日志里会回显别的构建的日志原文，
不锚行首就会把嵌入内容算成本轮读数）。

同一批里 `finish_reason=length` 的那一轮，`completion_tokens_detail.reasoning_tokens`
恰为 32000、`content` 聚合长度 **0 字符**、`tool_calls` 数 **0**
（构建 `cnb-p3m-1k3j7bd05` 的请求明细逐字：`finish: length`，
`completion_tokens: 32000 / reasoning_tokens: 32000`）。

## 根因（三个事实相乘，缺一不成立）

1. **推理与正文共享单轮输出预算，且预算会被推理吃满**：`thinkingLevel: max`
   下的单轮推理可达 11.9 万字符（`cnb-p3m-1k3j7bd05` 末轮 `thinking_end,
   length: 118537`），远超单轮输出上界。吃满即当轮**零正文、零工具调用** ——
   该轮白跑。
   同配置真对照（同一条 `$` 段、同 `maxTokens=48000`，只有思考档不同）：
   `cnb-i5u-1k3carfm9` / `cnb-9ro-1k3f57fif` / `cnb-s07-1k3f0uhcv`
   分别是 147 / 100 / 234 轮，末轮全是 `finish with stop`，
   **一条 `length` 都没有**。
2. **那一轮恰好是会话的最后一轮**：六条构建的 `done. N turns` 与末轮轮号逐条一致
   （46/31/31/37/46/36），末轮之后再无任何工具命令 —— 会话就停在那一次截断上。
3. **零产出的一轮不会触发接力**：收尾 `if` 的判据是平台在收尾时刻注入的
   `$CNB_PIPELINE_STATUS=error` + 失败 stage 名命中 `npc-go`（ADR 0022）。
   零产出的收官是 `success`，两条都不成立 ⇒ 收尾 Stage 每次 `skipped`
   （六条构建逐条如此：`轮数触顶接力…: 160ms (skipped)`）。

三条相乘的画面：**该轮白跑、会话停在那里、无人接手**。
而真正让损失不可逆的是「全程没有落盘」：这六条构建里
`cnb issues comment` / `git commit` / `git push` 三类命令**一条都没有执行过**
（逐段扫描读数，见下）。同配置的 `cnb-bgo-1k3iskj3v` / `cnb-i65-1k3isrpu4` /
`cnb-b0m-1k3ia89au` 末轮是 `stop`，且分别在第 36~226 / 146~153 / 148~198 轮
执行过落盘命令 —— 它们截断时也不至于全丢。

所以三条合起来解释了用户的观感：**跑满墙钟、零产出、无人接手、成果全丢**。

## 为什么修在指令面

NPC 的运行时在平台侧（`cnbcool/default-npc` 镜像 + 平台 Agent），仓库侧能改的
只有三处：`.cnb.yml` 的运行参数、`.cnb/settings.yml` 的角色人设、`scripts/ci`
的门禁脚本。其中**唯一进 Agent 上下文**的通道是角色 `prompt`
（`npc:go.options` 不认 `prompt` 键，评论触发时提示词一律由角色自带 ——
同源依据见 `tests/unit/ci/test_npc_pipeline_time_budget.py` 的 B 条）。

已在人设里的「时间预算硬约束」只覆盖**墙钟**：sleep 轮询、单条命令超时、
宽匹配 `pkill`。它管不到"单轮输出预算被推理吃满"这条 —— 上一版人设对
单轮输出预算只字未提，于是 Agent 按"等我全部想清楚再一次性交代"的方式工作，
一次长推理就把整轮预算烧掉，连交代的机会都没有。

## 本文件钉三件事（都可证伪）

- **A 条款在册**：每个在册角色的 prompt 都必须含「单轮输出预算纪律」条款，
  且点名四条事实：单轮输出预算、推理吃满、零产出、不会触发接力。
  可证伪：从任一角色 prompt 删掉该条款 → 立刻红。
- **B 条款正文逐字一致**：条款正文（锚点 → 结束锚点）在各角色间必须逐字相同。
  六份人设是手抄的共享正文，改一处漏一处不会有任何红（教义第 6 条）。
  可证伪：只改一个角色的措辞 → 立刻红。
- **C 动作约束可核**：条款必须给出**可执行**的落盘动作（"先落盘"），
  而不是只描述现象 —— 只描述现象等于把纪律写成了背景知识。
  可证伪：把动作句删掉、只留现象描述 → 立刻红。

## 复算口径（防把嵌入日志算成本轮读数）

日志里会**回显别的构建的日志原文**（实测踩过：`cnb-bgo-1k3iskj3v` 的 stage 日志里
嵌着 `cnb-t13-1k3im568q` 的输出），按子串匹配会把嵌入内容算成本轮读数。
本文件引用的读数一律按**行首锚定**的正则解析，并校验轮号 1..N 连续、
与 `done. N turns` 一致后才采纳。

初版曾把 `cnb-1hm-1k3e5csiq` / `cnb-35s-1k3et5jc9` 当"思考档对照"，
复核后**不成立**：它们跑的是平台默认流水线体（stage 只有
`Prepare → npc go → BeforeEnd → …`，无本仓四段门禁；参数为
`maxTokens=64000` / `thinkingLevel=off`），不是本仓配置。
已换成同配置真对照（`cnb-i5u-1k3carfm9` / `cnb-9ro-1k3f57fif` / `cnb-s07-1k3f0uhcv`）。

## 未闭环（点名，不静默）

- 六份人设是**手抄**的共享正文，`.cnb/settings.yml` 首注释声称"共享正文只写
  一份（YAML 锚点）"，实际文件里没有任何锚点。改成锚点要求平台 YAML 解析
  支持且行为等价，本轮**无法在本地自证**（改错会让全部 NPC 配置期失效），
  故不动配置，只登记在本条与 Issue 评论里；漂移风险由上面的 B 条拦住。
- 平台对单轮输出上界的真实口径（32k 是模型侧还是网关侧）无法从仓库侧核实，
  故条款按**实测读数**写，不写死"平台上限是 32000"这一因果断言。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"

#: 条款锚点：整段以它开头，守卫据此定位条款正文。
CLAUSE_ANCHOR = "【单轮输出预算纪律"

#: 条款正文的结束锚点（之后是人设各自的收尾，不参与逐字比对）。
CLAUSE_END_ANCHOR = "本条款由 tests/unit/ci/test_npc_turn_output_budget_discipline.py"

#: 条款必须点名的事实，逐条对应本案的一个读数。
REQUIRED_CLAUSE_TERMS = {
    "单轮输出预算": "预算与墙钟是两件事，此前只写了墙钟那一条",
    "推理": "推理吃满预算是本案的物理成因（末轮 out=32000 全为 reasoning tokens）",
    "零产出": "该轮没有任何正文与工具调用",
    "不会触发接力": "零产出收官是 success，收尾判据两条都不成立 ⇒ 无人接手",
}

#: 条款必须给出的**动作**约束（只描述现象不算纪律）。
REQUIRED_CLAUSE_ACTION = "先落盘"


@pytest.fixture(scope="module")
def personas():
    """在册角色名 → 人设正文（人设是进 Agent 上下文的唯一必达通道）。"""
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失"
    doc = yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read()) or {}
    roles = (doc.get("npc") or {}).get("roles") or []
    assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
    return {
        role.get("name"): (role.get("prompt") or "")
        for role in roles
        if role.get("name")
    }


def clauseBody(prompt: str) -> str:
    """取条款正文（锚点 → 结束锚点），供逐字比对。"""
    if CLAUSE_ANCHOR not in prompt:
        return ""
    tail = prompt.split(CLAUSE_ANCHOR, 1)[1]
    return tail.split(CLAUSE_END_ANCHOR, 1)[0]


class TestClauseIsOnTheReachableChannel:
    """条款必须落在每个在册角色的 prompt 上。"""

    def test_every_role_carries_the_clause(self, personas):
        missing = [
            name for name, prompt in personas.items()
            if CLAUSE_ANCHOR not in prompt
        ]
        assert not missing, (
            "以下角色的人设缺少单轮输出预算条款：\n  " + "\n  ".join(sorted(missing)) +
            "\n没有该条款时，Agent 会把单轮输出预算全烧在推理上（实测末轮 "
            "out=32000、reasoning_tokens=32000、content 0 字符），"
            "该轮零产出且不触发接力，成果随容器丢、Issue 无回音。"
        )

    def test_clause_covers_every_known_failure_mode(self, personas):
        problems = []
        covered = 0
        for name, prompt in personas.items():
            body = clauseBody(prompt)
            if not body:
                # 缺条款的角色由 test_every_role_carries_the_clause 判红；
                # 这里也必须计入覆盖数，否则「全员缺条款」会让本判据静默通过
                # （判据自己空转，比漏判更坏）。
                problems.append(f"{name}: 条款缺失，无法判覆盖")
                continue
            covered += 1
            for term, why in REQUIRED_CLAUSE_TERMS.items():
                if term not in body:
                    problems.append(f"{name}: 条款未覆盖「{term}」（{why}）")
        assert covered, "没有任何角色带该条款 —— 本判据空转"
        assert not problems, "\n  ".join(problems)

    def test_clause_carries_an_action_not_only_a_symptom(self, personas):
        problems = []
        covered = 0
        for name, prompt in personas.items():
            body = clauseBody(prompt)
            if not body:
                problems.append(f"{name}: 条款缺失，无法判动作约束")
                continue
            covered += 1
            if REQUIRED_CLAUSE_ACTION not in body:
                problems.append(f"{name}: 条款没有给出动作约束「{REQUIRED_CLAUSE_ACTION}」")
        assert covered, "没有任何角色带该条款 —— 本判据空转"
        assert not problems, (
            "\n  ".join(problems) +
            "\n只描述现象等于把纪律写成背景知识：必须给出可执行的落盘动作。"
        )

    def test_clause_body_identical_across_roles(self, personas):
        """条款正文在各角色间逐字一致：防"改一处漏一处"的静默漂移。"""
        bodies = {
            name: clauseBody(prompt)
            for name, prompt in personas.items()
            if clauseBody(prompt)
        }
        assert bodies, "没有任何角色带该条款 —— 本判据空转"
        distinct = set(bodies.values())
        assert len(distinct) == 1, (
            "单轮输出预算条款正文在各角色间不一致（改一处必须同步另一处）："
            + ", ".join(sorted(bodies))
        )
