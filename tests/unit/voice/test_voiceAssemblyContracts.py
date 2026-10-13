# -*- coding: utf-8 -*-
"""语音装配层的三条契约（批 18 · 形状格退役后的替代证据）。

为什么不是"把 hasattr 换成另一种 hasattr"：本目录此前有 14 格只断形状——
`assert X is not None`（import 失败只会 error，永远不会 fail）、`hasattr/callable` 成串、
以及两处跨文件重复的 `_channel_voice` 形状格。它们给的安心是假的。

也不能改成 `inspect.signature().bind(...)`：本层生产签名一律以 `**kwargs` 收口
（`UnifiedVoicePipeline.process_asr/process_tts`、`ASRManager.transcribe`、`TTSManager.synthesize`），
bind 对 catch-all 签名**恒成功**，那样造出来的格子常年全绿——比 hasattr 更坏，因为它看着像契约。
所以这里改问"被读的那一侧到底读到了什么"：

- 端点按属性名读 `VoiceResult`，属性名漂了就是运行时 `AttributeError` ⇒ 用真 dataclass 字段集
  合对真源码的属性读数取差集（`test_fieldNamesReadByEndpointsExist`）；
- 预转写按 `"text"` 读 ASR 返回的 dict，ASR 层改键名就变成"转写成功但空文本"（静默降级）
  ⇒ 用**真引擎产物的键集合**去覆盖**真源码里的读键集合**（`test_asrReturnKeysFeedReaders`）；
- `_channel_voice` 是记忆召回的一路通道，形状格只说"有这个方法" ⇒ 改成行为格：
  只回语音转写类记忆、按置信度×0.7＋时间衰减×0.3 排序、空库回空列表而不是抛
  （`TestChannelVoiceRecallBehavior`）。

三格都带反向对照（探测器自证），否则"X 不该出现"这种断言在功能缺失时会自动成立。
"""

import ast
import asyncio
import dataclasses
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]


def _attrReadsOn(path: pathlib.Path, varName: str, attrPrefix: str = "") -> set:
    """收集生产源码里 `varName.<attr>` 的属性读数（不是字符串包含，按 AST 形态判）。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == varName:
                found.add(attrPrefix + node.attr)
    return found


def _dictKeysReadBy(path: pathlib.Path, varName: str) -> set:
    """收集 `varName.get("字面键")` 的键名。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == varName:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
    return found


class TestCrossModuleFieldContracts:
    """生产读数与真产物形状必须逐字对得上——漂了就是在运行期炸。"""

    def testFieldNamesReadByEndpointsExist(self):
        from neurova.voice_engine import VoiceResult

        realFields = {f.name for f in dataclasses.fields(VoiceResult)}
        endpoint = REPO / "neurova" / "api" / "endpoints" / "audio.py"
        reads = _attrReadsOn(endpoint, "result")
        assert reads, "端点里没读到 result.* 属性——本格的口径已经失效，先修探测器"
        drift = reads - realFields - {"get"}
        assert drift == set(), (
            f"端点按这些名字读 VoiceResult，而真产物没有它们：{sorted(drift)}｜真字段={sorted(realFields)}")

    def testDetectorHasTeethForFieldDrift(self):
        """自证：真改一个不存在的键名，探测器必须报出来（否则上面那格是空转）。"""
        sample = "def f():\n    return result.notARealField and result.audio_data\n"
        tree = ast.parse(sample)
        read = {n.attr for n in ast.walk(tree)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "result"}
        assert "notARealField" in read

    def testAsrReturnKeysFeedReaders(self):
        """ASR 真产物键 ⊇ 各处读键：漂一个键，渠道语音就变成"转写成功、内容为空"。"""
        from neurova.asr.mock_asr import MockASREngine

        engine = MockASREngine(transcribe_text="明天有会")
        asyncio.run(engine.initialize())
        produced = asyncio.run(engine.transcribe(b"WAVBYTES"))
        assert isinstance(produced, dict) and produced, "MockASREngine 没返回非空 dict，口径变了"

        readers = _dictKeysReadBy(REPO / "neurova" / "channels" / "voice_precheck.py", "result")
        assert readers, "预检没读 ASR 结果的任何键——探测器失明，先修它"
        missing = readers - set(produced)
        assert missing == set(), (
            f"预检要读这些键，而 ASR 层真产物里没有：{sorted(missing)}｜真产物键={sorted(produced)}")

    def testDetectorHasTeethForKeyDrift(self):
        sample = 'def f():\n    return result.get("text") or result.get("ghost_key")\n'
        tree = ast.parse(sample)
        got = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "result" and node.args:
                got.add(node.args[0].value)
        assert got == {"text", "ghost_key"}


class TestChannelVoiceRecallBehavior:
    """`_channel_voice` 的行为：只回语音转写类记忆，且排序口径可查。"""

    @staticmethod
    def _engineWith(memories):
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        class _Store:
            def get_all_memories(self):
                return list(memories)

        return NeurovaRecallEngine(memory_manager=_Store())

    def testOnlyTranscriptionMemoriesComeBack(self):
        engine = self._engineWith([
            {"id": "v1", "memory_type": "asr_transcription", "content": "明天有例会",
             "timestamp": "2026-10-13T00:00:00", "metadata": {"record": {"confidence": 0.9,
                                                                          "engine": "funasr"}}},
            {"id": "t1", "memory_type": "text", "content": "明天有例会（打字记的）",
             "timestamp": "2026-10-13T00:00:00", "metadata": {}},
            {"id": "v2", "memory_type": "asr_transcription", "content": "完全不同的内容",
             "timestamp": "2026-10-13T00:00:00", "metadata": {"record": {"confidence": 0.8}}},
        ])

        out = engine._channel_voice("明天有例会", 5)

        assert [m.memory_id for m in out] == ["v1"], (
            f"语音通道回的不只是命中的转写记忆：{[(m.memory_id, m.content) for m in out]}")

    def testScoresUseConfidenceAndRecency(self):
        """分数口径：confidence×0.7 + 时间衰减×0.3（不是硬编码 1.0——BUG-12 那次修的形）。"""
        engine = self._engineWith([
            {"id": "hi", "memory_type": "asr_transcription", "content": "开会",
             "timestamp": "2026-10-13T09:00:00", "metadata": {"record": {"confidence": 0.99}}},
            {"id": "lo", "memory_type": "asr_transcription", "content": "开会",
             "timestamp": "2020-01-01T00:00:00", "metadata": {"record": {"confidence": 0.40}}},
        ])

        out = engine._channel_voice("开会", 5)

        assert [m.memory_id for m in out] == ["hi", "lo"], f"排序没按分数取：{[m.memory_id for m in out]}"
        assert out[0].score > out[1].score
        assert out[0].metadata["confidence"] == 0.99

    def testEmptyStoreAndMissingManagerReturnEmptyList(self):
        assert self._engineWith([])._channel_voice("任何", 5) == []
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        assert NeurovaRecallEngine()._channel_voice("任何", 5) == []

    def testLimitIsRespected(self):
        memories = [
            {"id": f"v{i}", "memory_type": "asr_transcription", "content": "同一话题",
             "timestamp": "2026-10-13T09:00:00", "metadata": {"record": {"confidence": 0.5 + i / 100}}}
            for i in range(6)
        ]
        out = self._engineWith(memories)._channel_voice("同一话题", 3)
        assert len(out) == 3, f"limit 没生效：{len(out)}"
