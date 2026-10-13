# -*- coding: utf-8 -*-
"""转写出来的语音元数据要一路到达回合与 prompt（§6-175 批 20 · 写侧接进现役回合）。

复核实状（逐处自己命中）：
- **读侧一直在等一份没人写的 metadata**——`chat_pipeline.py:1667` 取 `ctx.metadata.get("voice_context")`，
  `:1703` 传给 `ContextOrchestrator.build_context()`，再由唯一实现 `voiceContextLines()` 拼进行；
  此前全仓唯一的写者是 `agent_core.py:1183-1226`（`process_multimodal`），而那条路只能经
  `MessageRouter._route_chat` 到达，其入口 `Agent.process_message` 的生产调用点只有
  `evolution/eval/ab_library.py:189` ⇒ 对真用户，这条功能从未生效。
- **渠道这条链上，预检其实正握着这份数据**：`transcribe_voice_message` 成功那一刻，手上就是 ASR 的
  真产物 dict（现役引擎交 `{text, language, duration_sec}`，`confidence`/`engine` 由引擎自报时才有），
  但它只写了 `voice_transcribed`/`voice_transcript` 两个标记，没把这份元数据交给回合。
- 于是本批把写侧接上：**预检写 → `channel_router` 透传进回合 metadata → `chat_pipeline` 读**。

键名收口（教义第 6 条）：`"voice_context"` 这个键此前在读写两侧各是字面量，再加一个写者就是第三份，
故定义处唯一化为 `voice_context_module.VOICE_CONTEXT_KEY`。守卫视**用途**：只把「下标键 / `.get` 的
键实参 / 字典字面量的键位」算作使用——`context/orchestrator.py` 里那句 `metadata={"type": "voice_context"}`
是 ContextInput 的**类型值**，不是这个键，按值扫字符串就会把它误判成第二份定义（本卷"两头失真"那族）。

一处明知没扫到的写侧登记在此不藏：`agent_core.py:1226` 仍是字面量。它受 `agent_core.py` 尺寸棘轮
（基线只降不升）所阻——改引常量要加一行 import，而本批没有正当理由为它减行；那条路本身只活在评测面上，
留待与 `process_multimodal` 拆分同批处理。
"""

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
NEUROVA = REPO / "neurova"

from neurova.channels.base import ChannelMessage  # noqa: E402
from neurova.voice_context_module import VOICE_CONTEXT_KEY  # noqa: E402

from tests import ast_scan  # noqa: E402

# 现役 ASR 引擎的真产物键（funasr/mock 两档一致）——不发明键名
ASR_PRODUCT = {"text": "帮我看下明天的排程", "language": "zh", "duration_sec": 2.4}


def _voiceMessage(metadata=None):
    return ChannelMessage(
        channel_type="feishu", message_id="m_vc", sender_id="ou_vc", sender_name="ou_vc",
        content="[语音]", chat_id="oc_vc", chat_type="p2p", message_type="voice",
        metadata={"audio_bytes": b"WAV-BYTES", **(metadata or {})})


class _CapturingAgent:
    """只替 agent 本体，把生产交给它的 metadata 原样收下来。"""

    def __init__(self, resp=None):
        self.seenMetadata = []
        self.seenInput = []
        self._resp = dict(resp or {"text": "明天上午两点有会"})
        self.config = type("C", (), {"show_thinking": False, "show_tool_messages": False})()
        self.current_reasoning = ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input="", session_id="", metadata=None, **kw):
        self.seenInput.append(user_input)
        self.seenMetadata.append(metadata or {})
        return dict(self._resp)


