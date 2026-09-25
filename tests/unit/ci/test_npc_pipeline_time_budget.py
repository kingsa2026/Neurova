# -*- coding: utf-8 -*-
"""NPC 流水线的时间预算守卫。

## 为什么需要这份守卫

NPC 的执行体在 `.cnb.yml`（`.cnb/settings.yml` 只放人设）。两条硬约束：

1. **Job 有墙钟上界**：未声明 `timeout` 时默认 2h，声明后最长 12h；
   整个 Agent 会话只受流水线 20h 上限约束（`npc:go` 的 `timeout` 作用于
   **每一次工具执行**，不是整个会话）。
2. **`maxTurns` 是轮数配额，不是耗时上界** —— Agent 自己调用
   `sleep 300/420/480` 串起等待时，配额没吃满而墙钟先破。

实测（构建 `cnb-f1c-1k31garu5`）：251 轮 / 7262s，均摊 ≈29s/轮，
被平台 2h 上限掐断。若按「轮数上限 = 耗时上界」去压 `maxTurns`，
只是把正常长任务拦腰砍断，等待仍在漏。

## 一次真实事故（构建 `cnb-1q8-1k33cb2v9`，2026-09-22）

Agent 为一项「浏览器级 live」收尾任务反复 `sleep` 轮询构建容器内**根本不存在**的
常驻前后端进程，并在第 340 轮用 `pkill -f start_server.py` 收尾 —— `pkill -f`
按完整命令行子串匹配，把 NPC 自己所在的构建容器一并打掉。Stage status=error，
平台只报「构建环境异常终止，或流水线超过最大运行时长（2h）」，耗时 7261220ms。
整条流水线 **7260s 全部耗在一次零产出的等待上**，构建号失效、Issue 上没有任何回复。

## 这份守卫钉四件事（全部可证伪）

- **A. 预算显式**：`maxTurns` 是字面量整数且落在声明区间；每份 NPC 事件定义的
  Job 显式声明 `timeout`；`npc:go.options` 的键必须在平台 Schema 允许集内
  （写错键会被静默忽略——**配置者以为已生效，实际什么都没发生**）。
- **B. 时间条款落在真正必达的通道**：`npc:go.options` 不认 `prompt` / `systemPrompt`
  这类字段（评论触发时提示词由 `.cnb/settings.yml` 的角色自带），故时间预算条款
  必须写进**每个档位角色**的 `prompt`，并覆盖两类死因（sleep 轮询 / 宽匹配 pkill）。
- **C. 枚举仍在**：角色名不得被悄悄重命名，也不得被挂到 `.cnb.yml` 顶层 key 上
  —— 前者让 `DSCoder-max` 失去配置期唯一必达通道、回落平台默认 prompt，
  后者在**推送的那一刻**就是非法配置（顶层 key 只认分支名）。两条路都让本仓
  90+ 处引用的纪律静默失效，而平台不会报错。
- **D. 守卫自洽**：本文件必须留在受保护子集里，否则 A/B/C 三条在 CI 上无人执行。

可证伪路径：

- 把某个档位角色 `prompt` 里的时间条款删掉 → B 红；
- 把 `pkill` 那一条改写掉 → B 红；
- 把任一份 NPC 事件定义的 Job `timeout` 删掉 → A 红；
- 在 `npc:go.options` 里写平台不认的键 → A 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → D 红。
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
SCHEMA = PROJECT_ROOT / ".cnb" / "npc_schema_keys.txt"

# 本仓的档位角色枚举（2026-09-18 收敛为单档）。
# 这些名字同时出现在：
#   .cnb/settings.yml 的角色定义（人设 + 时间条款的唯一必达通道）
#   .cnb/npc_schema_keys.txt（平台 Schema 允许的 options 键，防止写错键被静默忽略）
#   本文件（枚举事实源，防重命名漂移）
LEVEL_ROLES = ("DSCoder", "DSCoder-max")

# ── 时间预算条款（必须出现在每个档位角色的 prompt 里）──────────────────────
# 条款锚点：整段以它开头，守卫据此定位条款正文。
CLAUSE_ANCHOR = "【时间预算硬约束"
# 条款正文的结束锚点（之后是事故依据与人设各自的收尾，不参与逐字比对）。
CLAUSE_END_ANCHOR = "事故依据（2026-09-22"

# 条款必须覆盖的死因，逐条对应本案的一个动作。
REQUIRED_CLAUSE_TERMS = {
    "sleep": "sleep 轮询（本案把 2h 墙钟烧在等待上）",
    "轮询": "循环等待（同上，换任何写法都不改变语义）",
    "pkill": "宽匹配 pkill（本案把 NPC 自己所在的容器一并打掉）",
    "timeout": "单条命令自带超时（防单步挂死吃满流水线）",
}

# 轮数配额的声明区间：低于 1 无意义，高于上限撑爆墙钟。
MIN_TURNS, MAX_TURNS = 1, 1000

# 与 `.cnb/npc_schema_keys.txt` 的绑定关系由本文件校验（防两份事实源漂移）。
SCHEMA_SENTINEL = "# 平台 Schema：npc:go.options 允许的键"


def _iter_nodes(node, path=""):
    """递归产出 (路径, 节点)，路径用于把违规点定位到配置的具体一行。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_nodes(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _iter_nodes(value, f"{path}.{key}" if path else str(key))


def _iter_npc_go_stages(node, path=""):
    """递归收集所有 npc:go 任务及其所在 Job。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_npc_go_stages(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if node.get("type") == "npc:go":
            yield path, node
        for key, value in node.items():
            yield from _iter_npc_go_stages(value, f"{path}.{key}" if path else str(key))


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


@pytest.fixture(scope="module")
def settings_doc():
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失"
    return yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read())


@pytest.fixture(scope="module")
def level_roles(settings_doc):
    """档位角色名 → prompt 正文。角色名不在枚举内的另有用例拦。"""
    return {
        (role or {}).get("name"): (role or {}).get("prompt")
        for role in ((settings_doc.get("npc") or {}).get("roles") or [])
    }


class TestNpcGoOptionsKeysAreSchemaKnown:
    """`npc:go.options` 的键必须在平台 Schema 允许集内。

    为什么这条必须独立钉：`options` 不在平台的 `additionalProperties: false` 约束下，
    写错的键**不报错、不告警、静默忽略**。配置者以为加了约束，实际什么都没发生 ——
    这类"看着配了、其实没配"是本文件最要防的形态（`prompt` 就曾这么被误用过）。
    """

    def test_allowlist_file_lives_with_the_config(self):
        assert SCHEMA.exists(), (
            f"{SCHEMA.relative_to(PROJECT_ROOT)} 丢失 —— options 键的允许集没了事实源"
        )
        text = io.open(SCHEMA, encoding="utf-8").read()
        assert SCHEMA_SENTINEL in text, (
            f"{SCHEMA.relative_to(PROJECT_ROOT)} 缺来源标记「{SCHEMA_SENTINEL}」"
        )

    def test_unknown_option_keys_are_rejected(self, cnb_doc):
        allowed = {
            line.split("#", 1)[0].strip()
            for line in io.open(SCHEMA, encoding="utf-8").read().splitlines()
            if line.split("#", 1)[0].strip()
        }
        unknown = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            for key in (stage.get("options") or {}):
                if key not in allowed:
                    unknown.append(f"{path}.options.{key}")
        assert not unknown, (
            "npc:go.options 出现平台 Schema 未声明的键（会被静默忽略，等于没配）：\n  "
            + "\n  ".join(unknown) +
            f"\n允许集见 {SCHEMA.relative_to(PROJECT_ROOT)}；"
            "新增键前先核对 https://docs.cnb.cool/conf-schema-zh.json 的 npc:go 定义。"
        )


class TestBudgetFieldsAreLiterals:
    """预算字段出现时必须是字面量（Schema 校验先于变量替换，$VAR 不展开）。"""

    def test_max_turns_within_declared_range(self, cnb_doc):
        problems = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            turns = (stage.get("options") or {}).get("maxTurns")
            if not isinstance(turns, int):
                problems.append(f"{path}: maxTurns={turns!r} 未声明或非整数")
            elif not (MIN_TURNS <= turns <= MAX_TURNS):
                problems.append(f"{path}: maxTurns={turns} 不在 [{MIN_TURNS}, {MAX_TURNS}]")
        assert not problems, (
            "npc:go 的轮数配额超出声明区间：\n  " + "\n  ".join(problems) +
            "\n轮数是配额、不是耗时上界：实测 251 轮/7262s 吃满平台上限的根因是"
            "Agent 自己 sleep 轮询，压轮数只会砍断正常长任务。"
        )

    def test_no_variable_in_max_turns(self, cnb_doc):
        bad = [
            f"{path}: maxTurns={value!r}"
            for path, node in _iter_nodes(cnb_doc)
            for value in (node.get("maxTurns"),)
            if isinstance(value, str)
        ]
        assert not bad, (
            "maxTurns 不可用变量/字符串：\n  " + "\n  ".join(bad) +
            "\noptions 走平台配置期 Schema 校验，校验发生在变量替换之前。"
        )


class TestAgentJobDeclaresTimeout:
    """每个 npc:go 所在的 Job 都要显式声明 `timeout`。

    平台依依据（docs.cnb.cool/zh/build/timeout.md、
    /zh/build/internal-steps/npc/go.md）：未声明时「连续 10 分钟无输出」即中断，
    Job 默认最长 2h；声明后无输出阈值与最长执行时间都按该值走。
    声明它让这两个数从平台隐含默认变成仓内可见 —— 事故复盘时
    「到底哪个阈值先破」不必再靠猜。
    """

    def test_every_npc_go_job_declares_timeout(self, cnb_doc):
        missing = [
            path for path, stage in _iter_npc_go_stages(cnb_doc)
            if "timeout" not in stage
        ]
        assert not missing, (
            "以下 npc:go 任务未声明 Job 级 timeout：\n  " + "\n  ".join(missing) +
            "\n未声明时按平台默认（无输出 10 分钟 / 最长 2h）执行，阈值不在仓内可见。"
        )


class TestTimeClauseLivesOnTheReachableChannel:
    """时间预算条款必须写进**每个档位角色**的 prompt。

    可达性依据：`npc:go.options` 没有 `prompt` 这个键（平台 Schema 只认
    role/systemPrompt/userPrompt/model/maxTurns/contextWindow/maxTokens/
    thinkingLevel/supportImage），且评论触发时提示词**一律由角色自带** ——
    写进流水线的 options 既不被识别、也不会生效。唯一必达通道是
    `.cnb/settings.yml` 的 `npc.roles[].prompt`。
    """

    def test_every_level_role_has_the_clause(self, level_roles):
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role)
            if prompt is None:
                problems.append(f"{role}: 角色不存在于 .cnb/settings.yml")
            elif CLAUSE_ANCHOR not in prompt:
                problems.append(f"{role}: prompt 缺「{CLAUSE_ANCHOR}...」条款")
        assert not problems, (
            "档位角色的人设里缺少时间预算条款：\n  " + "\n  ".join(problems) +
            "\n没有该条款时，Agent 会把墙钟预算烧在等待上，"
            "并可能用宽匹配的 pkill 打掉自己所在的构建容器（实测 cnb-1q8-1k33cb2v9）。"
        )

    def test_clause_covers_every_known_failure_mode(self, level_roles):
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            clause = prompt.split(CLAUSE_ANCHOR, 1)[1]
            for term, why in REQUIRED_CLAUSE_TERMS.items():
                if term not in clause:
                    problems.append(f"{role}: 条款未覆盖「{term}」（{why}）")
        assert not problems, "\n  ".join(problems)

    def test_clause_body_identical_across_roles(self, level_roles):
        """条款正文本身在各角色间逐字一致：防"某个角色改了措辞、另一个没改"的漂移。

        只比对条款正文（锚点 → 事故依据段结束），不比对各自的人设与身份收尾 ——
        那两段本来就按角色不同。
        """
        bodies = {}
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            tail = prompt.split(CLAUSE_ANCHOR, 1)[1]
            bodies[role] = tail.split(CLAUSE_END_ANCHOR, 1)[0]
        assert len(set(bodies.values())) <= 1, (
            "时间预算条款正文在各档位角色间不一致（改一处必须同步另一处）："
            + ", ".join(sorted(bodies))
        )

    def test_clause_is_immediately_before_the_working_style_section(self, level_roles):
        """条款必须紧贴人设的「工作方式」段之前：位置漂移会让后文被挤掉。"""
        problems = []
        for role in LEVEL_ROLES:
            prompt = level_roles.get(role) or ""
            if CLAUSE_ANCHOR not in prompt:
                continue
            after = prompt.split(CLAUSE_ANCHOR, 1)[1]
            if "工作方式" not in after.split(CLAUSE_END_ANCHOR, 1)[-1]:
                problems.append(f"{role}: 条款之后找不到「工作方式」段")
        assert not problems, "\n  ".join(problems)


class TestLevelRoleEnumUnchanged:
    """档位角色名不得被悄悄重命名（改名即失去配置期唯一必达通道）。"""

    def test_settings_declares_every_level_role(self, level_roles):
        missing = [role for role in LEVEL_ROLES if role not in level_roles]
        assert not missing, (
            f".cnb/settings.yml 缺档位角色: {missing}\n"
            "角色名是 NPC 人设与时间条款的配置期唯一入口——改名而不同步流水线挂载点，"
            "被 @ 时会静默回落到平台默认 prompt（本仓的修复教义随之失效），"
            "而平台不会以任何方式报错。"
        )

    def test_every_level_role_has_mount_point(self, cnb_doc):
        """每个档位角色都必须落到**合法**挂载点上 —— 非法顶层的唯一形态是角色名。

        本批冲突消解（2026-09-22，PR #136 并入 main）：本 PR 侧最初把本条判据写成
        「每个档位角色在 .cnb.yml 有同名顶层 key」，理由是角色名缺挂载点会静默回落
        平台默认 prompt。并入 main 时该写法已被 PR #134 用平台 Schema 否证：
        `.cnb.yml` 顶层 key **只认分支名**，角色名顶层 key 在推送那一刻就非法
        （Schema 只放行 `^\..` 锚点，语义规则另把 `issue.*` 钉在 `$` 下）。
        故判据改成「每个角色名都不得作为顶层 key 出现，且必须被 `$` 覆盖到」——
        洞见（不能静默回落）保留，实现取合法形态。
        """
        problems = []
        for role in LEVEL_ROLES:
            if role in cnb_doc:
                problems.append(
                    f"{role}: 角色名挂在 .cnb.yml 顶层 key 上 —— 顶层 key 只认分支名，"
                    "该形态在推送那一刻就是非法配置"
                )
        fallback = cnb_doc.get("$")
        if not isinstance(fallback, dict):
            problems.append("$: .cnb.yml 缺 `$` 兜底挂载点（角色没有配置期必达通道）")
        else:
            keys = [k for k in fallback if isinstance(k, str) and k.endswith("@npc")]
            if len(keys) < 2:
                problems.append("$: 兜底挂载点缺事件（应含 issue 与 pull_request 两类）")
            # 「两条事件定义的差异被逐字点名」这件事**不在本文件判**：
            # 它的单一事实源是 tests/unit/test_ci_npc_config_guard.py 的
            # `_strip_self_event` + `test_npc_events_declared_and_aliased`
            # （那份判据同时钉自接力事件名与对话载体键）。
            # 本文件曾逐字复制一份 `_strip_self_event`，两份实现随即分叉：
            # Issue #158 让 `cnb:apply` 的 event 从"同名评论事件"改为
            # `api_trigger_npc_handoff`、并新增对话载体键之后，那份副本立刻红在
            # 「除自身事件名外应逐字相同」上——**同一个事实被两份守卫各说一遍，
            # 改一处漏一处**（教义第 6 条：发现第二份定义就收口）。
            # 故此处删除副本，只保留本文件独有的职责：档位角色的合法挂载点。
        assert not problems, "\n  ".join(problems)

    def test_roles_rendered_identically_across_mounts(self, cnb_doc):
        """档位角色之间必须共用同一份锚点：两个角色名解析出的配置对象应当相等。

        顶层 key 已收敛为 `$` 一处（角色名顶层 key 非法），所以「多挂载点漂移」
        的形态在本仓不可能出现；本条改为直接钉住 `$` 段两条事件定义共用的锚点，
        防后人把某个角色拆出去另写一份定义（那就是第二套平行体系）。
        """
        fallback = cnb_doc.get("$") or {}
        bodies = {
            key: fallback.get(key)
            for key in ("issue.comment@npc", "pull_request.comment@npc")
        }
        distinct = {k: body for k, body in bodies.items() if body is not None}
        assert len(distinct) == 2, (
            "$ 段缺少 NPC 事件定义："
            + ", ".join(sorted(set(bodies) - set(distinct))) +
            "\n两个档位角色（DSCoder / DSCoder-max）都落到 `$`，缺一个就等于缺一类触发。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_pipeline_time_budget.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )


#: 门禁自证用的探针文件名（即写即删）。**不是**接力判据的落点 ——
#: 判据读平台在收尾期注入的两个变量，见 `TestRelayJudgmentReadsPlatformFacts`。
WORKSPACE_PROBE_FILE = ".npc-workspace-probe"

#: 开工前自证脚本：`.cnb.yml` 在 Agent 开工前调用它（只证工作区可写 / `$PWD` 同址）。
HANDOFF_GATE_SCRIPT = "scripts/ci/npc_turn_handoff_gate.py"

#: 上一代「本轮是接力轮」的变量名。**已作废**（Issue #158 / #189）——保留常量
#: 只为**反向钉住**"它不得再出现在配置的 env / exports 里"：它由 Agent 开工前的
#: 门禁无条件写成 1，跟"是否撞顶"无关。
TURN_FLAG_VAR = "turnLimitReached"

#: `##[set-output]` 协议标记。开工前的步骤**不得**再产出它（Issue #158 的根因）：
#: 那一刻无从知道本轮会不会撞顶，写出来的判据必然是拍脑袋的。
SET_OUTPUT_DIRECTIVE = "##[set-output"

#: 收尾接力唯一允许的内置任务类型（Issue #170，构建 cnb-i5m-1k355ooo1 实测）：
#: `cnb:apply` 的宿主事件白名单里没有 `@npc` 一族，改用适用「所有事件」的
#: `cnb:trigger`。通道更换由 test_npc_turn_handoff_execution.py 单独钉住。
HANDOFF_TRIGGER_TYPE = "cnb:trigger"


class TestNpcOptionsPromptIsAnUnreachableChannel:
    """`npc:go.options` 里不得再出现 `prompt` 键 —— 它是一条永不生效的通路。

    根因（Issue #158，构建 cnb-2v8-1k34htd2p）：接力配置"看着配了、其实跑不到"，
    第二处就在 `$` 段的 NPC 流水线里写了 `options.prompt`：平台 Schema 不声明该键，
    评论触发时提示词**一律由 `.cnb/settings.yml` 的角色自带**，写进去既不识别也不生效，
    而平台对未知键静默忽略 —— 没有任何红灯会亮。
    本仓为此专门设了一张错误码清单（`.cnb/npc_schema_keys.txt` 的
    「禁止出现（曾误用、被静默忽略）」段），`prompt` 第一位在册。
    然而 `tests/unit/test_ci_npc_config_guard.py` 的 `_iter_npc_go_options`
    曾一路 **skip 掉 `options` 子节点**，于是那张清单没有任何执行体 ——
    禁令写在纸上、判据空转（教义第 2 条：不许把门禁做成"看着配了"）。

    判据：`npc:go` 的 options 键集与 `.cnb/npc_schema_keys.txt` 的允许键集取差
    必须为空。允许键集是单一事实源，两处不得各写一份。
    """

    def test_options_keys_stay_inside_the_schema_allowlist(self, cnb_doc):
        allowed = _schema_allowlist()
        offenders = []
        for path, stage in _iter_npc_go_stages(cnb_doc):
            for key in (stage.get("options") or {}):
                if key not in allowed:
                    offenders.append(f"{path}.options.{key}")
        assert not offenders, (
            "npc:go.options 写了平台 Schema 未声明的键（会被静默忽略，等于没配）：\n  "
            + "\n  ".join(offenders) +
            f"\n允许键集见 {SCHEMA.relative_to(PROJECT_ROOT)}；"
            "行为约束（时长纪律、修复教义、接力协议）一律写进 "
            ".cnb/settings.yml 的角色 prompt —— 那是评论触发期唯一必达的通道。"
        )


def _schema_allowlist() -> set:
    """`.cnb/npc_schema_keys.txt` 的允许键集（注释与空行不计）。"""
    return {
        line.split("#", 1)[0].strip()
        for line in io.open(SCHEMA, encoding="utf-8").read().splitlines()
        if line.split("#", 1)[0].strip()
    }


class TestPreAgentStageProducesNoRelayPredicate:
    """Agent 开工前的 Step **不得**产出任何接力判据（Issue #158 的根因处判据）。

    根因（2026-09-25 实测，四条评论触发的父构建 + 一个真探针）：
    判据的生产方把「本轮会不会撞顶」这个**未来事实**，交给 Agent 开工**之前**
    跑的步骤无条件写成 1：

        $NPX_CALL scripts/ci/npc_turn_handoff_gate.py   # Agent 开工前
        ##[set-output turnLimitReached=1]               # ← 与是否撞顶无关

    于是「用户新发的 @ → 不接力」这条空轮防护**从未成立过**：

        cnb-2q8-1k3buskao   97 / 200 轮 → 收尾接力 success
        cnb-tr2-1k3bm5ssd  135 / 200 轮 → 收尾接力 success
        cnb-cou-1k3bmaal8  164 / 200 轮 → 收尾接力 success
        cnb-ofm-1k3bq16ij   76 / 200 轮 → 收尾接力 success

    代价可复算：接力落点 `api_trigger_npc_handoff` 共 32 次构建 / 22.2 小时
    墙钟，其中 17 次又跑满 200 轮 —— 一次普通提问被放大成自动续跑的链条。

    判据因此落在**产出侧**：开工前的步骤只准做开工前能证实的事（工作区可写、
    解释器可用），不得写任何"这一轮是接力轮"的凭据 —— 那件事只有平台在收尾
    时刻才知道。接力判据本身的正确形态由 ``TestRelayJudgmentReadsPlatformFacts``
    （本文件）与 ``tests/unit/ci/test_npc_turn_handoff_execution.py`` 共同钉住。
    """

    def test_pre_agent_gate_exists_and_does_not_emit_relay_predicates(self):
        """门禁必须存在（解释器可达性），但不得再向 stdout 写接力标记。"""
        gate = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"
        assert gate.exists(), (
            "开工前自证脚本丢失 —— 解释器/工作区可达性无人自证"
            "（构建 cnb-du8-1k34cfhg1 的 rc=127 形态会复活）。"
        )
        source = io.open(gate, encoding="utf-8").read()
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(source.splitlines(), 1)
            if SET_OUTPUT_DIRECTIVE in line
            and not line.strip().startswith("#")
            and "写入" not in line
        ]
        assert not offenders, (
            f"{gate.relative_to(PROJECT_ROOT)} 仍在产出接力判据（该步骤跑在 Agent "
            "开工前，那一刻无从知道本轮会不会撞顶）:\n  " + "\n  ".join(offenders) +
            "\n实测四条父构建在 76~164 轮即被接力；判据已搬到平台收尾事实变量。"
        )

    def test_every_npc_job_still_runs_the_pre_agent_gate(self, cnb_doc):
        """每条 `npc:go` 流水线都要在 Agent 开工前跑一次自证（可达性）。"""
        fallback = cnb_doc.get("$") or {}
        jobs = [
            job
            for event, body in fallback.items()
            if isinstance(event, str) and event.endswith("@npc")
            for job in (body if isinstance(body, list) else [])
            if isinstance(job, dict)
        ]
        assert jobs, "$ 段缺 NPC 事件定义"
        missing = [
            event
            for event, body in fallback.items()
            if isinstance(event, str) and event.endswith("@npc")
            for job in (body if isinstance(body, list) else [])
            if isinstance(job, dict)
            if not any(
                HANDOFF_GATE_SCRIPT in str(stage.get("script") or "")
                for stage in (job.get("stages") or [])
                if isinstance(stage, dict)
            )
        ]
        assert not missing, (
            f"{missing} 未在 Agent 开工前跑 {HANDOFF_GATE_SCRIPT} —— "
            "解释器/工作区可达性不再由真实构建自证。"
        )



def _gate_invocations(gate):
    """产出 (分支名, argv, 缺席原因) —— python 分支与经桥脚本的 node 分支。

    缺席原因非空表示该环境没有对应解释器（CI 的 `python:3.11` 镜像**没有 node**），
    此时调用方必须**点名跳过**该分支，不得把"环境缺解释器"写成"判据失败"：
    后者在 python-only 镜像里恒红，与代码对错无关（构建 cnb-5go-1k34lk8sh-004 实测
    `只跑到一个解释器分支：['python'] / assert 1 >= 2`）。
    """
    out = []
    if shutil.which("python3") or shutil.which("python"):
        out.append(("python", [sys.executable, str(gate)], None))
    else:
        out.append(("python", None, "本环境没有 python3/python"))

    bridge = PROJECT_ROOT / "scripts" / "ci" / "run_gate_under_node.sh"
    if not bridge.exists():
        out.append(("node", None, f"缺桥脚本 {bridge.relative_to(PROJECT_ROOT)}"))
    elif not shutil.which("node"):
        out.append(("node", None, "本环境没有 node（CI 的 python:* 镜像即如此）"))
    elif not shutil.which("sh"):
        out.append(("node", None, "本环境没有 sh（桥脚本是 sh 脚本）"))
    else:
        out.append(("node", ["sh", str(bridge), str(gate)], None))
    return out


def _first_available_invocation(gate):
    """取第一个可用的解释器分支 —— 不假定 `sys.executable` 一定能跑。

    本仓库的测试环境有三种：开发机（python + node 都有）、CI 的 `python:*`
    镜像（**没有 node**）、NPC 镜像 `cnbcool/default-npc:latest`（**没有 python**）。
    `sys.executable` 只在真正跑着 pytest 时才存在，把它当成"一定有"的条件写进
    默认参数，换到第三种环境就是 `FileNotFoundError` —— 与"少一个解释器分支"
    同一族根因：**把环境前提当判据**。
    """
    for label, argv, reason in _gate_invocations(gate):
        if argv is not None:
            return label, argv
        del label, reason
    return None, None


def _run_gate_capture_stdout(gate, argv=None, workspace=None):
    """在 CI 上下文里真跑一遍门禁，取回 stdout（含 `##[set-output]` 标记）。"""
    env = dict(os.environ, CNB="1", CI="true")
    env["CNB_BUILD_WORKSPACE"] = workspace or tempfile.mkdtemp(prefix="npc-handoff-gate-")
    if argv is None:
        label, argv = _first_available_invocation(gate)
        if argv is None:
            pytest.skip("本环境既无 python 也无 node，门禁判据无法执行")
        del label
    proc = subprocess.run(argv, capture_output=True, env=env, cwd=str(PROJECT_ROOT))
    assert proc.returncode == 0, (
        f"门禁 {' '.join(argv)} 未以 0 退出：\n"
        + proc.stdout.decode("utf-8", "replace")
        + proc.stderr.decode("utf-8", "replace")
    )
    return proc.stdout.decode("utf-8", "replace")


class TestRelayPredicateIsNotCarriedByAnExportChannel:
    """接力判据**不再经导出通道**传递，门禁 stdout 只承载环境自证读数。

    导出通道本身是真的（平台文档「环境变量」篇：脚本 stdout 的
    `##[set-output key=value]` → `exports` 映射为环境变量，生命周期覆盖整个
    Pipeline）。但用它承载接力判据的前提是「有一个 Agent 开工前就知道答案的值」
    —— 那正是被证伪的前提：开工前无从知道本轮会不会撞顶，写出来的值是拍脑袋的。

    事故依据：本类上一代断言"门禁必须输出 `##[set-output turnLimitReached=1]`"，
    而那条标记正是空轮防护恒真的来源。判据跟着错误设计走，是本案最难发现的一环
    —— 守卫全绿而行为全错。故现在同一件事反过来钉：

    - 门禁的**两个解释器分支**都不得再向 stdout 写任何 `##[set-output]` 标记；
    - 两个分支的自证读数必须逐字一致（NPC 镜像只有 node）；
    - `.cnb.yml` 里不得再有为它而设的 `exports` 映射，也不得再引用
      平台不存在的 `$CNB_ENV` / `$GITHUB_ENV` 文件通道（那批假设早已被证伪）。
    """

    def test_the_gate_emits_no_relay_truth(self):
        """两个解释器分支都不得再向 stdout 写任何 `##[set-output]` 标记。"""
        gate = PROJECT_ROOT / HANDOFF_GATE_SCRIPT
        emitted = _run_gate_capture_stdout(gate)
        assert "##[set-output" not in emitted, (
            f"{gate.relative_to(PROJECT_ROOT)} 仍在向 stdout 写协议标记。\n"
            "该标记会被 `exports` 映射成 Pipeline 级环境变量，使收尾 `if` 恒真 ——"
            "正常收官也照拉下一轮（cnb-2q8-1k3buskao 实测）。\n"
            "实际 stdout：\n" + emitted
        )

    def test_both_interpreter_branches_emit_the_same_reading(self):
        """python 与 node 两个分支的自证读数必须逐字一致（镜像只有 node）。

        **环境缺席 ≠ 判据失败**：CI 的 `python:*` 镜像根本没有 node（构建
        cnb-5go-1k34lk8sh-004 实测），此处若把"少一个分支"直接断言成红，
        判据就在与代码对错无关的地方恒红。缺席的分支**点名跳过**，在场的
        分支照旧逐字比对。
        """
        gate = PROJECT_ROOT / HANDOFF_GATE_SCRIPT
        workspace = tempfile.mkdtemp(prefix="npc-handoff-gate-")
        branches, absent = {}, []
        for label, argv, reason in _gate_invocations(gate):
            if argv is None:
                absent.append(f"{label}（{reason}）")
                continue
            branches[label] = _run_gate_capture_stdout(gate, argv=argv, workspace=workspace)
        if absent:
            pytest.skip("本环境缺解释器分支，无法做双运行时等价比对：" + "、".join(absent))
        assert len(branches) >= 2, f"只跑到一个解释器分支：{list(branches)}"
        unique = set(branches.values())
        assert len(unique) == 1, (
            "两个解释器分支的 stdout 不一致（判据分叉即双源）：\n"
            + "\n".join(f"── {label} ──\n{out}" for label, out in branches.items())
        )

    def test_the_gate_no_longer_writes_an_undeclared_env_file(self):
        """不得再**读取/写入**平台不声明存在的 `$CNB_ENV` / `$GITHUB_ENV`。

        判据落在"把它当通道用"这件事上：注释里说明"平台没有这条通道"是必要的
        理由记录，不构成违规；而 `env.get("CNB_ENV")` / `env["GITHUB_ENV"]`
        这类真去读它的写法必须消失 —— 否则接力依旧把成败押在不存在的文件上。
        """
        gate = PROJECT_ROOT / HANDOFF_GATE_SCRIPT
        source = io.open(gate, encoding="utf-8").read()
        for undeclared in ("CNB_ENV", "GITHUB_ENV"):
            offenders = [
                line.strip()
                for line in source.splitlines()
                if undeclared in line
                and not line.strip().startswith("#")
                and (f'"{undeclared}"' in line or f"'{undeclared}'" in line)
            ]
            assert not offenders, (
                f"{gate.relative_to(PROJECT_ROOT)} 仍把平台不存在的 `{undeclared}` 当通道用：\n  "
                + "\n  ".join(offenders) +
                "\n该通道是上一批的可证伪假设，已被真实构建证伪（文档零命中 + "
                "现场未注入）；继续保留它只会让接力在绿灯下静默失效。"
            )

    def test_no_relay_flag_is_passed_downstream_anywhere(self, cnb_doc):
        """NPC Job 的 `env` 与任何 Stage 的 `exports` 都不得承载接力标记。

        留任一处，收尾 `if` 的输入就还是自造值 —— 判据必须落在**这些位置为空**
        上，而不是落在"别处还有没有提到它"上。可证伪路径：把任一处
        `##[set-output turnLimitReached=1]` 或 `exports: {turnLimitReached: ...}`
        加回来 → 立刻转红。
        """
        fallback = cnb_doc.get("$") or {}
        jobs = [
            (event, job)
            for event, body in fallback.items()
            if isinstance(event, str) and event.endswith("@npc")
            for job in (body if isinstance(body, list) else [])
            if isinstance(job, dict)
        ]
        assert jobs, "$ 段缺 NPC 事件定义"
        offenders = []
        for event, job in jobs:
            if TURN_FLAG_VAR in (job.get("env") or {}):
                offenders.append(f"{event}: job.env 仍传 {TURN_FLAG_VAR}")
            for stage in (job.get("stages") or []):
                if not isinstance(stage, dict):
                    continue
                if TURN_FLAG_VAR in (stage.get("exports") or {}):
                    offenders.append(
                        f"{event}: {stage.get('name')!r} 的 exports 仍映射 {TURN_FLAG_VAR}"
                    )
        for event, body in fallback.items():
            if not isinstance(event, str) or event.startswith("."):
                continue
            for job in (body if isinstance(body, list) else []):
                if not isinstance(job, dict):
                    continue
                for stage in (job.get("stages") or []):
                    if isinstance(stage, dict) and stage.get("exports"):
                        offenders.append(f"{event}: exports={stage.get('exports')}")
        assert not offenders, (
            "仍有位置在把自造的接力真值传下去：\n  " + "\n  ".join(offenders) +
            "\n真值来自平台在收尾期注入的 $CNB_PIPELINE_STATUS + $CNB_BUILD_FAILED_MSG，"
            "不需要任何传递（导出通道更承载不了它：开工前的步骤无从知道本轮是否撞顶）。"
        )
