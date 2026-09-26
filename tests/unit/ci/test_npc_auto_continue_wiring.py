# -*- coding: utf-8 -*-
"""NPC 自动续跑（轮数/墙钟中止 → 下一轮）**接线**守卫（Issue #272）。

## 这一版修的是什么（live 实测，不是推测）

用户口径是「NPC 自动续跑下一轮」。本仓把这条链拆成三段：
评论触发 → Agent 跑 → 收尾判据命中则 `cnb:trigger` 拉起接力载体
`api_trigger_npc_handoff` → 载体里再跑 npc:go。

链路本身在原理上成立（探针 cnb-s4f-1k3c46us9 实测：`endStages` 里
`CNB_PIPELINE_STATUS=error`、`CNB_BUILD_FAILED_MSG=Agent aborted: reached
maxTurns limit (1)`，`reveal-end-facts` 能读到）。但 PR #273 把角色改名后，
**同一根因的两个命中点同时失效**，而没有任何一处会响亮：

1. **接力载体的 `role:` 指向已不存在的角色**。
   PR #273 把角色改名为 `DSCoder-Red / -Green / -Yello / -Blue` 并删掉了
   `DSCoder`，而 `.cnb.yml` 的载体仍写 `role: DSCoder`。
   实测（本仓真构建 cnb-ffc-1k3f5v4rm，`api_trigger` + `role: DSCoder`）：

       PROBE_MSG=[Role "DSCoder" not found in .cnb/settings.yml.
                  Available: DSCoder-Red, DSCoder-Green, DSCoder-Yello, DSCoder-Blue]

   ⇒ 接力轮一启动就失败，零产出。这正是「子流水线无果」。

2. **判据只认猜测的报错原文**。硬中止时 `CNB_BUILD_FAILED_MSG` 并不是一段
   平台文案，而是**失败 stage 最后一行输出**（实测 cnb-m16-1k3f5s0ri：Job 被
   SIGKILL 后 `MSG=[start]`，即脚本自己最后 echo 的那行）。于是
   `*"超过最大运行时长"*` 这类片段命中与否全看运气，而不是看「是否真被中止」。

## 判据（都指向**确定性事实**，不猜文案）

- **A（根因，单一事实源）**：`.cnb.yml` 里每个 `role:` 取值都必须在
  `.cnb/settings.yml` 的 `npc.roles` 名单里。**字面量**与平台变量形态
  （`$CNB_NPC_NAME` 一族）都要判：字面量必须与名单逐字命中，变量形态另由
  `tests/unit/ci/test_npc_handoff_role_continuity.py` 判「取值有真实来源」。
  改名漏改即红。
- **B（判据读 stage 名）**：每条接力的 `if` 都必须读
  `$CNB_BUILD_FAILED_STAGE_NAME` —— 它由平台在收尾期注入，取值是**失败 stage 的
  名字**，与「该 stage 打印了什么」无关（实测见上）。
- **C（双向锁）**：npc:go 所在 stage 的名字必须带 ASCII 标记 `npc-go`，
  且 `if` 匹配的正是该标记。改名与改判据任缺其一 → 红。
- **D（载体角色身份有据）**：接力载体的 `role:` 取的是**变量形态**时，
  该变量必须真由上一跳的收尾接力经 `cnb:trigger.options.env` 供上；
  取的是**字面量**时，必须等于 `npc.defaultRole`。两种形态都不得成为
  一处无人守的引用。

## 与「随轮传递」的衔接（PR #276 消解冲突时的收敛）

载体 role 的两个口径各有事实源，不再互相打架：
**身份随轮传递**（`role: $handoffRole`，根为平台注入的 `$CNB_NPC_NAME`）——
角色再改名自动跟随，是 Issue #272 的根修方向；
**单点字面量**（`role: DSCoder-Red`）—— 改名即与名单分叉。
两者都必须在名单里命中，故按当前口径收敛为随轮传递，
`npc.defaultRole` 只作名单自洽性读数（由角色连续性守卫判「在册」）。

可证伪：把 `role:` 写回 `DSCoder` → A 红；把 `if` 里的
`CNB_BUILD_FAILED_STAGE_NAME` 删掉 → B 红；把 stage 名里的 `npc-go` 标记去掉
→ C 红；把载体 `role:` 改成 `$notProvidedAnywhere` → D 红。
"""
import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
ADMISSION = PROJECT_ROOT / "scripts" / "ci" / "npc_role_admission.py"

#: 平台在收尾期注入的「失败 stage 名」——接力判据的确定性事实源。
FAILED_STAGE_VAR = "CNB_BUILD_FAILED_STAGE_NAME"

#: npc:go 所在 stage 名字里必须带的 ASCII 标记（判据按它匹配）。
GO_STAGE_MARKER = "npc-go"

#: 接力落点事件。
HANDOFF_EVENT = "api_trigger_npc_handoff"

#: 接力触发的内置任务类型。
HANDOFF_TRIGGER_TYPE = "cnb:trigger"


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


@pytest.fixture(scope="module")
def settings_doc():
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失"
    return yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read())


def _role_names(settings_doc):
    return [r.get("name") for r in ((settings_doc.get("npc") or {}).get("roles") or [])]