class TestPrecheckWritesTheVoiceContext:
    """预检成功那一刻是唯一的自然写点——它手上有 ASR 的真产物。"""

    @pytest.mark.asyncio
    async def testTranscribedMessageCarriesAsrProduct(self, monkeypatch):
        from neurova.asr.mock_asr import MockASREngine
        from neurova.channels import voice_precheck

        engine = MockASREngine(transcribe_text=ASR_PRODUCT["text"])
        await engine.initialize()
        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: engine.transcribe)

        out = await voice_precheck.transcribe_voice_message(_voiceMessage())

        ctx = out.metadata.get(VOICE_CONTEXT_KEY)
        assert isinstance(ctx, dict) and ctx, f"预检没写语音上下文：{out.metadata.keys()}"
        assert ctx.get("text") == ASR_PRODUCT["text"]
        assert ctx.get("language") == ASR_PRODUCT["language"]
        # 键按真产物原样带：没跑的字段不凭空造（发明键名会让读侧以为"有这项"）
        assert "duration_sec" in ctx and "confidence" not in ctx, f"写侧造了引擎没交的键：{ctx}"

    @pytest.mark.asyncio
    async def testFailedTranscriptionWritesNoVoiceContext(self, monkeypatch):
        """ASR 失败/空结果时不得留下半份上下文——下游会读到一条空语音信息。"""
        from neurova.channels import voice_precheck

        async def _empty(_data):
            return {"text": "", "error": "no speech"}

        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: _empty)
        out = await voice_precheck.transcribe_voice_message(_voiceMessage())

        assert VOICE_CONTEXT_KEY not in out.metadata
        assert out.metadata.get("voice_transcribe_failed"), "失败也没标降级原因"


class TestRouterHandsItToTheTurn:
    """渠道路由必须把它交给回合，否则读侧永远等不到。"""

    @staticmethod
    def _manager():
        from neurova.channels.manager import ChannelManager

        ChannelManager._instance = None
        return ChannelManager()

    @pytest.mark.asyncio
    async def testVoiceContextReachesAgentChatMetadata(self):
        from neurova.channels.channel_router import make_handler

        mgr = self._manager()
        agent = _CapturingAgent()
        handler = make_handler(mgr, lambda _aid: agent)
        msg = _voiceMessage({VOICE_CONTEXT_KEY: dict(ASR_PRODUCT)})

        await handler(msg)

        assert agent.seenMetadata, "回合没被调用"
        handed = agent.seenMetadata[0].get(VOICE_CONTEXT_KEY)
        assert handed == ASR_PRODUCT, f"路由没把语音上下文交给回合：{handed!r}"

    @pytest.mark.asyncio
    async def testTextTurnIsNotStainedWithVoiceContext(self):
        from neurova.channels.channel_router import make_handler

        mgr = self._manager()
        agent = _CapturingAgent()
        textMsg = ChannelMessage(
            channel_type="feishu", message_id="m_txt", sender_id="ou_vc", sender_name="ou_vc",
            content="就是文字", chat_id="oc_vc", chat_type="p2p", message_type="text", metadata={})

        await make_handler(mgr, lambda _aid: agent)(textMsg)

        assert agent.seenMetadata and VOICE_CONTEXT_KEY not in agent.seenMetadata[0], (
            "文字回合被塞了语音上下文（会是上一轮残留）")


