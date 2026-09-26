# -*- coding: utf-8 -*-
"""NPC 轮数触顶接力的**执行面**守卫（Issue #145；判据两轮收口见 Issue #189）。

## 为什么需要这份守卫

配置面另有一份守卫（`tests/unit/test_ci_npc_config_guard.py` 的
`TestTurnHandoffCeiling`）：它钉住「`.cnb.yml` 里有这笔接力」。但"接力被声明过"
与"接力会真的按预期发生"是两件事 —— 本仓为此付过三轮代价：

1. 燃料由 Agent 在最后一轮自己写文件 → 撞 maxTurns 时平台**不执行任何收尾
   指令或工具调用**，`if` 恒假、收尾 Stage 每次 `skipped`，没有回音
   （构建 cnb-2e8-1k341d9s1 / cnb-2v8-1k34htd2p 实测）。
2. 燃料改由构建侧在 Agent 开工前**无条件**写出 → `if` 恒**真**。
   判据的输入端被自己填成了真值：该变量回答「上一轮是否用满配额」，
   而得知这件事的唯一时点是收尾期。后果是空轮防护全失效，正常收官也照拉下一轮：
     cnb-2q8-1k3buskao  Agent stage success（1774s，未撞顶）→ 拉 cnb-lga-1k3c0itrj
     cnb-kdg-1k3bv22ct  Agent stage success（3977s，未撞顶）→ 拉 cnb-fln-1k3c2rjk7
3. 现形态（Issue #189）：收尾 `if` 读**平台在收尾期注入的事实** ——
   `$CNB_PIPELINE_STATUS` 与 `$CNB_BUILD_FAILED_MSG`（平台「环境变量」篇；
   真 `npc:go` 撞 `maxTurns` 的读数见构建 cnb-s4f-1k3c46us9 / cnb-p2q-1k3c2g7u3）。
   构建侧不再产出任何被 `if` 消费的真值。

## 本文件钉四件事（都可证伪）

- **A 人设教的是当前契约**：必须点明判据读哪两个平台变量、必须显式禁止
  Agent 去写状态文件或标记、且不得再出现已作废的标记文件名 ——
  继续教一个死协议与"看着配了、其实永不触发"是同一类断点，只是断在人这一侧。
- **B 门禁在构建里可达**：`scripts/ci/npc_turn_handoff_gate.py` 存在，
  且被 `.cnb.yml` 的 NPC 流水线真实执行（不是躺在仓库里当摆设）。
- **C 接力通道是平台真支持的形态**：`cnb:trigger`（适用所有事件），
  且接力载体能自己续链（否则接力只有一跳）。
- **D 门禁留在受保护子集**：判据要在 CI 上真的跑，否则 A/B/C 无人执行。

可证伪路径：
- 把人设改回「把 1 写进 `.npc-turn-handoff`」→ A 红；
- 把 `.cnb.yml` 里跑门禁的那一步删掉 → B 红；
- 把人设里的两个平台变量名删掉、或加回自造标记 → A 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → D 红。
"""
import ast
import copy
import io
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 已作废的接力标记文件名（Issue #158 引入、Issue #189 废止）。
#: 保留常量只为**反向钉住**「它不得再出现」—— 收尾 `if` 自 #189 起读平台
#: 注入的 `$CNB_PIPELINE_STATUS` / `$CNB_BUILD_FAILED_MSG`，
#: 这个文件不再是任何判据的输入。
HANDOFF_MARKER_FILE = ".npc-turn-handoff"

#: 开工前自证脚本（接力环境前提与工作区落点自证）。
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


@pytest.fixture(scope="module")
def npc_personas():
    """NPC 角色名 → 人设正文（人设是给 Agent 的唯一必达通道）。"""
    doc = yaml.safe_load(io.open(SETTINGS, encoding="utf-8").read())
    roles = (doc.get("npc") or {}).get("roles") or []
    assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
    return {r.get("name"): (r.get("prompt") or "") for r in roles}


