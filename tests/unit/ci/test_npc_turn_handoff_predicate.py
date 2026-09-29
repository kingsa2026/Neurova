# -*- coding: utf-8 -*-
"""轮数触顶接力的**判据来源**守卫（Issue #158 收口）。

## 根因（实测，不是推测）

接力的前提是「这一轮真的撞满了轮数配额」。而判据的生产方把它交给
**Agent 开工之前**跑的门禁无条件写成 1：

    $NPX_CALL scripts/ci/npc_turn_handoff_gate.py      # Agent 开工前
    ##[set-output turnLimitReached=1]                  # ← 与是否撞顶无关

于是「用户新发的 @ → 变量为空 → 不接力」这条空轮防护**从未成立过**。
实测（评论触发的父构建，maxTurns=200，收尾接力一律 success）：

    cnb-2q8-1k3buskao   97 / 200 轮 → 接力 success
    cnb-tr2-1k3bm5ssd  135 / 200 轮 → 接力 success
    cnb-cou-1k3bmaal8  164 / 200 轮 → 接力 success
    cnb-ofm-1k3bq16ij   76 / 200 轮 → 接力 success

代价可复算：`api_trigger_npc_handoff` 共 32 次构建 / 22.2 小时墙钟，
其中 17 次又跑满 200 轮 —— 一次普通提问被放大成一条自动续跑的链条。

## 本文件钉三件事（都可证伪）

- **A 判据取平台事实**：收尾接力的 `if` 必须直接读平台在收尾时刻注入的
  `$CNB_PIPELINE_STATUS` 与失败 stage 名（v2），不得读「上一轮预写」的变量。
  实测（探针 cnb-c9g-1k3c3dqg7 / cnb-p2q-1k3c2g7u3，2026-09-25）：
  在 `endStages` 里 `CNB_PIPELINE_STATUS=error`、
  `CNB_BUILD_FAILED_STAGE_NAME=force-maxTurns-abort`。
- **A′ 判据加问第三问**（Issue #327）：平台网关的外部中止与撞满配额在收尾期的
  可见形态相同，判据必须再问「可归因到时长配额吗」——消费运行时长预算量尺的
  `--predicate` 出口（阈值的唯一事实源仍在量尺脚本里）。
- **B 判据时机合法**：这两个变量只在收尾时刻成立（`failStages` 里为空，
  探针 cnb-o8q-1k3c25fpt 实测），故判据只能出现在 `endStages` 的 `if` 上，
  不得出现在 Agent 开工前的 Stage。
- **C 接力落点自己有接力**：`api_trigger_npc_handoff` 也要有同一份收尾接力，
  否则接力轮一旦再撞顶就断链（实测 17 次接力轮以 error 收场）。

可证伪路径：把 `if` 改回读 `$turnLimitReached` → A 红；
删掉判据第三问 → A′ 红；把判据挪回 Agent 开工前的 Stage → B 红；
删掉接力落点的 `endStages` → C 红。
"""
import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 平台在收尾时刻注入的两个事实变量（实测读数见模块 docstring）。
#: v2（Issue #272）：第二个是**失败 stage 名**，不是失败 stage 的最后一行输出。
#: 实测（探针 cnb-m16-1k3f5s0ri）证明 `$CNB_BUILD_FAILED_MSG` 的取值是
#: 失败 stage 自己打印的最后一行（Job 被 SIGKILL 后为 `start`），
#: 按它匹配文案等于看运气；`$CNB_BUILD_FAILED_STAGE_NAME` 才是确定性事实。
STATUS_VAR = "CNB_PIPELINE_STATUS"
FAILED_STAGE_VAR = "CNB_BUILD_FAILED_STAGE_NAME"

#: npc:go 所在 stage 名里的 ASCII 标记（判据按它匹配）。
GO_STAGE_MARKER = "npc-go"

#: 被实测推翻的 v1 事实源（不得作为判据的唯一输入）。
FAILED_MSG_VAR = "CNB_BUILD_FAILED_MSG"

#: 已被证伪的旧判据：由 Agent 开工前的门禁无条件写出的变量。
RETIRED_FLAG = "turnLimitReached"

#: 收尾接力落点事件。
HANDOFF_EVENT = "api_trigger_npc_handoff"

#: 判据第三问的消费标记（Issue #327）：`eval "$($NPX_PREDICATE)"` ——
#: `$NPX_PREDICATE` 由解释器探测段登记，取值指向运行时长预算量尺。
PREDICATE_MARKER = "NPX_PREDICATE"

