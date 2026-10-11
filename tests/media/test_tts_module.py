"""
TTS 模块单元测试

测试 TTS 基类、EdgeTTS、MOSSNanTTS、MockTTSSimple 和 TTSManager。
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import io

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.moss_nano import MOSSNanTTS
from neurova.tts.mock_tts_simple import MockTTSSimple
from neurova.tts.manager import TTSManager, TTSConfig


class TestTTSBase:
    """测试 TTS 基类"""

    def test_abstract_methods(self):
        """测试抽象方法"""
        # TTSBase 是抽象类，不能直接实例化
        with pytest.raises(TypeError):
            TTSBase()

    def test_concrete_tts(self):
        """测试具体 TTS 实现"""

        class TestTTS(TTSBase):
            async def initialize(self):
                return True

            async def synthesize(self, text: str) -> bytes:
                return b"test audio"

            async def synthesize_stream(self, text: str):
                yield b"chunk1"
                yield b"chunk2"

            async def shutdown(self):
                pass

        tts = TestTTS()
        assert not tts.is_initialized


class TestEdgeTTS:
    """测试 EdgeTTS"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """测试初始化"""
        tts = EdgeTTS()
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            result = await tts.initialize()
            assert result is True
            assert tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        tts = EdgeTTS()
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await tts.initialize()

            # 模拟 Communicate 类
            mock_communicate = MagicMock()
            mock_communicate.stream = AsyncMock(return_value=iter([
                {"type": "audio", "data": b"audio data"},
            ]))
            
            with patch("edge_tts.Communicate", return_value=mock_communicate):
                audio = await tts.synthesize("测试文本")
                assert isinstance(audio, bytes)

    @pytest.mark.asyncio
    async def test_list_voices(self):
        """列出音色：替身必须按真库的**协程**契约给，否则生产侧 `await` 会炸。

        首稿写成 `patch("edge_tts.list_voices", return_value=[...])`——那把库函数换成了返回
        普通 list 的同步函数，`edge_tts.py:248` 的 `await` 立刻抛
        「object list can't be used in 'await' expression」，被外层 `except Exception` 吞掉后
        返回 []，于是这格常年红且红得像"功能坏了"。实测
        `inspect.iscoroutinefunction(edge_tts.list_voices)` 为 True ⇒ 错在替身，不在被测端。
        """
        tts = EdgeTTS()
        voices = [
            {"Name": "zh-CN-XiaoxiaoNeural", "Gender": "Female"},
            {"Name": "zh-CN-YunxiNeural", "Gender": "Male"},
        ]
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await tts.initialize()
            with patch("edge_tts.list_voices", new=AsyncMock(return_value=voices)):
                got = await tts.list_voices()
                assert len(got) == 2
                assert got[0]["Name"] == "zh-CN-XiaoxiaoNeural"

    @pytest.mark.asyncio
    async def test_listVoicesSwallowsLibraryFailureButSaysSo(self):
        """库层失败必须被记成 error 并诚实回空表——静默回 [] 而不留一句日志，
        调用方就分不清"没有音色"与"音色查询挂了"。"""
        tts = EdgeTTS()
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await tts.initialize()
            with patch("edge_tts.list_voices", new=AsyncMock(side_effect=OSError("net down"))), \
                    patch.object(tts._logger, "error") as err:
                assert await tts.list_voices() == []
                assert err.called, "取音色失败却只字不记——这是一次被抹平的故障"


class TestMOSSNanTTS:
    """测试 MOSSNanTTS"""

    @pytest.mark.asyncio
    async def test_initializeWithoutModelFilesDegradesHonestly(self):
        """模型不在本机 ⇒ 初始化必须回 False、不抛、且不得留下"已初始化"的假状态。

        首稿是这样测的：`patch("pathlib.Path.exists", return_value=True)` ＋ 把 onnxruntime
        换成 MagicMock，然后断 `initialize() is True`。两处都是错的：
        ① 契约错——`moss_nano.py` 的 initialize 要过清单校验、manifest 加载、四张 ONNX 图，
           只把 `Path.exists` 全量改成 True 到不了 True 分支，于是常年红；
        ② **危险**——把"文件都在"这种假象强灌进去，会让生产代码真去
           `ort.InferenceSession(<不存在的路径>)`；在装了真 onnxruntime 的机器上这不是抛
           Python 异常，而是**原生 access violation 直接带走整个 pytest 进程**
           （新建 worktree 里跑宽域 A/B 时实测打断过一整轮 `tests/media`，见台账 §6-142）。
        所以这里改测真正能保证的那件事：缺件即诚实不可用。
        """
        tts = MOSSNanTTS(model_dir=str(Path("no-such-moss-dir")), auto_download=False)
        result = await tts.initialize()
        assert result is False, "模型不在却报初始化成功"
        assert not tts.is_initialized, "初始化失败仍标成已就绪——调用方会拿它去合成"

    @pytest.mark.asyncio
    async def test_initializeWithoutOnnxRuntimeFailsSoftNotCrash(self):
        """可选重型依赖 onnxruntime 缺失：必须 fail-soft 回 False，而不是把 ImportError 抛给调用方。

        用 `sys.modules['onnxruntime'] = None` 触发 ImportError 是标准做法（比把整库换成
        MagicMock 更接近真缺失，也不会让后面的真 `InferenceSession` 调用骗过检查）。
        """
        tts = MOSSNanTTS(model_dir=str(Path("no-such-moss-dir")), auto_download=False)
        with patch.dict(sys.modules, {"onnxruntime": None}):
            assert await tts.initialize() is False
            assert not tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesizeWhileUninitializedReturnsEmptyAndSaysSo(self):
        """未初始化就合成 ⇒ 回空字节并记 error，不崩、不抛给调用方。

        替掉的旧格长这样：`patch("pathlib.Path.exists", return_value=True)` ＋ 把 onnxruntime
        换 MagicMock ＋ 再 `patch("onnxruntime.InferenceSession")`，断"返回 bytes"。三处问题：
        ① 全局改 `Path.exists` 会让被测代码以为模型齐全，进而真去加载原生会话——本机装了
           onnxruntime 时这不是抛 Python 异常，是**原生崩溃带走整轮 pytest**（宽域 A/B 实测）；
        ② 断言"是 bytes"对空字节也成立，永远红不了；③ 全程没断过"未就绪要可见"这件事。
        真合成的成功路径要真模型，属活体面（本仓不在单测里模拟原生推理库）。
        """
        tts = MOSSNanTTS(model_dir=str(Path("no-such-moss-dir")), auto_download=False)
        assert await tts.initialize() is False
        out = await tts.synthesize("你好")
        assert out == b"", f"未就绪却给出看似可用的音频：{out!r}"


class TestMockTTSSimple:
    """测试 MockTTSSimple"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """测试初始化"""
        tts = MockTTSSimple()
        result = await tts.initialize()
        assert result is True
        assert tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        tts = MockTTSSimple()
        await tts.initialize()

        audio = await tts.synthesize("测试文本")
        assert isinstance(audio, bytes)
        # MockTTS 应该生成有效的 WAV 数据
        assert audio[:4] == b'RIFF'  # WAV 文件头

    @pytest.mark.asyncio
    async def test_synthesize_stream(self):
        """测试流式语音合成"""
        tts = MockTTSSimple()
        await tts.initialize()

        chunks = []
        async for chunk in tts.synthesize_stream("测试文本"):
            chunks.append(chunk)

        assert len(chunks) > 0
        # 合并所有 chunk 应该是有效的 WAV 数据
        audio = b"".join(chunks)
        assert audio[:4] == b'RIFF'


class TestTTSConfig:
    """测试 TTSConfig"""

    def test_default_config(self):
        """默认引擎是 `auto`（P1-12 有序回退链），不是某个具体引擎。

        旧期望写的是 `"edge-tts"`——那是有回退链之前的默认值，改契约时没同步这格，
        于是它常年红（`assert 'auto' == 'edge-tts'`）。这里同时钉住"默认值只能是清单里的
        一个"，避免下次改默认时又只改一侧。
        """
        config = TTSConfig()
        assert config.engine == "auto"
        assert config.voice == "zh-CN-XiaoxiaoNeural"
        assert config.rate == "+0%"
        assert config.volume == "+0%"
        assert config.fallback_enabled is True, "默认就该带有序回退链"

    def test_custom_config(self):
        """测试自定义配置"""
        config = TTSConfig(
            engine="moss-nano",
            voice="custom_voice",
            rate="+10%",
            volume="-20%",
        )
        assert config.engine == "moss-nano"
        assert config.voice == "custom_voice"
        assert config.rate == "+10%"
        assert config.volume == "-20%"


class TestTTSManager:
    """测试 TTSManager"""

    @pytest.mark.asyncio
    async def test_initialize_edge_tts(self):
        """测试初始化 EdgeTTS"""
        manager = TTSManager(TTSConfig(engine="edge-tts"))
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await manager.initialize()
            assert manager.is_initialized

    @pytest.mark.asyncio
    async def test_initialize_mock_tts(self):
        """测试初始化 MockTTS"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()
        assert manager.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()

        audio = await manager.synthesize("测试文本")
        assert isinstance(audio, bytes)
        assert len(audio) > 0

    @pytest.mark.asyncio
    async def test_synthesize_stream(self):
        """测试流式语音合成"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()

        chunks = []
        async for chunk in manager.synthesize_stream("测试文本"):
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_list_voices(self):
        """管理器透传引擎的音色表——替身同样必须按协程契约给（同 `TestEdgeTTS` 那格的教训）。"""
        manager = TTSManager(TTSConfig(engine="edge-tts"))
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await manager.initialize()
            with patch("edge_tts.list_voices", new=AsyncMock(
                    return_value=[{"Name": "zh-CN-XiaoxiaoNeural", "Gender": "Female"}])):
                voices = await manager.list_voices()
                assert len(voices) == 1, f"音色表被吞成空：{voices}"

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """测试关闭"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()
        await manager.shutdown()
        assert not manager.is_initialized


