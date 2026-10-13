# -*- coding: utf-8 -*-
"""语音上下文的注入实现只许有一份（§6-174 批 19A · 第 7 条：比-取-接-退）。

复核实状时逐处自己命中的三份并存实现，同一批标签串被抄了三次：

- `neurova/voice_context_module.py:173-232` `inject_metadata()` —— 实现最完整（含语言／引擎／TTS 元数据），
  但它的两个调用点都在**永不可达分支**里：`voice_pipeline.py:174/266` 的 `if self._voice_context_module
  and context_pool:`，而全仓没有任何生产调用点给 `process_asr/process_tts` 传 `context_pool`
  （`context_pool=` 的传参方只有 NeurFlow 那一路）。
- `neurova/context/orchestrator.py:1572-1586`（pool 分支，拼成 `blocks["tooling"]` 文本行）与
  `:1693-1725`（候选池分支，拼成 `ContextInput`）——**这两条才是现役读侧**：`chat_pipeline.py:1667`
  取 `metadata["voice_context"]` → `:1703` 传进 `build_context()`。同一函数里两份拷贝，标签串各写一遍。
- 外加 `orchestrator.py:1697` 一个**构造后即弃**的局部（`voice_module = VoiceContextModule()`，
  全函数再无引用；而它的 `__init__` 会跑 `_init_emotion_analyzer()` 去导入并实例化 EmotionModule）。

还有第 24 项要一并钉住：该模块把最近一次上下文**自持在进程级单例字段**上
（`_current_context`，`@lazySingleton` 的 `get_voice_context_module()`），读口 `get_voice_context()` 与
清理口 `clear_voice_context()`、`reset_voice_context_module()` 全仓零调用——无会话/用户键、无生命周期
终点。这种状态一旦被接上就是跨会话串台，所以它的正确处置是退役，不是找读者。

判据口径沿用 §6-173 那条：本层不做 `inspect.signature().bind` 型契约格（签名带 `**kwargs` 收口时
bind 恒成功＝没牙），这里全部按**定义处唯一**与**真产出行集合**判，并配一格探测器自证。
"""

import ast
import pathlib
import re

from tests import ast_scan

REPO = pathlib.Path(__file__).resolve().parents[3]
NEUROVA = REPO / "neurova"

LABELS = ("语音识别文本:", "识别置信度:", "语音情感:", "语言:", "识别引擎:", "TTS引擎:", "TTS音色:")
STATE_SYMBOLS = ("_current_context", "get_voice_context", "clear_voice_context")


def _pyFiles(root: pathlib.Path):
    """`root` 子树下的 `.py` 清单——枚举走共享解析预算（Issue #148）。

    私有 `rglob` + 别处私有 `ast.parse` 组成「全仓扫描」：判据成本随代码总量涨，
    与其余受保护文件共享机器时撞 30s 墙钟。枚举归 `ast_scan.filesUnder`
    （`SHARED_ENUM_ENTRIES`），解析归 `ast_scan.transientNodes`。
    """
    return iter(ast_scan.filesUnder(root))


class TestInjectionHasOneImplementation:
    """标签串只许出现在选定那一份里（其余两处必须改指它）。"""

    @staticmethod
    def _definersOf(label: str) -> list:
        hits = []
        for path in _pyFiles(NEUROVA):
            text = path.read_text(encoding="utf-8", errors="replace")
            if label in text:
                hits.append(path.relative_to(REPO).as_posix())
        return hits

    def testLabelVocabularyIsDefinedOnce(self):
        offenders = {}
        for label in LABELS:
            definers = self._definersOf(label)
            if len(definers) > 1:
                offenders[label] = definers
        assert offenders == {}, f"同一份语音上下文标签串被多处手抄：{offenders}"

    def testOnlyTheDesignatedSourceDefinesThem(self):
        """收口去向必须是 `voice_context_module`，别处只许调用不许重拼。"""
        for label in LABELS:
            definers = self._definersOf(label)
            assert definers and all("voice_context_module.py" in d for d in definers), (
                f"标签『{label}』的定义处不是唯一实现那份：{definers}")

    def testOrchestratorCallsTheSourceInsteadOfRebuilding(self):
        """现役两条分支都必须改指它——按调用形状判，不按注释判。"""
        src = (NEUROVA / "context" / "orchestrator.py").read_text(encoding="utf-8", errors="replace")
        calls = len(re.findall(r"\bvoiceContextLines\(", src))
        assert calls >= 2, f"orchestrator 里对唯一实现的调用只有 {calls} 处，两条分支没收口"

    def testDeadOneShotConstructionIsGone(self):
        """AST 查『构造 VoiceContextModule 后该名字再无去处』的赋值——今天正中有这一处。

        构造本身有代价：`__init__` 会跑 `_init_emotion_analyzer()` 去导入并实例化 EmotionModule，
        而现役那份根本没用这个实例（注入是内联重拼的）。
        """
        offenders = []
        # 取数走共享解析预算：`VoiceContextModule` 是判据的充分条件——连这个符号
        # 都没出现的文件不可能构造它，故带文本预筛（解析量从代码总量降到命中面）。
        for path, node in ast_scan.transientNodes(
                NEUROVA, hints=ast_scan.textHints("VoiceContextModule")):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not (isinstance(target, ast.Name) and isinstance(node.value, ast.Call)):
                continue
            fname = getattr(node.value.func, "id", "") or getattr(node.value.func, "attr", "")
            if not fname.endswith("VoiceContextModule"):
                continue
            text = ast_scan.sourceCode(path)
            if len(re.findall(rf"\b{re.escape(target.id)}\b", text)) <= 1:
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
        assert offenders == [], f"构造后即弃的实例（每次还白跑一遍情感分析器初始化）：{offenders}"