#: 收尾接力唯一允许的内置任务类型（适用「所有事件」，见 cnb/trigger.md）。
HANDOFF_TRIGGER_TYPE = "cnb:trigger"


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return yaml.safe_load(io.open(CNB, encoding="utf-8").read())


def _end_stages_by_event(cnb_doc):
    """产出 ($ 段每个真实事件名 → 其 Job 的 endStages 列表)。"""
    fallback = cnb_doc.get("$") or {}
    for event, body in fallback.items():
        if not isinstance(event, str) or event.startswith("."):
            continue
        yield event, [
            stage
            for job in (body if isinstance(body, list) else [])
            if isinstance(job, dict)
            for stage in (job.get("endStages") or [])
            if isinstance(stage, dict)
        ]


def _relay_stages(cnb_doc):
    """产出全部 (事件名, 接力 Stage)：type 为 cnb:trigger 且拉接力落点事件。"""
    for event, stages in _end_stages_by_event(cnb_doc):
        for stage in stages:
            options = stage.get("options") or {}
            if stage.get("type") == "cnb:trigger" and options.get("event") == HANDOFF_EVENT:
                yield event, stage


class TestPredicateReadsPlatformFacts:
    """A. 判据必须取自平台在收尾时刻给出的事实，而不是上一轮预写的变量。"""

    def test_relay_stages_exist(self, cnb_doc):
        relays = list(_relay_stages(cnb_doc))
        assert relays, (
            f"`$` 段找不到任何收尾接力（cnb:trigger → {HANDOFF_EVENT}）—— 本守卫空转"
        )

    def test_conditions_read_the_platform_facts(self, cnb_doc):
        """每条接力的 `if` 必须同时判定 status=error 与「失败 stage 是 Agent 那格」。

        v2：判据的第二个事实源是 `$CNB_BUILD_FAILED_STAGE_NAME`（确定性），
        不是 `$CNB_BUILD_FAILED_MSG`（失败 stage 的最后一行输出，实测不可靠）。
        """
        problems = []
        for event, stage in _relay_stages(cnb_doc):
            joined = " ".join(str(c) for c in (stage.get("if") or []))
            if STATUS_VAR not in joined:
                problems.append(f"{event}: 判据未读 ${STATUS_VAR}（收尾状态由平台给出）")
            if FAILED_STAGE_VAR not in joined:
                problems.append(
                    f"{event}: 判据未读 ${FAILED_STAGE_VAR}"
                    "—— 上一轮的预写变量与「是否真被中止」无关"
                )
            if GO_STAGE_MARKER not in joined:
                problems.append(
                    f"{event}: 判据未匹配 npc:go 的 stage 名标记 {GO_STAGE_MARKER!r}"
                )
        assert not problems, (
            "收尾接力的判据没取平台事实:\n  " + "\n  ".join(problems) +
            "\n实测（探针 cnb-c9g-1k3c3dqg7，2026-09-25）：endStages 里 "
            f"{STATUS_VAR}=error；失败 stage 名由 ${FAILED_STAGE_VAR} 给出。"
        )

    def test_conditions_also_ask_whether_the_abort_is_quota_attributable(self, cnb_doc):
        """判据必须再问一句「这次中止可归因到时长配额吗」（Issue #327）。

        前两条判据答的是「有没有被中止在 Agent 那一格」——它们对
        「这次中止是不是撞墙」一无所知。构建 cnb-urv-1k3lagkdv 实测：平台 AI 网关
        在第 36 轮 / 7.4 分钟主动中止（`Pipeline has been stopped, Agent aborted`，
        该轮 `in=0 out=0 duration=0.0s`），四道上限一道都没触达，而接力照样触发 ——
        于是每约 7 分钟一轮的自动续跑链条，每一轮都真实计入 LLM 成本。
        """
        offenders = [
            f"{event}: 判据未消费 ${PREDICATE_MARKER} —— 外部中止与撞满配额"
            "在收尾期的可见形态相同，缺这一问就分不开（Issue #327）"
            for event, stage in _relay_stages(cnb_doc)
            if PREDICATE_MARKER not in " ".join(str(c) for c in (stage.get("if") or []))
        ]
        assert not offenders, "\n  ".join(offenders)

    def test_conditions_do_not_judge_on_the_message_text(self, cnb_doc):
        """反向控制：判据不得只认 `$CNB_BUILD_FAILED_MSG` 的文案。

        实测（cnb-m16-1k3f5s0ri）：该变量是失败 stage 最后一行输出，
        Job 被 SIGKILL 后取值是脚本自己最后 echo 的那行（`start`）。
        """
        offenders = []
        for event, stage in _relay_stages(cnb_doc):
            joined = " ".join(str(c) for c in (stage.get("if") or []))
            if FAILED_MSG_VAR in joined:
                offenders.append(
                    f"{event}: 判据仍在读 ${FAILED_MSG_VAR} ——"
                    "它是失败 stage 的最后一行输出，不是平台文案"
                )
        assert not offenders, "\n  ".join(offenders)

    def test_relay_never_reads_the_retired_prewritten_flag(self, cnb_doc):
        """旧判据变量必须删净：它与「本轮是否撞顶」无关，是第二条平行判据。"""
        offenders = []
        for event, stage in _relay_stages(cnb_doc):
            if RETIRED_FLAG in " ".join(str(c) for c in (stage.get("if") or [])):
                offenders.append(f"{event}: if 仍读 ${RETIRED_FLAG}")
            if RETIRED_FLAG in ((stage.get("options") or {}).get("env") or {}):
                offenders.append(f"{event}: env 仍传出 ${RETIRED_FLAG}")
        # 注释里保留旧形态是**必要的理由记录**（"判据曾来自开工前的预写变量，
        # 已被实测证伪"），不构成违规；真去读它的写法必须消失。
        for lineno, raw in enumerate(io.open(CNB, encoding="utf-8"), 1):
            stripped = raw.strip()
            if RETIRED_FLAG in stripped and not stripped.startswith("#"):
                offenders.append(f"{CNB.name}:{lineno}: {stripped}")
        assert not offenders, (
            "已被证伪的预写变量仍在接力链上:\n  " + "\n  ".join(offenders) +
            "\n它由 Agent 开工前的门禁无条件写成 1（实测 4 条父构建在 76~164 轮即接力），"
            "不构成「本轮撞顶」的证据。判据只有一处：平台事实变量。"
        )