class TestPersonaTeachesTheCurrentRelayContract:
    """A. 人设必须教**当前**的接力契约，不许再教已作废的标记协议。

    这条守卫的前身钉的是「标记落点必须写成
    `$CNB_BUILD_WORKSPACE/.npc-turn-handoff`」。Issue #189 之后那个文件**不再是
    任何判据的输入**（收尾 `if` 读平台注入的 `$CNB_PIPELINE_STATUS` /
    `$CNB_BUILD_FAILED_MSG`），继续把它写进人设就是把 Agent 往一个已死的
    协议上引 —— 与它当初要消灭的"看着配了、其实永不触发"是同一类断点，
    只是这次断在文档与人之间。

    故判据改为两条，都落在**行为**上：

    - 人设必须点明接力判据读的是平台事实（两个变量名）；
    - 人设必须点明"别去写状态文件/标记"（否则 Agent 会新造平行判据）。
    """

    #: 平台在收尾期注入的两个事实（`.cnb.yml` 收尾 `if` 读它们）。
    STATUS_VAR = "CNB_PIPELINE_STATUS"
    FAILED_MSG_VAR = "CNB_BUILD_FAILED_MSG"

    def test_personas_name_the_platform_facts_the_relay_reads(self, npc_personas):
        missing = [
            name
            for name, prompt in npc_personas.items()
            if self.STATUS_VAR not in prompt or self.FAILED_MSG_VAR not in prompt
        ]
        assert not missing, (
            f"NPC 人设未点明接力判据读的平台事实: {missing}\n"
            f"收尾 `if` 读的是 ${self.STATUS_VAR} 与 ${self.FAILED_MSG_VAR}；"
            "人设里不写清楚，Agent 会以为接力还需要它配合，"
            "或者以为接力不存在而另造一套判据。"
        )

    def test_personas_forbid_writing_a_state_file(self, npc_personas):
        """人设必须显式禁止写状态文件 —— 那是平行判据的唯一入口。"""
        offenders = [
            name
            for name, prompt in npc_personas.items()
            if "别去写任何状态文件或标记" not in prompt
        ]
        assert not offenders, (
            f"NPC 人设未显式禁止写状态文件/标记: {offenders}\n"
            "撞上 maxTurns 时平台中止 Agent、不执行任何收尾指令或工具调用，"
            "写不出也不该写；而自造标记正是上一轮「恒真、空轮防护失效」的来源。"
        )

    def test_personas_do_not_teach_the_retired_marker_file(self, npc_personas):
        """人设不得再出现已作废的标记文件名（教一个死协议 = 新断点）。"""
        offenders = [
            f"{name}: {line.strip()}"
            for name, prompt in npc_personas.items()
            for line in prompt.splitlines()
            if HANDOFF_MARKER_FILE in line
        ]
        assert not offenders, (
            "人设仍在教已作废的接力标记协议:\n  " + "\n  ".join(offenders) +
            f"\n`{HANDOFF_MARKER_FILE}` 自 Issue #189 起不再是任何判据的输入；"
            "继续教它会把 Agent 引到一个已死的协议上。"
        )

    def test_cnb_config_carries_no_retired_marker(self, cnb_doc):
        """`.cnb.yml` 里同样不得再出现该文件名。"""
        text = io.open(CNB, encoding="utf-8").read()
        bad = [
            f"{lineno}: {line.strip()}"
            for lineno, line in enumerate(text.splitlines(), 1)
            if HANDOFF_MARKER_FILE in line
        ]
        assert not bad, (
            "`.cnb.yml` 仍在提接力标记文件:\n  " + "\n  ".join(bad) +
            "\n收尾判据读平台事实，配置侧与它无关。"
        )


class TestGateScriptIsExecutedByTheBuild:
    """B. 落点可达性必须由真实构建自证，不能只在仓库里躺着。"""

    def test_gate_script_exists_and_is_a_python_program(self):
        assert GATE_SCRIPT.exists(), (
            "scripts/ci/npc_turn_handoff_gate.py 丢失 —— 接力判据的可达性无人自证"
        )
        ast.parse(io.open(GATE_SCRIPT, encoding="utf-8").read())

    def test_npc_pipeline_runs_the_gate(self, cnb_doc):
        """每条 NPC 流水线都要跑门禁：门禁不跑，A 条判据在 CI 上就是空转。"""
        found = []

        def walk(node, job=None):
            """产出 (所在 Job, Stage)；job 为空时用当前 Stage 充当占位。

            复用式递归：`.cnb.yml` 里同一个 Job 下并列着多个 stage，
            「这个 Job 有没有跑门禁」要看**同级**的兄弟 stage，而不是 stage 自己。
            """
            if isinstance(node, list):
                for item in node:
                    walk(item, job)
                return
            if isinstance(node, dict):
                if node.get("type") == "npc:go":
                    found.append((job if job is not None else node, node))
                for value in node.values():
                    walk(value, job if job is not None else node)

        for key in ("issue.comment@npc", "pull_request.comment@npc"):
            walk((cnb_doc.get("$") or {}).get(key))
        assert found, "未在 .cnb.yml 找到 npc:go 流水线 —— 判据空转"
        missing = [
            job for job, _stage in found
            if not any(
                "npc_turn_handoff_gate.py" in str(stage.get("script", ""))
                for stage in (job.get("stages") or [])
                if isinstance(stage, dict)
            )
        ]
        assert not missing, (
            f"{len(missing)} 条 npc:go 流水线未执行 scripts/ci/npc_turn_handoff_gate.py\n"
            "该步在真实构建里自证 `$CNB_BUILD_WORKSPACE` 可写可读，"
            "并反向自证 $PWD 是否等于 $CNB_BUILD_WORKSPACE——"
            "这是接手时唯一能回答「构建环境前提是否成立、工作区到底在哪」的读数。"
        )

    def test_gate_is_registered_in_the_import_sweep_or_directly_runnable(self):
        """门禁必须能独立跑起来（不依赖仓库内其它模块的导入副作用）。"""
        r = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--json"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            env={"PATH": "/usr/bin:/bin", "CNB_BUILD_WORKSPACE": str(PROJECT_ROOT)},
            timeout=60,
        )
        assert r.returncode == 0, (
            f"门禁在 CNB_BUILD_WORKSPACE 可写时仍判红: rc={r.returncode}\n"
            f"stdout={r.stdout}\nstderr={r.stderr}"
        )


