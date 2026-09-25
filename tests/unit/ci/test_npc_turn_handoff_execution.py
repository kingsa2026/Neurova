# -*- coding: utf-8 -*-
"""NPC 轮数触顶接力的**执行面**守卫（Issue #145）。

## 为什么需要这份守卫

配置面已经有一份守卫（`tests/unit/test_ci_npc_config_guard.py` 的
`TestTurnHandoffCeiling`）：它钉住「`.cnb.yml` 里有这笔接力」——
`endStages` 里存在 `cnb:apply`、`event` 与触发事件同名、标记经 `env` 传下来。

但那份配置**从来没有被执行过**：接力 Stage 的 `if` 读的标记是 Agent 自己
在最后一轮写出的文件，而写在哪里由人设文本约定。构建 cnb-2e8-1k341d9s1 的
实测形态正是这样：

    Master[agent][201] stop with error: Agent aborted: reached maxTurns limit (200)
    ✅ DebugDetection / End 通过
    ⏳ 轮数触顶接力：自动开启下一轮 → skipped

Agent 从未写出标记，于是 `if` 恒假、接力被跳过、成果随容器一起丢，
用户在 Issue 上只看到「流水线构建失败」。配置面守卫对此是完全绿的 ——
它只能证明"接力被声明过"，证明不了"接力会真的发生"。

## 本文件钉三件事（都可证伪）

- **A 落点词汇统一**：`$CNB_BUILD_WORKSPACE` 是接力判据的唯一落点，
  凡提到"标记写在哪"的人设文本必须用这个变量，不得退化成
  「工作区工作目录 / 构建目录 / workspace 目录」这类字面表述 ——
  后者会让 Agent 把它理解成 `$PWD`，在两者不同的构建里写错位置。
- **B 落点在构建里可达**：`scripts/ci/npc_turn_handoff_gate.py` 存在，
  且被 `.cnb.yml` 的 NPC 流水线真实执行（不是躺在仓库里当摆设）。
- **C 门禁留在受保护子集**：门禁脚本的判据要在 CI 上真的跑，否则 A/B 无人执行。

可证伪路径：
- 把 `.cnb.yml` 里跑门禁的那一步删掉 → B 红；
- 把人设里 `$CNB_BUILD_WORKSPACE/.npc-turn-handoff` 改写成「工作区工作目录」→ A 红；
- 从 `scripts/ci/protected_tests.txt` 摘掉本文件 → C 红。
"""
import ast
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

#: 接力标记的文件名（与 `.cnb/settings.yml` 人设、`.cnb.yml` 收尾阶段同一事实源）
HANDOFF_MARKER_FILE = ".npc-turn-handoff"

#: 落点变量：标记必须写在 `$CNB_BUILD_WORKSPACE` 下，而不是「工作目录」这类字面表述。
HANDOFF_ROOT_VAR = "$CNB_BUILD_WORKSPACE"

#: 门的脚本（接力判据可达性自证）
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "npc_turn_handoff_gate.py"

#: 人设提到标记落点时的**正确**写法（逐字）
MARKER_PATH_IN_PERSONA = f"{HANDOFF_ROOT_VAR}/{HANDOFF_MARKER_FILE}"

#: 同一句话里绝不允许出现的模糊说法：它们会被读成 `$PWD`，而非工作区根。
VAGUE_ROOT_PHRASES = ("工作区工作目录", "构建目录", "workspace 目录", "工作目录下")


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


class TestHandoffRootIsTheWorkspaceVariable:
    """A. 标记落点必须用 `$CNB_BUILD_WORKSPACE` 表达，不得退化成字面目录名。"""

    def test_personas_state_the_marker_path_with_the_workspace_variable(self, npc_personas):
        missing = [name for name, prompt in npc_personas.items() if MARKER_PATH_IN_PERSONA not in prompt]
        assert not missing, (
            f"NPC 人设未把标记落点写成 {MARKER_PATH_IN_PERSONA}: {missing}\n"
            "收尾阶段读的是 `$CNB_BUILD_WORKSPACE/"
            f"{HANDOFF_MARKER_FILE}`；写法一旦含糊（如「工作区工作目录」），"
            "Agent 会把它当成 $PWD，在两者不同的构建里写到收尾读不到的位置，"
            "接力整条失效（构建 cnb-2e8-1k341d9s1 的跳过形态）。"
        )

    def test_personas_do_not_use_vague_directory_phrases(self, npc_personas):
        offenders = []
        for name, prompt in npc_personas.items():
            for line in prompt.splitlines():
                if HANDOFF_MARKER_FILE not in line:
                    continue
                for phrase in VAGUE_ROOT_PHRASES:
                    if phrase in line:
                        offenders.append(f"{name}: 「{phrase}」出现在 {line.strip()}")
        assert not offenders, (
            "标记落点用了会被读成 $PWD 的模糊表述:\n  " + "\n  ".join(offenders) +
            f"\n统一写成 {MARKER_PATH_IN_PERSONA}（单一事实源）。"
        )

    def test_cnb_comment_only_cites_the_variable_form(self, cnb_doc):
        """`.cnb.yml` 里提到标记落点时，同样只准用变量形态。"""
        text = io.open(CNB, encoding="utf-8").read()
        bad = [
            f"{lineno}: {line.strip()}"
            for lineno, line in enumerate(text.splitlines(), 1)
            if HANDOFF_MARKER_FILE in line and HANDOFF_ROOT_VAR not in line
        ]
        assert not bad, (
            "`.cnb.yml` 提到接力标记时未点明落点变量:\n  " + "\n  ".join(bad) +
            f"\n落点只有一处：{MARKER_PATH_IN_PERSONA}。"
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
            "该步在真实构建里断言 `$CNB_BUILD_WORKSPACE/.npc-turn-handoff` 可写可读，"
            "并反向自证 $PWD 是否等于 $CNB_BUILD_WORKSPACE——"
            "这是接手时唯一能回答「标记到底写在哪」的读数。"
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

    `$CNB_BUILD_WORKSPACE` 落点、`##[set-output]` + `exports` 通道、`if` 判据——
    前两批修的东西**全部生效**了：Stage 0 打印 `turn_flag_handoff.written=true`，
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