class TestPredicateTimingIsLegal:
    """B. 平台事实变量只在收尾时刻成立，判据不得出现在 Agent 开工前。"""

    def test_no_pre_agent_stage_reads_the_platform_facts(self, cnb_doc):
        """`stages`（Agent 开工前）里不得出现收尾时刻才成立的变量。

        实测（探针 cnb-o8q-1k3c25fpt，2026-09-25）：同一个 Job 的 `failStages`
        里 `$CNB_PIPELINE_STATUS` 为空串，`endStages` 里才是 `error`。
        判据落在 `.cnb.yml` 的文本上：`stages` 与 `endStages` 是两个键，
        故直接按缩进块判定——`stages:` 下不得出现这两个变量名。
        """
        lines = io.open(CNB, encoding="utf-8").read().splitlines()
        offenders, in_stages, base = [], False, 0
        for lineno, raw in enumerate(lines, 1):
            stripped = raw.strip()
            if stripped.startswith("#") or not stripped:
                continue
            indent = len(raw) - len(raw.lstrip())
            if re.match(r"^\s*stages:\s*$", raw):
                in_stages, base = True, indent
                continue
            if in_stages and indent <= base:
                in_stages = False
            if in_stages and (STATUS_VAR in stripped or FAILED_STAGE_VAR in stripped):
                offenders.append(f"{lineno}: {stripped}")
        assert not offenders, (
            "收尾时刻才成立的变量被用在 Agent 开工前的 Stage 里（该处读数为空）:\n  "
            + "\n  ".join(offenders) +
            "\n实测探针 cnb-o8q-1k3c25fpt：同一 Job 的 failStages 里这两个变量为空串，"
            "只有 endStages 里才有真值。"
        )


class TestHandoffLandingPointRelaysToo:
    """C. 接力落点自己也要有接力，否则接力轮撞顶即断链。"""

    def test_handoff_event_has_its_own_relay(self, cnb_doc):
        relays = {event for event, _stage in _relay_stages(cnb_doc)}
        assert HANDOFF_EVENT in relays, (
            f"{HANDOFF_EVENT} 自身没有收尾接力 —— 接力轮一旦再撞顶就断链。"
            "实测 17 次接力轮以 error 收场（如 cnb-sis-1k3bnmick / cnb-f08-1k3bqnvtf），"
            "成果随容器一起丢。"
        )

    def test_handoff_event_relay_carries_the_context_forward(self, cnb_doc):
        """接力落点的接力要把对话载体继续传下去（它拿不到评论期注入的变量）。"""
        envs = [
            (stage.get("options") or {}).get("env") or {}
            for event, stage in _relay_stages(cnb_doc) if event == HANDOFF_EVENT
        ]
        assert envs, f"{HANDOFF_EVENT} 没有接力 Stage"
        keys = {str(k) for env in envs for k in env}
        assert {"handoffIssueIid", "handoffPrIid"} & keys, (
            f"{HANDOFF_EVENT} 的接力未把 Issue/PR 标识继续传下去（下一轮读不到对话载体）：{sorted(keys)}"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_npc_turn_handoff_predicate.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )


class TestCarrierDeclaresNoSelfReferencingEnv:
    """收尾接力链上的 ``env`` 不得出现**自引用**：那是同一条静默失效面的下一个命中点。

    ## 实测形态（构建 cnb-5bc-1k3e046c7，2026-09-26）

    评论触发的 NPC 流水线（``issue.comment@npc`` / ``pull_request.comment@npc``）
    在收尾把对话载体经 ``cnb:trigger`` 传给接力轮，两侧各只供自己那一侧的键：

        # issue.comment@npc 的 endStages
        env:
          handoffIssueIid: $CNB_ISSUE_IID
        # pull_request.comment@npc 的 endStages
        env:
          handoffPrIid: $CNB_PULL_REQUEST_IID

    而接力落点 ``api_trigger_npc_handoff`` 的**载体层**又把两个键都声明成
    "同名变量"：

        env:
          handoffIssueIid: $handoffIssueIid
          handoffPrIid: $handoffPrIid

    于是 issue 侧那一跳里 ``$handoffPrIid`` 无处可解析。平台在**配置期与运行期
    都不报错**，只是在替换后把它写成字面量 ``$handoffPrIid``；下一跳的 carries
    再读它、再写一次，字面量沿着链**越掺越长**（实测 18 → 35 → 84 字符）：

        +84 characters ... "...$handoffPrIid-1k3ddqln6$handoffPrIid"

    最终 ``cnb:trigger`` 的目标流水线名被这个值掺坏，报错落在**与它无关**的
    地方：

        docker: Error response from daemon: Invalid container name (x),
        only [a-zA-Z0-9][a-zA-Z0-9_.-] are allowed

    ## 根因（教义第 1 条：修在生产非法状态的那一处）

    非法状态的生产点**不是**报错那一格，而是"声明了 ``$同名变量``，却没有任何
    一跳向它赋值"这种写法本身。修法是让两份 ``env`` 映射**键集合对齐**：

    * 接力落点（载体）只声明上一跳真的会传下来的键，且不再自引用；
    * 上游两跳（评论侧与载体侧的收尾接力）把两个键都显式供上，
      不适用的一侧给空串——空串经 ``cnb:trigger.options.env`` 传下去是
      有界的，不会掺坏目标流水线名。

    ## 判据

    判据落在"被触发方声明了哪些键"与"触发方供上了哪些键"的**集合关系**上，
    不落在注释或取值形态上：

    * 载体层的 ``env`` 不得出现 ``$同名`` 自引用；
    * 每一个 ``cnb:trigger.options.env`` 的键集合，必须覆盖目标事件载体层
      ``env`` 声明的键集合（含自接力那一跳）；
    * 载体层自己续链时，必须把同一组键继续传下去（否则第二跳就丢载体）。
    """

    @staticmethod
    def _carrier_declared_keys(cnb_doc, event):
        """载体层（被触发方）自身声明的键 —— 就是它承诺会读的那几个。

        载体层**允许**声明与上层同名的键（`env` 文件是可选的读取面），但取值
        不得是 `$同名变量`：真值只由触发方的 `cnb:trigger.options.env` 给出。
        """
        fallback = cnb_doc.get("$") or {}
        target = fallback.get(event)
        if target is None:
            return None
        jobs = target if isinstance(target, list) else [target]
        declared = set()
        for job in jobs:
            if not isinstance(job, dict):
                continue
            for key in (job.get("env") or {}):
                declared.add(str(key))
        return declared

    @staticmethod
    def _carrier_promised_keys(cnb_doc, event):
        """载体层**承诺会读**的键：声明的键 ∪ 它在自己的 pipeline 里引用的载体变量。

        后者是必要的：载体层不声明 `env` 时（平台「环境变量」篇允许子流水线
        直接读到触发方给的 env），承诺面就只能从它对 `$handoff*` 的**引用**读出来
        —— 上一跳的 `options.env` 里逐字引用了它。
        """
        declared = TestCarrierDeclaresNoSelfReferencingEnv._carrier_declared_keys(cnb_doc, event)
        assert declared is not None, f"`$` 段缺少接力落点事件 {event}"
        keys = set(declared)
        upstream = TestCarrierDeclaresNoSelfReferencingEnv._upstream_hops(cnb_doc, event)
        consumed = {k for core in ("handoff", "relay") for k in (f"{core}IssueIid", f"{core}PrIid")}
        for _event, env_map in upstream:
            for _key, value in env_map.items():
                literal = str(value).strip().lstrip("$")
                if literal in consumed:
                    keys.add(literal)
        return keys

    @staticmethod
    def _upstream_hops(cnb_doc, event):
        """产出 (上游事件名, 该跳 `cnb:trigger.options.env`) —— 谁把上下文传下来。"""
        fallback = cnb_doc.get("$") or {}
        upstream = []
        for other, body in fallback.items():
            if not isinstance(other, str) or other.startswith("."):
                continue
            for job in (body if isinstance(body, list) else []):
                if not isinstance(job, dict):
                    continue
                for stage in (job.get("endStages") or []):
                    if not isinstance(stage, dict):
                        continue
                    if stage.get("type") != HANDOFF_TRIGGER_TYPE:
                        continue
                    options = stage.get("options") or {}
                    if options.get("event") != event:
                        continue
                    upstream.append((other, dict(options.get("env") or {})))
        return upstream

    @staticmethod
    def _declared_env_keys(cnb_doc, event):
        """产出 (载体层承诺会读的键集, [(上游事件, 该跳供上的键集)])。"""
        if (cnb_doc.get("$") or {}).get(event) is None:
            return None, []
        declared = TestCarrierDeclaresNoSelfReferencingEnv._carrier_promised_keys(cnb_doc, event)
        upstream = [
            (other, {str(k) for k in env_map})
            for other, env_map in TestCarrierDeclaresNoSelfReferencingEnv._upstream_hops(cnb_doc, event)
        ]
        return declared, upstream

    def test_carrier_env_does_not_reference_itself(self, cnb_doc):
        """载体层 ``env`` 的取值不得是 ``$同名`` —— 没有上游赋值，只会掺坏下游。"""
        fallback = cnb_doc.get("$") or {}
        body = fallback.get(HANDOFF_EVENT)
        assert body, f"`$` 段缺少接力落点事件 {HANDOFF_EVENT}"
        offenders = []
        for job in (body if isinstance(body, list) else []):
            if not isinstance(job, dict):
                continue
            for key, value in (job.get("env") or {}).items():
                if str(value).strip() == f"${key}":
                    offenders.append(f"{key}: {value}")
        assert not offenders, (
            "接力载体的 env 出现自引用（`$同名变量`），上一跳并不会给它赋值：\n  "
            + "\n  ".join(offenders) +
            "\n平台对无值变量**不报错也不告警**，只把配置里的 `$name` 当字面量往下传；"
            "实测（构建 cnb-5bc-1k3e046c7）该字面量沿链越掺越长，"
            "最终把 cnb:trigger 的目标流水线名掺坏，报错落在"
            "`Invalid container name (x)` 这种与它无关的地方。"
        )

    def test_every_upstream_hop_supplies_the_carrier_keys(self, cnb_doc):
        """每一跳都必须把载体声明的键供上；不适用的一侧给空串，不许缺键。

        实测形态：issue 侧只传 ``handoffIssueIid``、PR 侧只传 ``handoffPrIid``，
        而载体两个键都要 —— 缺的那一个就成了 ``$handoffPrIid`` 字面量的源头。
        """
        declared, upstream = self._declared_env_keys(cnb_doc, HANDOFF_EVENT)
        assert declared is not None, f"`$` 段缺少接力落点事件 {HANDOFF_EVENT}"
        assert declared, f"{HANDOFF_EVENT} 未声明任何对话载体键 —— 本守卫空转"
        assert upstream, (
            f"没有任何事件把上下文传给 {HANDOFF_EVENT} —— 下一轮读不到对话载体"
        )
        problems = [
            f"{event}: 缺键 {sorted(declared - keys)}（载体声明了 {sorted(declared)}）"
            for event, keys in upstream if declared - keys
        ]
        assert not problems, (
            "收尾接力没有把载体声明的键全部供上：\n  " + "\n  ".join(problems) +
            "\n未供上的键在下一跳会被写成字面量 `$键名` 并沿链越掺越长——"
            "平台对无值变量不报错，故障最终落在与它无关的地方"
            "（实测构建 cnb-5bc-1k3e046c7）。"
        )