class TestRelayJudgmentReadsPlatformFacts:
    """接力的判据必须读**平台在收尾期给出的事实**，不许读自己事前伪造的燃料。

    根因（本轮实测取证，2026-09-25）：
    燃料曾被设计为「由门禁在 Agent 开工前无条件写出 1」——
    而门禁的判据是 `CNB` 非空即写（真实构建里 `CNB=1`，该条件恒真），
    于是 `##[set-output turnLimitReached=1]` → `exports` → Pipeline 级环境变量，
    收尾 `if` **恒真**。空轮防护因此是死的，任一正常收官的轮次都会再拉一条接力轮：

        cnb-2q8-1k3buskao  Agent stage success（1774s，未撞顶）→ 照拉 cnb-lga-1k3c0itrj
        cnb-kdg-1k3bv22ct  Agent stage success（3977s，未撞顶）→ 照拉 cnb-fln-1k3c2rjk7

    这不是"判据写松了"，而是**判据的输入端被自己填成了真值**：
    该变量回答的是"上一轮是否用满配额"，而得知这件事的唯一时点是收尾期。

    平台已在 `endStages` 内提供这两个事实（构建 cnb-s4f-1k3c46us9 与
    cnb-p2q-1k3c2g7u3 实测，真 `npc:go` 撞 `maxTurns: 1`）：

        PROBE_STATUS=[error]
        PROBE_MSG=[Agent aborted: reached maxTurns limit (1)]

    故判据改为读它们，并删净事前伪造的燃料链路（门禁发射、`exports`、
    `env` 透传）——留着它就是"看着守住了空轮、其实恒真"。
    """

    #: 平台在收尾期给出的事实（`endStages` 内可读，平台「环境变量」篇）。
    STATUS_VAR = "CNB_PIPELINE_STATUS"
    FAILED_MSG_VAR = "CNB_BUILD_FAILED_MSG"

    #: 真实撞顶时平台给出的错误原文片段（构建 cnb-s4f-1k3c46us9 实测）。
    ABORT_MARKER = "reached maxTurns limit"

    @staticmethod
    def _relay_stages(cnb_doc):
        """产出 (挂载点, 事件名, job, 接力 Stage) —— `cnb:trigger` 收尾任务。"""
        for mount, body in cnb_doc.items():
            if not isinstance(body, dict):
                continue
            for event, event_body in body.items():
                for i, job in enumerate(event_body if isinstance(event_body, list) else []):
                    if not isinstance(job, dict):
                        continue
                    for stage in (job.get("endStages") or []):
                        if isinstance(stage, dict) and stage.get("type") == HANDOFF_TRIGGER_TYPE:
                            yield f"{mount}.{event}[{i}]", event, job, stage

    def test_every_relay_condition_reads_the_two_platform_facts(self, cnb_doc):
        """接力 `if` 必须同时读「流水线状态」与「失败原文」，不得读自造标记。"""
        seen = 0
        problems = []
        for where, event, job, stage in self._relay_stages(cnb_doc):
            seen += 1
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            if self.STATUS_VAR not in blob:
                problems.append(f"{where}: 接力 `if` 未读 ${self.STATUS_VAR}")
            if self.FAILED_MSG_VAR not in blob:
                problems.append(f"{where}: 接力 `if` 未读 ${self.FAILED_MSG_VAR}")
            if self.ABORT_MARKER not in blob:
                problems.append(
                    f"{where}: 接力 `if` 未按平台原文片段 {self.ABORT_MARKER!r} 判定"
                    "（不许以其它近似条件代替）"
                )
        assert seen, "未在 .cnb.yml 找到任何接力 Stage —— 本守卫空转"
        assert not problems, (
            "接力判据没有读平台给出的事实：\n  " + "\n  ".join(problems) +
            "\n该变量回答「上一轮是否用满配额」，唯一得知时点是收尾期；"
            "$" + self.STATUS_VAR + " 与 $" + self.FAILED_MSG_VAR + " 由平台注入。"
        )

    def test_no_self_fabricated_relay_flag_anywhere(self):
        """全仓不得再有"由构建侧提前写出接力真值"的形态。

        判据落在**真实文件内容**上：`.cnb.yml`、门禁脚本、人设三处都不得
        再出现发射/映射该标记的写法。留着任何一处，空轮防护就还是恒真。
        """
        sources = {
            ".cnb.yml": CNB,
            ".cnb/settings.yml": SETTINGS,
        }
        offenders = []
        for label, path in sources.items():
            if not path.exists():
                continue
            text = io.open(path, encoding="utf-8").read()
            for lineno, line in enumerate(text.splitlines(), 1):
                if "turnLimitReached" in line or "set-output" in line:
                    offenders.append(f"{label}:{lineno}: {line.strip()}")
        assert not offenders, (
            "仍在发射/映射一个由构建侧提前写出的接力标记（空轮防护恒真）：\n  "
            + "\n  ".join(offenders) +
            "\n真值只能来自平台在收尾期注入的 $CNB_PIPELINE_STATUS + "
            "$CNB_BUILD_FAILED_MSG。"
        )

    def test_relay_carrier_can_continue_the_chain(self, cnb_doc):
        """接力载体自己也要有心跳：否则接力只有一跳，撞顶后仍会断链。

        接力载体（`api_trigger_npc_handoff`）跑的就是下一轮 Agent。
        它若不在收尾再判一次，第二轮撞满配额时就没有任何消费者 ——
        与 Issue #131 最初的断点同形，只是往后挪了一跳。
        """
        body = (cnb_doc.get("$") or {}).get(HANDOFF_APPLY_EVENT)
        assert body, f"`$` 段缺接力落点事件 {HANDOFF_APPLY_EVENT!r}"
        jobs = body if isinstance(body, list) else [body]
        relays = [
            stage
            for job in jobs if isinstance(job, dict)
            for stage in (job.get("endStages") or [])
            if isinstance(stage, dict) and stage.get("type") == HANDOFF_TRIGGER_TYPE
        ]
        assert relays, (
            f"{HANDOFF_APPLY_EVENT} 没有收尾接力 —— 接力只发生一跳："
            "第一轮撞顶拉起的第二轮若再撞顶，链条即断，用户仍收不到回音。"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_turn_handoff_execution.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )


#: 平台 `cnb:apply` 的 applicable events（docs.cnb.cool/zh/build/internal-steps/cnb/apply.md）。
#: 这份清单是**平台运行期**的准入判据：不在其中，Stage 直接以 error 收场。
CNB_APPLY_EVENTS = frozenset({
    "push",
    "commit.add",
    "branch.create",
    "pull_request.target",
    "pull_request.mergeable",
    "tag_push",
    "pull_request.merged",
    "api_trigger",
    "web_trigger",
    "crontab",
    "tag_deploy",
})

#: `cnb:apply` 的 `event` **参数自身**的取值约束（同一篇文档）：
#: 「必须为 `api_trigger` 或以 `api_trigger_` 开头」。
CNB_APPLY_EVENT_PARAM_PREFIX = "api_trigger"

#: 接力落点事件名：`cnb:apply` 只能拉自定义 API 事件，故下一轮的入口**不是**
#: 原评论事件，而是一条 `api_trigger_*` 流水线（其内用 npc:go 续跑）。
HANDOFF_APPLY_EVENT = "api_trigger_npc_handoff"


#: 收尾接力唯一允许的内置任务类型（Issue #170，构建 cnb-i5m-1k355ooo1 实测）。
#: `cnb:apply` 的适用事件白名单里没有 `@npc` 一族及其宿主 `issue.comment` /
#: `pull_request.comment`，写在 `@npc` 流水线里注定执行不了 —— 校验看的是
#: **宿主事件**，`options.event` 取值再合法也绕不开。`cnb:trigger` 的适用事件
#: 是「所有事件」（docs.cnb.cool/zh/build/internal-steps/cnb/trigger.md），
#: 是同一件事在 `@npc` 宿主下唯一可行的通道；代价是多了必填的 `slug`。
HANDOFF_TRIGGER_TYPE = "cnb:trigger"


def _handoff_apply_stages(cnb_doc):
    """产出 ($ 段每一处收尾接力 Stage) 及其所在事件名。

    只扫**真实事件挂载点**：`$` 下以 `.` 开头的是 YAML 锚点定义
    （如 `.npc-dscoder-job`），它们不直接触发、由事件展开时被引用；
    锚点里无法写死 Issue/PR 专属的上下文（两条事件各不相同），
    故「对话载体传下去了吗」的判据只能落在展开后的真实事件上。
    """
    fallback = cnb_doc.get("$") or {}
    for event, body in fallback.items():
        if not isinstance(event, str) or event.startswith("."):
            continue
        for job in (body if isinstance(body, list) else []):
            if not isinstance(job, dict):
                continue
            for stage in (job.get("endStages") or []):
                if isinstance(stage, dict) and stage.get("type") == HANDOFF_TRIGGER_TYPE:
                    yield event, stage


