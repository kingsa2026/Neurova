# -*- coding: utf-8 -*-
"""蜂群终态回灌父会话邮箱：投的是信封（关键信息 + 下钻指针），不是正文。

两批裁定叠在这条链上，本文件是它们的落地判据：

**第一批（字段错配）**：全仓唯一的邮箱写点原先挂在 `tool_executor` 的 `spawn()`
返回之后，取 `reply|result|output` 三个信封里从不存在的键（报告键名是 `report`，
见 `SubAgentRun.to_dict()`），投出去的是一条只有前缀、正文为空的壳；而既有判据
用 FakeSwarm 返回自造的 `{"reply": ...}`，替身与读侧一起错向同一个不存在的键，
两边自洽便恒绿。投递时机也错——后台模式 `spawn()` 返回那一刻子任务还没跑完。
故写点收口到终态（`SwarmManager._run_member` 收尾）。

**第二批（表示形态）**：上报不得硬性截断；旁路（邮箱 / 上下文池归档）封装成
信封，涵盖主要关键信息，正文不在旁路里重复——主 Agent 要看详情，凭信封里的
`agent=` / `session=` 指针经 `recall_history` 下钻到记录原始会话的 json。
主链路（工具返回值 `to_dict()`）仍带 report 全文，同轮即可综合。

⚠ 本文件前身名为 `test_subagentCompletionReachesMailboxWithReportBody`，它断
「邮箱正文含报告真值」——那是第一批的形态，已被第二批裁定取代，改名并改写。
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.mailbox import get_agent_mailbox, reset_agent_mailbox
from neurova.agent.swarm import SUBAGENT_PENDING, get_swarm_manager, reset_swarm_manager

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ast_scan import filesUnder, transientTree, parseSource  # noqa: E402

PARENT_SESSION = "s-parent"
REPORT_BODY = "调研结论：β 方案胜出，风险点集中在写入时序"
LONG_REPORT = "长报告正文标记。" + "结论逐条铺开：" + ("证据链片段；" * 400)


@pytest.fixture
def swarm():
    reset_swarm_manager()
    reset_agent_mailbox()
    yield get_swarm_manager()
    reset_agent_mailbox()
    reset_swarm_manager()


def _agentReturning(report: str):
    agent = MagicMock()
    agent.config.name = "调研子Agent"
    agent.chat = AsyncMock(return_value={"text": report})
    return agent


def _envelope(mail: str) -> dict:
    """旁路必须是可解析的信封——按 user 角色注入的文本若解不出结构，下钻就无从下手。"""
    return json.loads(mail.split("] ", 1)[-1] if mail.startswith("[") else mail)


async def _awaitMailArrival(sessionId: str, seconds: float = 2.0) -> list[str]:
    """等后台链跑完再读箱：轮询公开 pending()，带墙钟上界，不碰私有 _tasks。"""
    box = get_agent_mailbox()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if box.pending(sessionId):
            break
        await asyncio.sleep(0.01)
    return box.drain(sessionId)


class TestTerminalStateReachesParentMail:
    """终态必到父会话，且到的是信封。"""

    @pytest.mark.asyncio
    async def test_foregroundTerminalReachesParentMailAsEnvelope(self, swarm):
        agent = _agentReturning(REPORT_BODY)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="调研 β 方案", session_id=PARENT_SESSION)

        mails = get_agent_mailbox().drain(PARENT_SESSION)
        assert len(mails) == 1, f"父会话邮箱应恰有一条终态回灌，实得 {mails}"
        env = _envelope(mails[0])
        assert env["status"] == result["status"]
        assert env["subagent_id"] == result["subagent_id"]
        # 指针在场，且指向真正记下全过程的那条 member 会话
        assert result["member_session_id"] in mails[0], (
            f"信封缺 member 会话指针，主 Agent 无从下钻：{mails[0]!r}"
        )
        assert result["agent_id"] in mails[0], "信封缺会话属主 agent_id——读侧会去错目录"
        assert "recall_history" in mails[0], "信封得点名取回入口，指针才是可执行的指引"
        assert REPORT_BODY not in mails[0], "正文不得在旁路重复一遍（主链路已带全文）"

    @pytest.mark.asyncio
    async def test_backgroundTerminalReachesParentMail(self, swarm):
        """后台模式的回传通道必须真投得出终态——模块说明就是这么承诺的。"""

        async def _slowChat(*args, **kwargs):
            await asyncio.sleep(0.02)
            return {"text": REPORT_BODY}

        agent = _agentReturning("")
        agent.chat = AsyncMock(side_effect=_slowChat)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            ack = await swarm.spawn(
                task="长任务", session_id=PARENT_SESSION, background=True
            )

        assert ack["status"] == SUBAGENT_PENDING
        # 立即返回那一刻还没有终态可投——投出去的必须不是这一刻的空壳
        assert get_agent_mailbox().pending(PARENT_SESSION) == 0
        mails = await _awaitMailArrival(PARENT_SESSION)
        assert mails, f"后台子任务落终态后应回灌父会话，实得 {mails}"
        env = _envelope(mails[0])
        assert env["subagent_id"] == ack["subagent_id"]
        assert ack["member_session_id"] in mails[0]

    @pytest.mark.asyncio
    async def test_failureReasonStaysInEnvelope(self, swarm):
        """成因属关键信息，留在信封里——它不是正文，不需要下钻。"""
        agent = _agentReturning("")
        agent.chat = AsyncMock(side_effect=RuntimeError("LLM 上游 503"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="会失败的任务", session_id=PARENT_SESSION)

        assert result["status"] not in (SUBAGENT_PENDING, "completed")
        mails = get_agent_mailbox().drain(PARENT_SESSION)
        assert mails and "LLM 上游 503" in mails[0], (
            "失败终态要把成因带回父会话，否则主 agent 只看到沉默"
        )


class TestMainLinkKeepsFullReport:
    """主链路（工具返回值）带全文，且硬性截断一律撤除。"""

    @pytest.mark.asyncio
    async def testForegroundReportSurvivesUntruncatedToMainLink(self, swarm):
        agent = _agentReturning(LONG_REPORT)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="长报告", session_id=PARENT_SESSION)

        assert result["report"] == LONG_REPORT, (
            "工具返回值里的报告必须逐字完整——主 Agent 同轮就要综合它"
        )

    @pytest.mark.asyncio
    async def testStatusListKeepsFullReport(self, swarm):
        agent = _agentReturning(LONG_REPORT)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="长报告", session_id=PARENT_SESSION)

        listing = swarm.status("")
        assert listing["status"] == "list"
        assert any(r["report"] == LONG_REPORT for r in listing["runs"]), (
            "列表模式把 report 砍成 300 字符是硬性截断，按裁定撤除"
        )


class TestDrillDownSourceIsPersisted:
    """下钻的源必须真存在：落盘键与信封指针是同一个键。

    真链路 `chat(session_id=…)` → `ChatContext.session_id` → `post_chat_pipeline.process`
    → `_step_save_session` → `MemCore.save_to_session` 按那个键写会话文件。
    活体把这条走通了，但脚本即用即删；这格把「指针即落盘键」钉成常驻判据。
    """

    @pytest.mark.asyncio
    async def testPointerSessionIsTheKeyThePipelinePersistsUnder(self, swarm):
        agent = _agentReturning(REPORT_BODY)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="调研 β 方案", session_id=PARENT_SESSION)

        _, kwargs = agent.chat.call_args
        assert kwargs.get("session_id") == result["member_session_id"], (
            "chat 落盘用的键与信封指针不是同一个——指针会指向一份不存在的会话"
        )
        assert kwargs.get("save_memory", True) is not False, (
            "关掉落盘就得关地下钻；要改必须显式表态并同步撤掉 transcript 指针"
        )


class TestMailScopeUnchanged:
    """反向控制：收口不得把回灌面放宽到本来不回灌的路径。今天就该绿。"""

    @pytest.mark.asyncio
    async def test_rejectedSpawnLeavesMailboxEmpty(self, swarm):
        huge = "任" * 20000
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_agentReturning("x")):
            result = await swarm.spawn(task=huge, session_id=PARENT_SESSION)

        assert result.get("rejected") is True
        assert get_agent_mailbox().pending(PARENT_SESSION) == 0, (
            "被数据层拒绝的派生没有终态报告，不该往父会话投任何信"
        )

    @pytest.mark.asyncio
    async def testWorkflowOriginLeavesMailboxEmpty(self, swarm):
        """工作流派生把报告交给引擎的 output，不经对话循环的邮箱排空。"""
        agent = _agentReturning(REPORT_BODY)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(
                task="工作流子任务",
                session_id=PARENT_SESSION,
                origin="workflow",
                node_id="n1",
                execution_id="e1",
            )

        assert result["report"] == REPORT_BODY
        assert get_agent_mailbox().pending(PARENT_SESSION) == 0


class TestReportKeyIsSingleSource:
    """信封里报告只有一个键名——两个消费方（工作流 / 邮箱）都取 report。"""

    @pytest.mark.asyncio
    async def testSpawnEnvelopeExposesReportUnderSingleKey(self, swarm):
        agent = _agentReturning(REPORT_BODY)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务", session_id=PARENT_SESSION)

        assert result.get("report") == REPORT_BODY
        for ghost in ("reply", "output"):
            assert ghost not in result, (
                f"信封里不存在 {ghost} 键；按它取摘要正是第一批缺陷的读侧形态"
            )


class TestMailboxWriteSideIsSingleSource:
    """写点全仓唯一：投递只发生在蜂群终态，不在下游消费者手里。"""

    def testOnlySwarmWritesParentMailbox(self):
        # 扫描面自证：根若被改窄，下面的「零命中」就不再来自代码（同档棘轮点名的形态）。
        # 下限按本档现读的候选量定，不抄别处的数。
        candidates = [
            p for p in filesUnder(REPO_ROOT / "neurova")
            if p.name != "mailbox.py"  # 定义处自己不算引用方
        ]
        assert len(candidates) > 900, (
            f"候选面现读 {len(candidates)}——根指错了会得到『干净』的假结论"
        )

        referencing: set[str] = set()
        for py in candidates:
            if "get_agent_mailbox" not in py.read_text(encoding="utf-8"):
                continue  # 文本预筛：只为真候选建语法树，不常驻全仓 AST
            tree = transientTree(py)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "get_agent_mailbox":
                    referencing.add(py.relative_to(REPO_ROOT).as_posix())
                elif isinstance(node, ast.Attribute) and node.attr == "get_agent_mailbox":
                    referencing.add(py.relative_to(REPO_ROOT).as_posix())

        assert referencing == {
            "neurova/agent/swarm.py",
            "neurova/agent/loops/base.py",
        }, (
            "邮箱写点应在蜂群终态一处、读点在 loop 排空一处；"
            f"实得 {sorted(referencing)}——多出的那份就是第二事实源"
        )


class TestNoHardTruncationInUplink:
    """三处砍正文的字面量必须退役，连写口一起拒（防止换个数字复活）。"""

    #: 正文侧字段——按裁定不得按字面量砍长度。`uuid4().hex[:12]` 这类标识生成不在内。
    BODY_FIELDS = ("report", "task", "error")

    @staticmethod
    def _slicedSource(node: ast.Subscript) -> str:
        """被切对象指向哪个字段名：`run.report` 与 `r["report"]` 两形都要认。"""
        src = node.value
        if isinstance(src, ast.Attribute):
            return src.attr
        if isinstance(src, ast.Subscript) and isinstance(src.slice, ast.Constant):
            return str(src.slice.value)
        return ""

    def testSwarmNoLongerSlicesBodyByLiteralLength(self):
        src = (REPO_ROOT / "neurova" / "agent" / "swarm.py").read_text(encoding="utf-8")
        tree = parseSource(src)
        sliced = [
            f"line{node.lineno}:{self._slicedSource(node)}[:{node.slice.upper.value}]"
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Slice)
            and isinstance(node.slice.upper, ast.Constant)
            and self._slicedSource(node) in self.BODY_FIELDS
        ]
        assert not sliced, (
            f"旁路仍在按字面量砍正文：{sliced}——本模块正文的长度尺度只允许来自具名声明，"
            "不留散落的数字上界"
        )

    def testMailBodyCharConstantRetired(self):
        from neurova.agent.swarm import SwarmManager

        assert not hasattr(SwarmManager, "MAIL_BODY_CHARS"), (
            "第一批引入的 400 字符尺度已被裁定取代，留着就是第二个尺度源"
        )
