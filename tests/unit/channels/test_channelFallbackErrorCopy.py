# -*- coding: utf-8 -*-
"""批 G1：渠道兜底错误文案单源。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 G）：
单处理器路径的兜底文案「抱歉，处理消息时出现错误，请稍后重试。」硬编码在
`_dispatch_message` 的发送点内联——改措辞要找散在代码里的中文字符串；同点的
`except Exception: pass` 把"错误提示回发也失败了"吞成无声。本批：文案收进
模块常量单源；吞异常改成点名日志（回发失败本身经批 F 台账有归宿，这里的
except 只接 send_message 抛异常的残余路径，必须出声）。
"""
import ast
import asyncio
import pathlib

import pytest

from tests import ast_scan
from tests.ast_scan import parseSource

REPO = pathlib.Path(__file__).resolve().parents[3]
CHANNELS_DIR = REPO / "neurova" / "channels"


def _channelSources() -> dict:
    """渠道族源码面——**先验面宽，再谈「零命中」**。

    根写错（`parents[3]` 按本档所在深度算）时这里返回空 dict，于是本档那两条
    「字面量只在 manager.py 一处」「`_dispatch_message` 里没有 pass-only except」
    会以零命中假绿——读数说"干净"，其实什么都没看（§6-491 由常驻棘轮
    `test_scanCriterionMustProveItsOwnSurfaceRatchet` 抓到这一形）。
    """
    # 枚举走共享预算（`tests/ast_scan`）：私有 `glob + parseSource` 会把「代码总量」
    # 编码成墙钟上界（`tests/unit/test_ci_ast_scan_budget_guard.py` 的根因）。
    sources = {ref.path.name: ref.code
               for ref in ast_scan.sourceRefsUnder(CHANNELS_DIR, ".py")}
    scanned = len(sources)
    assert scanned > 50, (
        f"扫描面现读 {scanned} 个文件（`neurova/channels/*.py` 本批实测 61）——"
        "根指不到该目录时，本档的「零命中」断言全部失真"
    )
    return sources


class TestFallbackErrorCopySingleSource:
    def test_fallbackTextIsAModuleConstantNotAnInlineLiteral(self):
        """兜底文案只许以常量定义一次；发送点引用常量名，不许再写第二份内联。"""
        sources = _channelSources()
        literal = "抱歉，处理消息时出现错误，请稍后重试。"
        holders = [name for name, text in sources.items() if literal in text]
        assert holders == ["manager.py"], (
            f"兜底文案字面量出现处 {holders}——只许在 manager.py 常量定义一处"
        )
        assert "FALLBACK_ERROR_TEXT = " in sources["manager.py"], (
            "manager.py 里没有具名常量（文案仍是散落内联）"
        )
        # 发送点必须引常量：内联字面量出现在常量定义行之外的次数为 0
        body_lines = [l for l in sources["manager.py"].splitlines()
                      if literal in l and "FALLBACK_ERROR_TEXT = " not in l]
        assert body_lines == [], f"兜底文案在常量之外还有内联出现：{body_lines}"

    def test_fallbackSendFailureIsNotSilentlySwallowed(self):
        """_dispatch_message 里不许有 pass-only 的 except——兜底回发自身失败
        必须出声（现读该函数恰一处：兜底 send 的 except Exception: pass）。"""
        src = _channelSources()["manager.py"]
        tree = parseSource(src)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                    and node.name == "_dispatch_message":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ExceptHandler) \
                            and len(sub.body) == 1 and isinstance(sub.body[0], ast.Pass):
                        found.append(sub.lineno)
        assert found == [], (
            f"_dispatch_message 里有 pass-only except（行 {found}）——"
            "兜底回发失败被吞成无声，必须点名日志"
        )


class TestFallbackCopyBehavior:
    @pytest.fixture()
    def manager(self, tmp_path):
        from tests.manual._liveVerifyIsolation import isolatedDataRoot

        isolatedDataRoot()
        from neurova.channels.base import ChannelConfig
        from neurova.channels.feishu import FeishuAdapter
        from neurova.channels.manager import ChannelManager, get_channel_manager

        isolatedDataRoot()
        ChannelManager._instance = None
        mgr = get_channel_manager()
        mgr.ingress_queue = False
        mgr.outbound_ledger = False  # 台账不是本批主张

        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_g",
                                              app_secret="sec", use_stream=False))
        adapter._connected = True
        sent = []

        async def _record(chat_id, content, message_type="text", **kwargs):
            sent.append(content)
            return "msg_ok"

        adapter.send_message = _record
        mgr.register_adapter(adapter, agent_id="default")

        async def _noSessionSync(*args, **kwargs):
            return None

        mgr._sync_reply_to_session = _noSessionSync

        async def _raisingHandler(message):
            raise RuntimeError("处理器炸了")

        mgr._message_handler = _raisingHandler
        try:
            yield mgr, sent
        finally:
            mgr.unregister_adapter("feishu", agent_id="default")
            ChannelManager._instance = None

    def test_handlerFailureSendsTheNamedConstantCopy(self, manager):
        """处理器炸了 → 用户收到的兜底话就是常量那一句话（行为面咬合）。"""
        from neurova.channels.base import ChannelEventType, ChannelMessage
        from neurova.channels.manager import FALLBACK_ERROR_TEXT

        mgr, sent = manager
        msg = ChannelMessage(channel_type="feishu", message_id="om_g", sender_id="ou_g",
                             sender_name="ou_g", content="触发处理器异常", chat_id="oc_g")
        asyncio.run(mgr._dispatch_message(msg))

        assert FALLBACK_ERROR_TEXT in sent, (
            f"兜底文案没有按常量发出（实得 {sent}）"
        )
