# -*- coding: utf-8 -*-
"""2026-09-08 审计修复⑧：TTS 引擎流式 kwargs 宽契约。

/synthesize-stream 端点恒传 voice/speed（audio.py:321 无 try 直调）。
sapi5/mock/base 的 synthesize_stream(self, text) 签名无 **kwargs →
调用点 TypeError → 500（绕过 fallback/502 语义）。
根修复=引擎签名对齐宽契约（与 moss/edge 同构：**kwargs 收编语义参数）。
"""

import inspect

import pytest


class TestStreamKwargsWideContract:
    """所有 TTS 引擎的 synthesize_stream 必须接受任意语义 kwargs。"""

    @pytest.mark.parametrize(
        "cls_path",
        [
            "neurova.tts.base:TTSBase",
            "neurova.tts.sapi5_tts:SAPI5TTS",
            "neurova.tts.mock_tts_simple:MockTTSSimple",
            "neurova.tts.moss_nano:MOSSNanTTS",
            "neurova.tts.edge_tts:EdgeTTS",
        ],
    )
    def test_synthesize_stream_accepts_kwargs(self, cls_path):
        mod_name, cls_name = cls_path.split(":")
        import importlib

        cls = getattr(importlib.import_module(mod_name), cls_name)
        sig = inspect.signature(cls.synthesize_stream)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        assert has_var_keyword, (
            f"{cls_path}.synthesize_stream 缺 **kwargs——端点直传 voice/speed 时 TypeError 500"
        )

    def test_mock_engine_stream_survives_semantic_kwargs(self):
        """绑定级验证：mock 引擎带 voice/speed 调用不抛 TypeError（可实例化引擎）。"""
        from neurova.tts.mock_tts_simple import MockTTSSimple

        engine = MockTTSSimple()
        gen = engine.synthesize_stream("你好", voice="zh-CN-XiaoxiaoNeural", speed=1.2)
        # 绑定成功即可（未初始化引擎首帧即返回，不消费）
        assert gen is not None