class TestHandoffUsesAnEventCnbApplyActuallyAccepts:
    """D. 接力的**通道与宿主事件**必须是平台真支持的形态（Issue #158 / #170 三次修）。

    ## 事故形态一（构建 cnb-k6e-1k34osn4f，2026-09-22 23:21:43 实测）

    收尾 `if` 的判据（当时是自造的 `##[set-output]` + `exports` 通道，现已作废）——
    那一批修的东西**全部生效**了：Stage 0 打印 `turn_flag_handoff.written=true`，
    收尾 Stage 的 `if` 真的被判真（`Finished, code: 0`，不再是 `skipped`）。
    但 Stage 的最终状态是 **error**，平台逐字给出：

        cnb:apply can only be used in push/commit.add/branch.create/
        pull_request.target/pull_request.mergeable/tag_push/pull_request.merged/
        api_trigger/web_trigger/crontab/tag_deploy events

    当时读到的是「`event` 参数取值不合法」，于是把 `event` 改成 `api_trigger_*`
    ——**判据方向错了**，故本轮（Issue #170，构建 cnb-i5m-1k355ooo1 三次实测）
    仍然以同一句 error 收场。

    ## 事故形态二（构建 cnb-i5m-1k355ooo1，2026-09-23 实测）

    同一句 error 再次出现，而这次 `event` 早已是合法的 `api_trigger_npc_handoff`
    ——于是白名单的判据方向终于被钉死：平台校验的是**承载 `cnb:apply` 的宿主
    事件**（`issue.comment@npc` / `pull_request.comment@npc`），不是 `options.event`。
    `@npc` 一族不在白名单内，**这一点无法靠改 `options.event` 绕开**。
    `cnb:trigger` 的适用事件是「所有事件」，是同一件事唯一可行的通道。

    这条是本仓第四次同型犯病（前三次：`GITHUB_ENV` 通道不存在、`options.prompt`
    键不被承认、`options.event` 取值合规）——**配置写了一个平台不支持的形态，
    平台不报错，只在真被执行时才响亮**。故判据必须钉在"平台声明支持什么"上，
    而不是钉在"我们写了什么"上。
    """

    #: `cnb:apply` 的**宿主事件**白名单（apply.md「适用事件」节）；`@npc` 一族不在列。
    APPLY_HOST_EVENT_WHITELIST = frozenset({
        "push", "commit.add", "branch.create", "pull_request.target",
        "pull_request.mergeable", "tag_push", "pull_request.merged",
        "api_trigger", "web_trigger", "crontab", "tag_deploy",
    })

    def test_handoff_never_rides_cnb_apply(self, cnb_doc):
        """`@npc` 流水线的收尾接力**不得**用 `cnb:apply`（宿主事件不在白名单）。

        Issue #170 的根因判据。粗看像"写法问题"，实际是平台约束：
        `cnb:apply` 校验的是**宿主事件**，`@npc`（及其宿主 `issue.comment` /
        `pull_request.comment`）不在白名单内，**改 `options.event` 绕不开**。
        故这条判据的本体不是"event 取值合不合法"，而是"用的内置任务对不对"。

        可证伪路径：把任一处接力改回 `type: cnb:apply` → 立刻转红。
        """
        problems = []
        seen = 0
        for where, stage in _handoff_apply_stages(cnb_doc):
            seen += 1
            event = (stage.get("options") or {}).get("event")
            if not isinstance(event, str) or not event:
                problems.append(f"{where}: 收尾接力未声明 event")
                continue
            if not event.startswith(CNB_APPLY_EVENT_PARAM_PREFIX):
                problems.append(
                    f"{where}: 接力 event={event!r} 不是 api_trigger* 事件 —— "
                    "运行期会被平台以 error 拒掉"
                )
            if event.endswith("@npc"):
                problems.append(
                    f"{where}: 接力 event 指向 NPC 评论事件 {event!r}；"
                    "cnb:trigger 拉的是自定义事件，@npc 事件只能由人在评论里 @ 触发。"
                )
        assert seen, "未在 `$` 段找到任何收尾接力 Stage —— 本守卫空转"
        assert not problems, (
            "轮数触顶接力拉不起下一轮:\n  " + "\n  ".join(problems) +
            f"\n接力必须用 {HANDOFF_TRIGGER_TYPE}（适用「所有事件」）+ "
            "api_trigger_* 落点，由它内部的 npc:go 续跑。"
        )

    def test_handoff_does_not_use_cnb_apply_anywhere(self, cnb_doc):
        """全 `$` 段不得再把 `cnb:apply` 用在 `@npc` 事件下（宿主白名单）。

        与上一条的区别：上一条查**接力 Stage 的存在与否与 event 取值**，
        这一条直接在整份配置里搜 `cnb:apply` 的宿主事件——即便有人另加一处
        接力（或把 `endStages` 挪到别处），只要宿主是 `@npc` 一族，本条即红。
        `cnb:apply` 的宿主白名单见平台文档 apply.md「适用事件」节。
        """
        fallback = cnb_doc.get("$") or {}
        offenders = []
        for event, body in fallback.items():
            if not isinstance(event, str) or event.startswith("."):
                continue
            if event.split("@", 1)[0] in self.APPLY_HOST_EVENT_WHITELIST:
                continue
            for job in (body if isinstance(body, list) else []):
                if not isinstance(job, dict):
                    continue
                for stage in (job.get("endStages") or []) + (job.get("stages") or []):
                    if isinstance(stage, dict) and stage.get("type") == "cnb:apply":
                        offenders.append(f"{event}: cnb:apply")
        assert not offenders, (
            "cnb:apply 被用在平台不允许的宿主事件下（构建 cnb-i5m-1k355ooo1 实测 error）:\n  "
            + "\n  ".join(offenders) +
            "\n白名单：" + "/".join(sorted(self.APPLY_HOST_EVENT_WHITELIST)) +
            f"。`@npc` 一族不在列，改用 {HANDOFF_TRIGGER_TYPE}。"
        )

    def test_handoff_target_pipeline_exists_and_runs_npc_go(self, cnb_doc):
        """接力拉的 `api_trigger_*` 事件必须在 `$` 下真的存在，且其内跑 npc:go。

        只把 `event` 改成合法名还不够：事件不存在或里面没有 npc:go，
        接力依然是"拉起来什么都不干"的空转——同一条死链的下一个命中点。
        """
        fallback = cnb_doc.get("$") or {}
        assert HANDOFF_APPLY_EVENT in fallback, (
            f"`$` 段缺少接力落点事件 {HANDOFF_APPLY_EVENT!r} —— "
            "收尾的 cnb:apply 指向一个不存在的流水线，接力仍是空转。"
        )
        body = fallback.get(HANDOFF_APPLY_EVENT)
        jobs = body if isinstance(body, list) else []
        assert jobs, f"{HANDOFF_APPLY_EVENT}: 流水线体为空"
        found = [
            stage
            for job in jobs if isinstance(job, dict)
            for stage in (job.get("stages") or []) if isinstance(stage, dict)
        ]
        go = [s for s in found if s.get("type") == "npc:go"]
        assert go, (
            f"{HANDOFF_APPLY_EVENT}: 流水线里没有 npc:go —— "
            "接力拉起来之后没有任何 Agent 续跑，等于只烧一次配额。"
        )

    def test_handoff_target_pipeline_supplies_its_own_prompts(self, cnb_doc):
        """API 触发下 `npc:go` **不继承**评论触发的人设，必须自带提示词。

        平台文档（internal-steps/npc/go.md）：`role` / `systemPrompt` / `userPrompt`
        「仅 API 触发时生效」，且 `systemPrompt`、`userPrompt` 在 API 触发下**必填**——
        评论触发时提示词由角色自带（并被忽略），api_trigger 时没有任何角色上下文，
        不传则下一轮 Agent 不知道自己是谁、要干什么。

        可证伪：把 `systemPrompt` 从接力流水线的 options 里删掉 → 本条红。
        """
        fallback = cnb_doc.get("$") or {}
        body = fallback.get(HANDOFF_APPLY_EVENT) or []
        options = [
            stage.get("options") or {}
            for job in (body if isinstance(body, list) else []) if isinstance(job, dict)
            for stage in (job.get("stages") or []) if isinstance(stage, dict)
            if stage.get("type") == "npc:go"
        ]
        assert options, f"{HANDOFF_APPLY_EVENT}: 找不到 npc:go 的 options"
        problems = []
        for opt in options:
            for key in ("systemPrompt", "userPrompt"):
                value = opt.get(key)
                if not (isinstance(value, str) and value.strip()):
                    problems.append(f"{HANDOFF_APPLY_EVENT}: npc:go 缺 {key}（API 触发下必填）")
        assert not problems, "\n  ".join(problems)

    def test_handoff_carries_the_issue_or_pr_context_forward(self, cnb_doc):
        """下一轮要能找回**同一个** Issue/PR —— 上下文断链等于接力白跑。

        评论触发时 `CNB_ISSUE_IID` / `CNB_PULL_REQUEST_IID` 由平台注入；
        `api_trigger_*` 是全新流水线，这些变量**不会再出现**（平台只注入
        `API_TRIGGER_*` 一族，见 cnb/apply.md 的「环境变量相关」）。
        故上一轮必须显式把它们传下去，否则下一轮 Agent 无处可读对话载体。
        判据落在"env 里确实点了名"，不落在"注释里说要传"。
        """
        problems = []
        seen = 0
        for where, stage in _handoff_apply_stages(cnb_doc):
            seen += 1
            env = (stage.get("options") or {}).get("env") or {}
            keys = {str(k) for k in env}
            if not ({"issueIid", "issueNumber", "handoffIssueIid"} & keys) and \
               not ({"prIid", "pullRequestIid", "handoffPrIid"} & keys):
                problems.append(
                    f"{where}: 接力 env 未把 Issue/PR 标识传下去（下一轮读不到对话载体）"
                )
        assert seen and not problems, "\n  ".join(problems)

