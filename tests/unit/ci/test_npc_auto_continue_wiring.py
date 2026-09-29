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
import os
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

#: 量尺脚本的落点 —— 收尾判据第三问的**唯一事实源**（Issue #327）。
BUDGET_SCRIPT_REL = "scripts/ci/npc_runtime_budget.py"

#: 判据第三问：`eval "$($NPX_PREDICATE)"` 里的调用形态标记（怎么调用由探测段登记）。
PREDICATE_CALL_MARKER = "NPX_PREDICATE"

#: 解释器探测段锚点（`$NPX_PREDICATE` 的赋值处）。
INTERPRETER_ANCHOR = "npc-script-interpreter"


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


class TestRelayJudgmentAlsoAsksAboutTheQuotaWall:
    """E：判据必须再问一句「这次中止可归因到时长配额吗」（Issue #327）。

    ## 根因（真实构建实测，不是推测）

    构建 cnb-urv-1k3lagkdv：NPC 会话在第 36 轮 / 7.4 分钟被平台 AI 网关中止
    （`Pipeline has been stopped, Agent aborted`，该轮 `in=0 out=0 duration=0.0s`），
    四道上限（流水线整体 / Job / 无输出 / `maxTurns`）**一道都没触达** ——
    而接力真的触发了。旧判据（B/C 两条）回答的是「是不是被中止在 Agent 那一格」，
    对「这次中止是不是撞墙」一无所知，于是每约 7 分钟拉起一轮新 `npc:go`，
    以同样方式再被掐、再接力，无限循环，每一轮都真实计入 LLM 成本。

    ## 判据

    每条接力的 `if` 里必须有一条**消费量尺事实源**的条件，且该消费必须
    可追溯到唯一的调用形态登记处（解释器探测段的 `$NPX_PREDICATE`）：

    * 条件里出现 `$NPX_PREDICATE`（怎么调用只有一处登记）；
    * 探测段确实给它赋了值，且取值指向 `npc_runtime_budget.py`；
    * 量尺脚本真的把判据片段算出来（`--predicate` 在脚本里可达）。

    反向控制：把任意一条接力的第三问删掉 → 红；把 `$NPX_PREDICATE` 的赋值
    改指到别的脚本 → 红。
    """

    def test_every_relay_if_consumes_the_quota_wall_predicate(self, cnb_doc):
        seen, problems = 0, []
        for where, stage in _relay_stages(cnb_doc):
            seen += 1
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            if PREDICATE_CALL_MARKER not in blob:
                problems.append(
                    f"{where}: 接力 `if` 未消费 ${PREDICATE_CALL_MARKER} —— "
                    "判据只答得了「有没有被中止在 Agent 那格」，"
                    "答不了「这次中止是不是撞在配额上」（Issue #327："
                    "平台网关的 7.4 分钟外部中止被放大成自动续跑链条）"
                )
        assert seen, "未在 .cnb.yml 找到任何接力 Stage —— 本守卫空转"
        assert not problems, "\n  ".join(problems)

    def test_predicate_call_form_is_registered_once(self):
        """`$NPX_PREDICATE` 的赋值必须在解释器探测段 —— 调用形态只有一处登记。"""
        text = io.open(CNB, encoding="utf-8").read()
        anchor_at = text.find(INTERPRETER_ANCHOR)
        assert anchor_at >= 0, f"`.cnb.yml` 缺探测段锚点 {INTERPRETER_ANCHOR}"
        body = text[anchor_at:]
        cut = body.find("\n$:", 1)
        if cut > 0:
            body = body[:cut]
        assignments = [
            line.strip() for line in body.splitlines()
            if PREDICATE_CALL_MARKER in line
            and not line.strip().startswith("#")
            and "=" in line
        ]
        assert assignments, (
            f"探测段没有登记 {PREDICATE_CALL_MARKER} 的调用形态 —— "
            "判据第三问无从复算"
        )
        joined = " ".join(assignments)
        assert BUDGET_SCRIPT_REL in joined, (
            f"{PREDICATE_CALL_MARKER} 没有指向 {BUDGET_SCRIPT_REL}：\n  "
            + "\n  ".join(assignments) +
            "\n判据的阈值与解析口径只在量尺脚本里有一份定义，"
            "指到别处就等于新造第二份。"
        )

    def test_budget_script_actually_computes_the_predicate(self):
        """量尺脚本必须真能算出判据片段：`--predicate` 有执行体、读数可分辨。"""
        script = PROJECT_ROOT / BUDGET_SCRIPT_REL
        assert script.exists(), f"{BUDGET_SCRIPT_REL} 丢失 —— 判据第三问的事实源没了"
        source = io.open(script, encoding="utf-8").read()
        assert "--predicate" in source, (
            f"{BUDGET_SCRIPT_REL} 没有 `--predicate` 入口 —— "
            "`.cnb.yml` 消费的是一个不存在的读数"
        )
        # 真跑两支：远未触达（外部中止）与触达阈值，判据必须可分辨。
        import subprocess, sys, time
        def run(start_offset_s: int) -> str:
            start = time.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - start_offset_s)
            )
            env = dict(
                os.environ,
                CNB_PIPELINE_MAX_RUN_TIME="7200000",
                CNB_BUILD_START_TIME=start,
            )
            proc = subprocess.run(
                [sys.executable, str(script), "--predicate"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
            )
            assert proc.returncode == 0, proc.stderr
            return proc.stdout.strip()

        early, late = run(7 * 60), run(int(7200 * 0.9))
        assert early == "false", (
            "已用 7 分钟（2h 配额的 6%）时判据仍为真 —— 平台网关的外部中止"
            "依旧会被当成撞墙，自动续跑链条没有断（Issue #327）"
        )
        assert late == "true", "已用 90% 配额时判据为假 —— 真撞墙的中止反而不会续跑"
        assert early != late, "两种相反的输入给出同一读数 —— 判据是恒真壳"

    def test_missing_readings_do_not_relay(self):
        """量不出（两个平台变量缺失）时必须判 false：不把「量不出来」转写成接力。"""
        import subprocess, sys
        script = PROJECT_ROOT / BUDGET_SCRIPT_REL
        env = {k: v for k, v in os.environ.items()
               if k not in ("CNB_PIPELINE_MAX_RUN_TIME", "CNB_BUILD_START_TIME")}
        proc = subprocess.run(
            [sys.executable, str(script), "--predicate"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "false", (
            "读不到预算变量时判据为真 —— 「量不出来」被当成了撞墙证据，"
            "而那正是烧配额的接力（教义第 2 条：不得用兜底默认把不确定性抹平）"
        )


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


#: `issue.comment@npc` 的宿主事件名 —— 接力链上所有 Job 的运行配置都随它走。
#: 平台「自定义 NPC」篇：NPC 事件触发时，系统把系统默认配置与 **NPC 所属仓库**的
#: `.cnb.yml` 合并；`@CodeBuddy` 是平台内置系统 NPC，其「NPC 所属仓库」是平台的，
#: 故本仓在 `$` 下写的这套 Job 对系统 NPC 完全不生效（实测读者见报告
#: `docs/05-reports/npc系统事件通道_2026-09-28.md`）。
HOST_NPC_EVENT = "issue.comment@npc"

#: 本仓 NPC 流水线的容器镜像：脚本解释器探测的降级链（`&npc-script-interpreter`）
#: 只按这个镜像设计 —— 它**只有 node，没有 python**。
REQUIRED_DOCKER_IMAGE = "cnbcool/default-npc:latest"


def _npc_jobs(cnb_doc):
    """产出 ($ 段每个 NPC 事件名, 该事件下的 Job)。"""
    fallback = cnb_doc.get("$") or {}
    for event, body in fallback.items():
        if not isinstance(event, str) or not event.endswith("@npc"):
            continue
        for job in (body if isinstance(body, list) else []):
            if isinstance(job, dict):
                yield event, job


class TestNpcJobsSelfContainTheirContainerRuntime:
    """本仓 NPC Job 必须自带容器 runtime —— 缺项会被平台系统默认配置按 key 覆盖。

    ## 根因（实测读数，不是推测）

    2026-09-28 的一次真实调用：用户在 Issue #306 评论里 @ 了本仓在册角色
    `@kingsa2026/neurova(DSCoder-max)`，平台上同时出现两台构建，且**都停在中转态**：

        cnb-1ii-1k3jc0fgm-001  pipeline 001                      pending
        cnb-tb2-1k3jc0fgm-001  cnb/issue.comment@npc/pipeline-1  pending

    同一条评论的前一次（@CodeBuddy）留下的读数是 `cnb/issue.comment@npc/default` ——
    「default」那一格是**平台默认配置**的流水线，本仓 `.cnb.yml` 里那条
    `$` → `issue.comment@npc` 定义的 stage 名（构建环境自证 / 角色准入 /
    npc-go 在册角色执行任务）一个都不在里面。

    两件事同源：**本仓写的 Job 没有自带 `docker.image`**。平台按 key 覆盖合并
    系统默认配置与本仓配置，本仓缺的那一项由平台补上，Job 的实际运行环境
    不再由本仓 `.cnb.yml` 决定 —— 而这条差异在平台侧与日志里都不响。

    ## 判据

    每个 NPC 事件下的每个 Job 都必须自带 `docker.image`，且取值是平台 NPC 镜像
    （本仓的解释器探测只按该镜像设计）。可证伪路径：删掉 `docker.image` → 立刻红。
    """

    def test_every_npc_job_declares_its_own_image(self, cnb_doc):
        fallback = cnb_doc.get("$") or {}
        missing = [
            f"$.{event}[{i}]"
            for event, body in fallback.items()
            if isinstance(event, str) and event.endswith("@npc")
            for i, job in enumerate(body if isinstance(body, list) else [])
            if isinstance(job, dict)
            and not str(((job.get("docker") or {}).get("image") or "")).strip()
        ]
        assert list(_npc_jobs(cnb_doc)), "`$` 段找不到任何 NPC 事件 Job —— 本守卫空转"
        assert not missing, (
            "以下 NPC Job 未自带 docker.image：\n  " + "\n  ".join(missing) +
            "\n平台合并系统默认配置与本仓配置时按 key 覆盖：本仓缺 docker.image 时，"
            "平台那一份会顶上，Job 的实际运行环境不再由本仓 `.cnb.yml` 决定，"
            "而平台侧与日志里都看不出这件事。"
        )

    def test_npc_job_image_is_the_platform_npc_runtime(self, cnb_doc):
        offenders = [
            f"$.{event}[{i}]: {((job.get('docker') or {}).get('image'))!r}"
            for event, body in ((k, v) for k, v in (cnb_doc.get("$") or {}).items()
                                if isinstance(k, str) and k.endswith("@npc"))
            for i, job in enumerate(body if isinstance(body, list) else [])
            if isinstance(job, dict)
            and str(((job.get("docker") or {}).get("image") or "")).strip()
            != REQUIRED_DOCKER_IMAGE
        ]
        assert not offenders, (
            "NPC Job 的容器镜像不是平台 NPC 运行时：\n  " + "\n  ".join(offenders) +
            f"\n本仓的脚本解释器探测、门禁脚本与 npc:go 都按 {REQUIRED_DOCKER_IMAGE!r} 设计"
            "（`&npc-script-interpreter` 的降级链只认该镜像的 node 分支）。"
        )

    def test_image_check_is_not_tautological(self, cnb_doc):
        """反向控制：把 `docker.image` 改成别的镜像，本判定必须抓得到。"""
        import copy
        injected = copy.deepcopy(cnb_doc)
        injected["$"][HOST_NPC_EVENT][0]["docker"] = {"image": "python:3.12"}
        offenders = [
            ((job.get("docker") or {}).get("image"))
            for _event, job in _npc_jobs(injected)
            if str(((job.get("docker") or {}).get("image") or "")).strip()
            != REQUIRED_DOCKER_IMAGE
        ]
        assert offenders, "把镜像改成别的值后判定没有变化 —— 本判据接不上真实文档"


class TestNpcEventChannelIsTheRepositoriesOwn:
    """@ 本仓角色产出的构建必须落在本仓声明的事件定义上（静态面自洽）。

    ## 实测形态（2026-09-28，Issue #306）

    用户在 Issue #306 评论里 @ 了本仓在册角色 `DSCoder-max`，平台上同时出现两台
    构建，`statuses.npc.data` 的读数是：

        cnb-1ii-1k3jc0fgm-001  pipeline 001                      pending
        cnb-tb2-1k3jc0fgm-001  cnb/issue.comment@npc/pipeline-1  pending

    两条流水线**同时** pending、没有一条进入执行 —— 用户看到的就是「NPC 空转」。

    这一格 shape 属平台测（`pipeline-1` 是本仓 `$` → `issue.comment@npc`
    那**数组的第 1 条**，`pipeline 001` 是被触发的构建），不能只由静态文本判定；
    但配置能否被执行，有静态可判的一半：

    * 本仓必须同时声明 issue / PR 两个 NPC 评论事件 —— 漏一个即走平台默认行为；
    * 每个 Job 必须自带容器 runtime（见上一个类）。
    """

    def test_host_event_is_declared_with_both_comment_events(self, cnb_doc):
        fallback = cnb_doc.get("$") or {}
        missing = [
            key for key in ("issue.comment@npc", "pull_request.comment@npc")
            if key not in fallback
        ]
        assert not missing, (
            f"`$` 段缺 NPC 评论事件 {missing} —— 平台按事件独立合并，"
            "漏配的事件走平台默认行为（本仓 Job 完全不参与）。"
        )
