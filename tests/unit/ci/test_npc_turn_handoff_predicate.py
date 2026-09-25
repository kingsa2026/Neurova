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
  `$CNB_PIPELINE_STATUS` 与 `$CNB_BUILD_FAILED_MSG`，不得读「上一轮预写」
  的变量。实测（探针 cnb-c9g-1k3c3dqg7 / cnb-p2q-1k3c2g7u3，2026-09-25）：
  在 `endStages` 里 `CNB_PIPELINE_STATUS=error`、
  `CNB_BUILD_FAILED_MSG=Agent aborted: reached maxTurns limit (N)`。
- **B 判据时机合法**：这两个变量只在收尾时刻成立（`failStages` 里为空，
  探针 cnb-o8q-1k3c25fpt 实测），故判据只能出现在 `endStages` 的 `if` 上，
  不得出现在 Agent 开工前的 Stage。
- **C 接力落点自己有接力**：`api_trigger_npc_handoff` 也要有同一份收尾接力，
  否则接力轮一旦再撞顶就断链（实测 17 次接力轮以 error 收场）。

可证伪路径：把 `if` 改回读 `$turnLimitReached` → A 红；
把判据挪回 Agent 开工前的 Stage → B 红；删掉接力落点的 `endStages` → C 红。
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
STATUS_VAR = "CNB_PIPELINE_STATUS"
FAILED_MSG_VAR = "CNB_BUILD_FAILED_MSG"

#: 平台自己的中止措辞。实测原文 `Agent aborted: reached maxTurns limit (200)`，
#: 在四条独立构建里逐字一致。判据只认这一个子串，不认「上一轮写的标记」。
ABORT_MARKER = "reached maxTurns limit"

#: 已被证伪的旧判据：由 Agent 开工前的门禁无条件写出的变量。
RETIRED_FLAG = "turnLimitReached"

#: 收尾接力落点事件。
HANDOFF_EVENT = "api_trigger_npc_handoff"


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
        """每条接力的 `if` 必须同时判定 status=error 与 maxTurns 中止。"""
        problems = []
        for event, stage in _relay_stages(cnb_doc):
            joined = " ".join(str(c) for c in (stage.get("if") or []))
            if STATUS_VAR not in joined:
                problems.append(f"{event}: 判据未读 ${STATUS_VAR}（收尾状态由平台给出）")
            if ABORT_MARKER not in joined:
                problems.append(
                    f"{event}: 判据未认平台的中止措辞 {ABORT_MARKER!r}"
                    "—— 上一轮的预写变量与「是否真撞顶」无关"
                )
            if FAILED_MSG_VAR not in joined:
                problems.append(f"{event}: 判据未读 ${FAILED_MSG_VAR}（中止原因由平台给出）")
        assert not problems, (
            "收尾接力的判据没取平台事实:\n  " + "\n  ".join(problems) +
            "\n实测（探针 cnb-c9g-1k3c3dqg7，2026-09-25）：endStages 里 "
            f"{STATUS_VAR}=error、{FAILED_MSG_VAR}='Agent aborted: {ABORT_MARKER} (1)'。"
        )

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
            if in_stages and (STATUS_VAR in stripped or FAILED_MSG_VAR in stripped):
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