def _walk(node):
    """深度遍历 YAML 结构，产出所有 dict。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _relay_stages(cnb_doc):
    """产出 (挂载点, 接力 Stage)。"""
    for mount, body in cnb_doc.items():
        for event, event_body in (body or {}).items() if isinstance(body, dict) else []:
            for i, job in enumerate(event_body if isinstance(event_body, list) else []):
                if not isinstance(job, dict):
                    continue
                for stage in (job.get("endStages") or []):
                    if isinstance(stage, dict) and stage.get("type") == HANDOFF_TRIGGER_TYPE:
                        yield f"{mount}.{event}[{i}]", stage


def _npc_go_stages(cnb_doc):
    """产出 (挂载点, Stage) —— 所有 `type: npc:go` 的 stage。"""
    for mount, body in cnb_doc.items():
        for event, event_body in (body or {}).items() if isinstance(body, dict) else []:
            for i, job in enumerate(event_body if isinstance(event_body, list) else []):
                if not isinstance(job, dict):
                    continue
                for stage in (job.get("stages") or []):
                    if isinstance(stage, dict) and stage.get("type") == "npc:go":
                        yield f"{mount}.{event}[{i}]", stage


#: 平台变量形态的 `role:` 取值（`$NAME`；仅接受环境变量名形态）。
#: 它同样必须在册 —— 只是「在册」的判据换成了「取值有真实来源」，
#: 由 tests/unit/ci/test_npc_handoff_role_continuity.py 判：
#: 载体读的 `$handoffRole` 必须真由上一跳的收尾接力供上，且根节点是
#: 平台注入的当前角色名 `$CNB_NPC_NAME`（按轮传递即自动跟随改名）。
ROLE_VARIABLE_FORM = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


class TestEveryRoleLiteralIsRegistered:
    """A：`.cnb.yml` 里每个 `role:` 取值都必须在 `.cnb/settings.yml` 名单范围内。

    根因（实测 cnb-ffc-1k3f5v4rm）：PR #273 改名后，载体仍写 `role: DSCoder`，
    平台直接以 `Role "DSCoder" not found` 拒绝 —— 而改名那一次没有任何判据会响。
    判据方向：名单的事实源只有 `npc.roles` 一处，`role:` 是它的**消费方**。

    两种取值的「在册」判法：
      * **字面量**（`role: DSCoder-Red`）—— 必须与名单逐字命中；
      * **平台变量**（`role: $handoffRole`）—— 变量名本身不是角色名，
        故本判据只钉「它确实是变量形态、不是某个猜的名字」，
        真正的在册由「变量取值有真实来源」保证（角色连续性守卫判：
        根本自平台注入的 `$CNB_NPC_NAME`，平台只注入在册角色的名字）。
    反向：写回退役名 `DSCoder` → 红；写成一个**既不在册又不像变量**的名字 → 红。
    """

    def test_role_values_are_registered_or_platform_variables(self, cnb_doc, settings_doc):
        names = _role_names(settings_doc)
        assert names, ".cnb/settings.yml 未声明任何 npc.roles"
        literals, variables = [], []
        for node in _walk(cnb_doc):
            value = node.get("role")
            if not isinstance(value, str) or not value.strip():
                continue
            (variables if ROLE_VARIABLE_FORM.match(value.strip()) else literals).append(
                value.strip()
            )
        assert literals or variables, (
            "`.cnb.yml` 里找不到任何 `role:` 取值 —— 本守卫空转"
            "（接力载体没有 `role` 时 API 触发拿不到人设）"
        )
        stale = sorted({r for r in literals if r not in names})
        assert not stale, (
            "`.cnb.yml` 引用了不在册的 NPC 角色名：" + " / ".join(stale) +
            "\n在册角色（事实源 .cnb/settings.yml 的 npc.roles）：" + " / ".join(names) +
            "\n实测（构建 cnb-ffc-1k3f5v4rm）：平台以 "
            '`Role "..." not found in .cnb/settings.yml` 直接拒绝该流水线，'
            "接力轮零产出。"
        )
        assert variables, (
            "`.cnb.yml` 的 `role:` 全部是字面量 —— 角色身份没有随轮传递，"
            "角色一改名就从第二轮起与名单分叉（PR #276 的根修方向是"
            "`role: $handoffRole`，根本自平台注入的 `$CNB_NPC_NAME`）。"
        )


class TestRelayJudgmentUsesTheFailedStageName:
    """B：判据必须读 `$CNB_BUILD_FAILED_STAGE_NAME`（确定性事实）。

    为什么不能只认报错原文：硬中止时 `CNB_BUILD_FAILED_MSG` 是**失败 stage 最后
    一行输出**（实测 cnb-m16-1k3f5s0ri 的 `MSG=[start]`），不是平台文案。
    按文案片段匹配等于让「是否接力」取决于脚本最后打印了什么。
    """

    def test_every_relay_if_reads_failed_stage_name(self, cnb_doc):
        seen = 0
        problems = []
        for where, stage in _relay_stages(cnb_doc):
            seen += 1
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            if FAILED_STAGE_VAR not in blob:
                problems.append(
                    f"{where}: 接力 `if` 未读 ${FAILED_STAGE_VAR} —— "
                    "判据只认报错原文时，硬中止（stage 被 SIGKILL）的形态会静默落空"
                )
        assert seen, "未在 .cnb.yml 找到任何接力 Stage —— 本守卫空转"
        assert not problems, "\n  ".join(problems)


class TestGoStageMarkerIsBidirectionallyLocked:
    """C：npc:go stage 的名字带 `npc-go` 标记，且判据匹配同一个标记。

    只锁一端等于不锁：stage 改名而判据不改（判据永远假），
    或判据改而 stage 名不改（判据永远假）—— 两种都红。
    """

    def test_go_stages_carry_the_marker(self, cnb_doc):
        stages = list(_npc_go_stages(cnb_doc))
        assert stages, "`.cnb.yml` 找不到任何 npc:go stage —— 本守卫空转"
        missing = [
            f"{where}: stage 名 {stage.get('name')!r} 不含标记 {GO_STAGE_MARKER!r}"
            for where, stage in stages
            if GO_STAGE_MARKER not in str(stage.get("name") or "")
        ]
        assert not missing, (
            "\n  ".join(missing) +
            f"\n接力判据按 `$CNB_BUILD_FAILED_STAGE_NAME` 匹配标记 {GO_STAGE_MARKER!r}；"
            "stage 名不带该标记时判据永远为假。"
        )

    def test_relay_if_matches_the_marker(self, cnb_doc):
        seen = 0
        problems = []
        for where, stage in _relay_stages(cnb_doc):
            seen += 1
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            if GO_STAGE_MARKER not in blob:
                problems.append(f"{where}: 接力 `if` 未匹配标记 {GO_STAGE_MARKER!r}")
        assert seen, "未在 .cnb.yml 找到任何接力 Stage —— 本守卫空转"
        assert not problems, "\n  ".join(problems)


class TestCarrierRoleHasARealSource:
    """D：接力载体的 `role:` 取值必须有真实来源（不得成为无人守的死引用）。

    载体的 `role` 是**唯一的第二处角色引用**（评论入口的角色名由评论给出，
    不由配置给出），故它的取值只有两种合法形态，两种都必须钉住：

    * **字面量** —— 必须等于 `npc.defaultRole`（声明的默认角色这一处事实源），
      改名时要么两处一起改（绿），要么漏一处（红）；
    * **平台变量**（`role: $handoffRole`，随轮传递）—— 变量必须真由上一跳的
      收尾接力经 `cnb:trigger.options.env` 供上，且取值的根节点是平台注入的
      当前角色名 `$CNB_NPC_NAME`。这条**不由本守卫判**：跨轮传递链的完整性
      由 `tests/unit/ci/test_npc_handoff_role_continuity.py`
      （`test_role_variable_resolves_from_a_real_source` 等）常驻钉住，
      本守卫只判「形态合法」这一半，并把它明确交出去。
      两个判据咬合，改任一侧漏另一侧即红。

    为什么不是「钉死等于 defaultRole」：那会把**单点字面量**重新钉成唯一合法形态，
    角色再改一次名即复断（PR #276 的根修方向是随轮传递）。平台对无值变量
    替换为空串，空 role 同样静默回落平台默认 prompt，
    故随轮传递的兜底由**供值侧**承担（三条评论侧事件都供 `$CNB_NPC_NAME`）。
    """

    def test_carrier_role_is_a_registered_literal_or_a_platform_variable(
        self, cnb_doc, settings_doc
    ):
        default_role = (settings_doc.get("npc") or {}).get("defaultRole")
        assert default_role, ".cnb/settings.yml 未声明 npc.defaultRole"
        fallback = cnb_doc.get("$") or {}
        body = fallback.get(HANDOFF_EVENT) or []
        options = [
            stage.get("options") or {}
            for job in (body if isinstance(body, list) else []) if isinstance(job, dict)
            for stage in (job.get("stages") or []) if isinstance(stage, dict)
            if stage.get("type") == "npc:go"
        ]
        assert options, f"{HANDOFF_EVENT}: 找不到 npc:go 的 options"
        problems = []
        for opt in options:
            role = opt.get("role")
            if not isinstance(role, str) or not role.strip():
                problems.append(
                    f"{HANDOFF_EVENT}: 载体缺 `role` —— API 触发下 `role` 决定平台"
                    "按哪份人设拼 system prompt，缺它等于人设与修复教义全线失效"
                )
                continue
            role = role.strip()
            if ROLE_VARIABLE_FORM.match(role):
                continue  # 随轮传递形态：来源链由角色连续性守卫判（见 docstring）
            if role != default_role:
                problems.append(
                    f"{HANDOFF_EVENT}: 载体 `role: {role!r}` 既不是平台变量形态，"
                    f"也不等于 `npc.defaultRole: {default_role!r}` —— "
                    "改名时两处各自演化不会有任何红（实测 cnb-ffc-1k3f5v4rm："
                    '平台以 `Role "…" not found` 直接拒绝接力轮）'
                )
        assert not problems, "\n  ".join(problems)