class TestModuleHoldsNoSessionState:
    """自持状态三符号必须退净——无会话键的进程级"最近一次"是串台入口。

    口径按**归属**收：`_current_context` 这个名字在 `auto_context_module.py` 里是另一回事
    （那是对话窗口的消息列表，同名词不同物），扫全仓符号名会把它的合法使用算成命中——
    这正是本卷"伪命中九类"里"同名词不同物"那一族，判据自己也会犯。
    所以：状态位只看本模块文件；读口/清理口按**调用形状**全仓查（`name(` 且不带后缀）。
    """

    def testStateSymbolsAreGone(self):
        src = (NEUROVA / "voice_context_module.py").read_text(encoding="utf-8", errors="replace")
        left = [s for s in STATE_SYMBOLS if re.search(rf"\b{re.escape(s)}\b", src)]
        assert left == [], f"语音上下文模块仍自持进程级状态：{left}"

    def testNoCallSitesRemainAnywhere(self):
        hits = []
        for path in _pyFiles(NEUROVA):
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in ("get_voice_context", "clear_voice_context"):
                for m in re.finditer(rf"\b{name}\s*\(", text):
                    line = text[:m.start()].count("\n") + 1
                    hits.append(f"{path.relative_to(REPO).as_posix()}:{line}")
        assert hits == [], f"退役读口仍有调用点（接上即串台）：{hits}"


class TestTheSingleSourceProducesRealLines:
    """唯一实现本身的读数：字段齐、格式稳、neutral 不出情感行。"""

    @staticmethod
    def _lines(ctx):
        from neurova.voice_context_module import voiceContextLines

        return voiceContextLines(ctx)

    def testEveryProducedFieldShowsUp(self):
        lines = self._lines({
            "text": "帮我看下明天的排程",
            "confidence": 0.62,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1800,
        })
        joined = "\n".join(lines)
        for fragment in ("帮我看下明天的排程", "0.62", "zh", "funasr"):
            assert fragment in joined, f"唯一实现少了『{fragment}』：{lines}"

    def testTtsMetadataAlsoProducesLines(self):
        joined = "\n".join(self._lines({
            "audio_metadata": {"tts_engine": "moss-nano", "tts_voice": "zh-CN-XiaoxiaoNeural",
                               "audio_size_bytes": 64044},
        }))
        assert "moss-nano" in joined and "zh-CN-XiaoxiaoNeural" in joined

    def testNeutralEmotionProducesNoEmotionLine(self):
        joined = "\n".join(self._lines({"text": "行", "emotion": {"primary_emotion": "neutral",
                                                                  "confidence": 0.4}}))
        assert "语音情感" not in joined, f"neutral 情感被当信息注入了：{joined}"

    def testEmptyContextYieldsNoLines(self):
        assert self._lines({}) == [], "空上下文仍产出行——下游会注入一条空气条目"

    def testDetectorHasTeeth(self):
        """自证：标签串出现在别的文件里必须被上面那格抓到。"""
        fake = REPO / "neurova" / "channels" / "_tmp_probe_marker.py"
        fake.write_text('# x\nA = "语音识别文本: abc"\n', encoding="utf-8")
        try:
            assert "neurova/channels/_tmp_probe_marker.py" in TestInjectionHasOneImplementation._definersOf("语音识别文本:")
        finally:
            fake.unlink()
        assert "neurova/channels/_tmp_probe_marker.py" not in TestInjectionHasOneImplementation._definersOf("语音识别文本:")