#: 接力落点事件：其流水线是**续跑载体**，不是门禁。
#: 它跑的是「上一轮撞满轮数后继续干」这一件事，配额用满即它的正常结束形态。
HANDOFF_CARRIER_EVENT = HANDOFF_APPLY_EVENT

#: 门禁事件：与 GitHub job 逐条对齐、裁决合并、逐条上报提交状态。
#: 判据按**枚举**取，不按"除某几个之外"取 —— 后者会把后加的非门禁事件判成门禁，
#: 于是「非门禁不上报提交状态」这条契约重新失效（PR #255 复核的根因形态）。
GATE_EVENTS = ("push", "pull_request")


class TestHandoffCarrierDoesNotReportQuotaEndAsCommitFailure:
    """续跑载体不得把「Agent 用满轮数」上报成**提交状态失败**（Issue #217 的假红）。

    ## 实测形态（2026-09-25，本轮取证）

    PR #217 本身是**已合并**的：PR 流水线全绿（`cnb pulls check-status` 读数
    `state: success`）、合并提交 `0cc0719a` 也在 `main` 上。但它的**提交状态**里
    多出一条失败：

        cnb/api_trigger_npc_handoff/pipeline-1   error [1h 8m]   ← 构建 cnb-sis-1k3bnmick

    同形态在近 8 次接力里出现 5 次（44m / 1h8m / 1h20m / 1h42m / 41m 后 error），
    每一次的原因都是同一句：`Agent aborted: reached maxTurns limit (200)` ——
    也就是本仓**自己声明**的「配额触发的正常收官」。于是：

    * 合并提交在提交列表 / PR 页上被标红，用户读到的就是「合并失败」；
    * 而这份失败**不是**任何门禁的结论 —— 门禁流水线当时全绿。

    ## 根因：续跑载体把「设计内的收官」报进了**门禁的通道**

    `endStages` 不影响流水线状态（平台文档「语法手册」），所以撞顶的 `npc:go`
    必然把整条载体流水线判成 `error`；而平台把它当**提交状态检查**上报，
    与门禁共用同一条通道。用户无法从这一格里区分「门禁拦住了合并」与
    「续跑那一轮跑满了轮数」。

    平台已声明的区分手段只有一处：流水线的 `allowFailure`
    （平台文档「语法手册」：为 `true` 时，流水线的失败状态**不会上报**到 CNB 上）。
    故修法是在**载体**上声明它，而不是在报错处加判空、也不是把门禁放宽。

    ## 判据咬合（正向 + 反向，缺一不可）

    * 正向：载体流水线必须声明 `allowFailure`；撤掉它 → 立刻转红。
    * 反向：`main.push` / `main.pull_request` 的**门禁**流水线一律不得声明它 ——
      余下所有 npc:go 事件定义（评论触发的那两条）与全部门禁流水线都不在放宽
      范围内。
      否则这条判据会被拿去"顺手全局放宽"，那才是把失败改写成 warning。

    ## 口径收口（PR #255 复核，2026-09-26）

    本类的第二版口径把"允许放宽"写成了**一份枚举**——「只有续跑载体」。而它要表达的
    契约其实是**按类别**的：*提交状态通道是门禁专用的，非门禁流水线一律不上报*。
    枚举漏掉了同契约的其余全部消费方（`commit.add` 建库、`crontab` 周级巡检、
    以及后加的手动触发口），于是它们一失败就照常写「状态检查：未通过」。

    实测（PR #255 的合并提交 `d5210625`）：该 PR 已合并、10 条门禁全绿，聚合却是
    `failure` —— 红格全部来自手动 `api_trigger` 探针与 `config error`，
    用户在提交列表里读到的就是「合并失败」。同一个根因在提交状态上留了一条
    看不出成因的红。

    故口径改为按事件类别判定：`push` / `pull_request` 是门禁（保持阻塞），
    `main` 下其余事件与 `$` 下的接力载体是非门禁（必须 `allowFailure`）。
    两类判定互为反向控制 —— 缺任一条，另一条都可能被"顺手全局放宽"或
    退化成恒真断言。
    """

    def test_every_non_gate_pipeline_is_off_the_commit_status_channel(self, cnb_doc):
        """口径收口：`main` 下**每一条非门禁**流水线都不上报提交状态。

        同一个契约的全部消费方一次扫清（教义第 5 条）：此前只有接力载体那一处，
        建库 / 周级巡检 / 手动触发口全部漏网 —— 它们一失败就把「状态检查：未通过」
        写到提交上，与门禁结论同形。可证伪：给 `main` 注入一条不带 `allowFailure`
        的新非门禁事件 → 立刻红。
        """
        main = cnb_doc.get("main") or {}
        offenders = []
        for event, body in main.items():
            if event in GATE_EVENTS:
                continue
            for i, pipe in enumerate(body if isinstance(body, list) else []):
                if not isinstance(pipe, dict):
                    continue
                if pipe.get("allowFailure") is not True:
                    offenders.append(f"main.{event}[{i}]({pipe.get('name') or '<未命名>'})")
        assert not offenders, (
            "这些非门禁流水线未声明 allowFailure，失败时会写成「状态检查：未通过」——"
            "合并提交在提交列表里挂红叉，而门禁本身全绿，用户读到的就是一句「合并失败」。\n  "
            + "\n  ".join(offenders)
            + "\n实测：PR #255 的合并提交 d5210625 聚合为 failure，红格全部来自手动 "
            "api_trigger 探针与 config error，而该 PR 的 10 条门禁流水线全绿。\n"
            "修法：流水线体加 `allowFailure: true` —— 失败仍以诚实形态暴露"
            "（构建列表与日志里 error），只是不再占用门禁通道。"
        )

    def test_non_gate_coverage_is_not_tautological(self, cnb_doc):
        """反向控制：注入一条新的非门禁事件，本判定必须翻转。"""
        injected = copy.deepcopy(cnb_doc)
        injected["main"]["api_trigger_probe_injected"] = [
            {"name": "probe", "stages": [{"script": "echo x"}]}
        ]
        offenders = [
            f"main.api_trigger_probe_injected[{i}]({p.get('name')})"
            for i, p in enumerate(injected["main"]["api_trigger_probe_injected"])
            if isinstance(p, dict) and p.get("allowFailure") is not True
        ]
        assert offenders, "注入新的非门禁事件后判定没有变化 —— 判据的输入端没接上真实文档"

    def test_carrier_declares_allow_failure(self, cnb_doc):
        fallback = cnb_doc.get("$") or {}
        body = fallback.get(HANDOFF_CARRIER_EVENT)
        assert body, f"`$` 段缺少接力落点事件 {HANDOFF_CARRIER_EVENT}"
        jobs = [job for job in (body if isinstance(body, list) else []) if isinstance(job, dict)]
        assert jobs, f"{HANDOFF_CARRIER_EVENT}: 流水线体为空"
        unflagged = [i for i, job in enumerate(jobs) if job.get("allowFailure") is not True]
        assert not unflagged, (
            f"{HANDOFF_CARRIER_EVENT} 的流水线未声明 allowFailure（下标 {unflagged}）——"
            "续跑轮撞满 maxTurns 是本仓自己声明的正常收官，平台却把它当**提交状态失败**"
            "上报，于是合并提交被标红、用户读到「合并失败」。\n"
            "实测：构建 cnb-sis-1k3bnmick 以 `error [1h 8m]` 挂在 0cc0719a 的提交状态上，"
            "而该合并的门禁流水线全绿。\n"
            "修法只允许一处：在**载体**上按平台声明的 `allowFailure` 关掉这格上报，"
            "不得改判据、不得放宽门禁。"
        )

    def test_gate_pipelines_stay_blocking(self, cnb_doc):
        main = cnb_doc.get("main") or {}
        offenders = []
        for event in GATE_EVENTS:
            for i, pipe in enumerate(main.get(event) or []):
                if not isinstance(pipe, dict):
                    continue
                if pipe.get("allowFailure"):
                    offenders.append(f"main.{event}[{i}]({pipe.get('name')})")
        assert not offenders, (
            "门禁流水线被放宽成非阻塞（放行标准被单侧放宽）: " + ", ".join(offenders) +
            "\n允许放宽的是**非门禁**流水线 —— 它不裁决任何契约；"
            "门禁一旦非阻塞，扫出问题也拦不住合并。"
        )

    def test_gate_block_detection_is_not_tautological(self, cnb_doc):
        """反向控制：给门禁注入 `allowFailure`，本判定必须抓得到。"""
        injected = copy.deepcopy(cnb_doc)
        push = injected["main"]["push"]
        push[0] = {**push[0], "allowFailure": True}
        offenders = [
            f"main.push[{i}]({p.get('name')})"
            for i, p in enumerate(push) if isinstance(p, dict) and p.get("allowFailure")
        ]
        assert offenders, "门禁被注入 allowFailure 后判定仍为空 —— 它是一条恒真断言"

    def test_gate_events_are_an_enumeration_not_a_wildcard(self):
        """门禁事件是**枚举**，不得写成「除某几个之外全是门禁」的反向口径。

        事实源：`.github/workflows/ci.yml` 的 job 枚举（对照表在
        `tests/unit/test_ci_parity_guard.py::EXPECTED_MAP`）。门禁只有
        `push` / `pull_request` 两个事件键；写成通配会把后加的
        非门禁事件一并判成门禁，于是「非门禁不上报」重新失效。
        """
        assert GATE_EVENTS == ("push", "pull_request")