class TestKeyVocabularyIsDefinedOnce:
    """读写两侧共用一处定义的键名；按用途判，不按字符串包含判。"""

    @staticmethod
    def _keySites(src: str) -> list:
        """只数「键位」用法：`x["voice_context"]`、`x.get("voice_context")`、`{"voice_context": ...}`。

        `ast.Key` 不是 walk 得到的节点（字典键要按 `ast.Dict` 的 `keys` 槽看），第一版按它判
        直接 AttributeError；而按值扫会把 `{"type": "voice_context"}` 这种**取值**位置也算成
        第二份定义——那是假红，会把人逼成绕开判据。
        """
        tree = ast.parse(src)
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and node.slice.value == VOICE_CONTEXT_KEY:
                hits.append(node.lineno)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value == VOICE_CONTEXT_KEY:
                    hits.append(node.lineno)
            elif isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value == VOICE_CONTEXT_KEY:
                        hits.append(node.lineno)
        return hits

    @classmethod
    def _keySitesIn(cls, path: pathlib.Path) -> list:
        return cls._keySites(path.read_text(encoding="utf-8", errors="replace"))

    #: 明知还没收口的写侧，逐名登记并配一格"过期即红"（见本文件 docstring 末段：
    #: `agent_core.py` 有尺寸棘轮，改引常量要加一行 import，本批没有正当减行理由；
    #: 且那条路本身只活在评测面上）。加文件进来必须同时写清为什么。
    EXEMPT = {"neurova/agent_core.py"}

    def _offenders(self, includeExempt: bool = False):
        """把键名当字面量又用了一次的文件清单。

        取数走共享解析预算 `tests/ast_scan`（Issue #148）：私有 `rglob + ast.parse`
        把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟。
        文本预筛取键名本身——连这个串都没出现的文件不可能命中。
        """
        bad = []
        for ref in ast_scan.sourceRefsUnder(
                NEUROVA, hints=ast_scan.textHints(VOICE_CONTEXT_KEY)):
            rel = ref.path.relative_to(REPO).as_posix()
            if rel == "neurova/voice_context_module.py":
                continue
            if not includeExempt and rel in self.EXEMPT:
                continue
            sites = self._keySites(ref.code)
            if sites:
                bad.append(f"{rel}:{sites}")
        return bad

    def testNoSiteRestatesTheKeyLiteral(self):
        offenders = self._offenders()
        assert offenders == [], (
            f"语音上下文键名被当字面量第二次使用（该引 voice_context_module.VOICE_CONTEXT_KEY）：{offenders}")

    def testExemptionsAreStillNeeded(self):
        """登记在案≠永久豁免：哪处已经收口了，就得从豁免名单里划掉。"""
        stillNeeded = set()
        for rel in self.EXEMPT:
            path = REPO / rel
            if path.is_file() and self._keySitesIn(path):
                stillNeeded.add(rel)
        stale = self.EXEMPT - stillNeeded
        assert stale == set(), f"这些豁免项已经不再需要，划掉它：{sorted(stale)}"

    def testValuePositionIsNotMistakenForAKeyUse(self):
        """反向对照：`metadata={"type": "voice_context"}` 是 ContextInput 的类型值，不是键——
        把它算成命中，守卫就会一边假红一边逼人把代码改成绕开判据。"""
        src = (NEUROVA / "context" / "orchestrator.py").read_text(encoding="utf-8", errors="replace")
        assert '"type": "voice_context"' in src, "锚定形状变了，先修这格"
        assert not self._keySitesIn(NEUROVA / "context" / "orchestrator.py"), (
            "orchestrator 里出现了键位使用——那才是真该收口的地方")

    def testDetectorHasTeeth(self):
        """自证：三种键位写法都要被抓到；取值位置不得被抓。"""
        sample = (
            'd = m.get("voice_context")\n'          # 读：.get 键实参
            'e = {}\ne["voice_context"] = 1\n'      # 写：下标键
            'g = {"voice_context": {}}\n'           # 写：字典字面量的键位
            'f = {"type": "voice_context"}\n'       # 取值位置——不是本键，不得算命中
        )
        sites = self._keySites(sample)
        assert sorted(sites) == [1, 3, 4], f"键位/取值用法没分干净：{sites}"


class TestTheWholeSeamIsOnePiece:
    """预检 → 路由 → 读侧键名同源：三处若各改各的，症状是 prompt 少一项而不是报错。"""

    @pytest.mark.asyncio
    async def testPrecheckOutputIsWhatPipelineReads(self, monkeypatch):
        """写侧与读侧必须引同一个常量——两侧各写一次字面量时，改名字的症状只是 prompt 少一项。"""
        from neurova.channels import voice_precheck

        async def _tr(_data):
            return dict(ASR_PRODUCT)

        monkeypatch.setattr(voice_precheck, "_get_asr_transcriber", lambda: _tr)
        out = await voice_precheck.transcribe_voice_message(_voiceMessage())
        assert VOICE_CONTEXT_KEY in out.metadata, "运行时没写下这份上下文"

        precheckSrc = (NEUROVA / "channels" / "voice_precheck.py").read_text(encoding="utf-8", errors="replace")
        pipelineSrc = (NEUROVA / "agent" / "chat_pipeline.py").read_bytes().decode("utf-8", errors="replace")
        assert re.search(r"metadata\[VOICE_CONTEXT_KEY\]", precheckSrc), "写侧不是通过常量写的"
        assert re.search(r"ctx\.metadata\.get\(\s*VOICE_CONTEXT_KEY\s*\)", pipelineSrc), "读侧不是通过常量读的"
        for src, where in ((precheckSrc, "voice_precheck"), (pipelineSrc, "chat_pipeline")):
            assert re.search(r"from neurova\.voice_context_module import [^\n]*VOICE_CONTEXT_KEY", src), (
                f"{where} 没引唯一定义的键名")