class TestAutoFallbackChain:
    """`auto` 那条链的实质判据（替掉 `tests/media/test_tts_init.py` 等三份从不真跑的脚本）。

    那三份是 `#!/usr/bin/env python3` ＋ `try/except: print` 的手工冒烟脚本，顶着 `test_` 名字
    放在 `tests/media/` 下：pytest 9 的 asyncio STRICT 模式对未标记的协程用例直接判
    「async def functions are not natively supported」⇒ **它们一次都没跑过**；即便跑起来，
    脚本自己把异常吞成 print，永远不可能红。本档把它想表达的那件事（auto 最终要有可用引擎、
    且失败要可见）改成两条真会咬的断言——**不碰外网、不碰真模型**。
    """

    # 显式给链，别按平台默认链断言：Windows 上 sapi5 真能起来，会把"应落到 mock"这种
    # 期望变成一条与平台绑死的假红（首稿就是这么写的，实得 sapi5）。
    _CHAIN = ["edge-tts", "moss-nano", "mock"]

    @pytest.mark.asyncio
    async def test_autoLandsOnTheLastResortEngineWhenOthersAreUnavailable(self):
        async def _fail(self):
            return False

        with patch.object(EdgeTTS, "initialize", _fail), \
                patch.object(MOSSNanTTS, "initialize", _fail):
            manager = TTSManager(TTSConfig(engine="auto", fallback_chain=list(self._CHAIN)))
            assert await manager.initialize() is True, "auto 链全灭却不报错也不落到兜底引擎"
            assert manager.engine_name in manager.fallback_chain, \
                f"选中的引擎不在声明的链上：{manager.engine_name}"
            assert manager.engine_name == "mock", (
                f"链上 edge/moss 都不可用时应落到兜底 mock，实得 {manager.engine_name}")
            await manager.shutdown()

    @pytest.mark.asyncio
    async def test_everyEngineFailingIsReportedNotSwallowed(self):
        """链上一律失败 ⇒ 回 False 并记 error；不得"初始化失败仍 is_initialized"。"""
        async def _fail(self):
            return False

        with patch.object(EdgeTTS, "initialize", _fail), \
                patch.object(MOSSNanTTS, "initialize", _fail), \
                patch.object(MockTTSSimple, "initialize", _fail), \
                patch("neurova.tts.manager.logger") as log:
            manager = TTSManager(TTSConfig(engine="auto", fallback_chain=list(self._CHAIN)))
            assert await manager.initialize() is False
            assert not manager.is_initialized
            assert log.error.called, "全链失败被静默吞掉——调用方会拿一个没就绪的引擎去合成"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])