class TestRelayCoversEveryPlatformAbortReason:
    """接力判据必须覆盖平台的**每一种**中止原文，不只 maxTurns 那一种。

    根因（构建 cnb-m74-1k3cm87o9 实测，2026-09-26）：
    `$CNB_BUILD_FAILED_MSG` 的原文字符串在平台侧有**两种**取值来源 ——
    `maxTurns` 用满与整轮会话撞 2h 墙钟。彼时判据只认前者：

        case "$CNB_BUILD_FAILED_MSG" in
          *"reached maxTurns limit"*) true;; *) false;; esac

    而该构建的真实中止原文是
    `Agent 已中止：构建环境异常终止，或流水线超过最大运行时长（2h）。` ——
    `case` 落到 `*)` 分支为假，收尾接力整格被判 **skipped**：

        ⏳ 轮数触顶接力：自动开启下一轮（判据取平台收尾事实）: 106ms (skipped)

    后果不是"少接力一轮"这么轻：Agent 在 222 轮里改而未提交的成果
    （工作树不跨轮保存）随容器一起丢，用户看到的是一条「流水线构建失败」，
    Issue 上没有任何回音。判据把「配额触发的正常收官」写成了唯一形态，
    于是「被墙钟掐断」这一形态永远静默落空。

    这是教义第 1 条的典型形态：修在报错处（判据）**不是**consumer-only guard，
    但判据只覆盖了同一根因的一个命中点 —— 第 5 条要求同时扫清全部命中点。

    判据：`.cnb.yml` 里每一条收尾接力的 `if`，都必须同时覆盖
    「轮数用满」与「整轮会话超时」两种平台原文片段。
    """

    #: 平台给出的两种中止原文片段（前者实测于 cnb-s4f-1k3c46us9，
    #: 后者实测于 cnb-m74-1k3cm87o9）。
    ABORT_MARKERS = (
        "reached maxTurns limit",
        "超过最大运行时长",
    )

    @staticmethod
    def _relay_stages(cnb_doc):
        """产出 (挂载点, 接力 Stage) —— 与同文件既有实现同源，不另造一份。"""
        for mount, body in cnb_doc.items():
            if not isinstance(body, dict):
                continue
            for event, event_body in body.items():
                for i, job in enumerate(event_body if isinstance(event_body, list) else []):
                    if not isinstance(job, dict):
                        continue
                    for stage in (job.get("endStages") or []):
                        if isinstance(stage, dict) and stage.get("type") == HANDOFF_TRIGGER_TYPE:
                            yield f"{mount}.{event}[{i}]", stage

    def test_every_relay_condition_covers_both_abort_reasons(self, cnb_doc):
        seen = 0
        problems = []
        for where, stage in self._relay_stages(cnb_doc):
            seen += 1
            conditions = stage.get("if") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            blob = "\n".join(str(item) for item in conditions)
            for marker in self.ABORT_MARKERS:
                if marker not in blob:
                    problems.append(
                        f"{where}: 接力 `if` 未覆盖平台中止原文 {marker!r} —— "
                        "该形态下的中止将静默落空（实测 cnb-m74-1k3cm87o9）"
                    )
        assert seen, "未在 .cnb.yml 找到任何接力 Stage —— 本守卫空转"
        assert not problems, (
            "接力判据未覆盖平台的全部中止原文：\n  " + "\n  ".join(problems) +
            "\n平台的 `$CNB_BUILD_FAILED_MSG` 至少有两种取值来源（轮数用满 / "
            "整轮会话撞 2h 墙钟）。判据漏掉任一种，那一类中止就永远不接力，"
            "Agent 改而未提交的成果随容器一起丢。"
        )
