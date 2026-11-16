# -*- coding: utf-8 -*-
"""语音管线依赖装配失败必须留 WARNING 级线索（审计 3.2-15，2026-11-17）：

四个依赖（VoiceContextModule/VoiceMemoryBridge/ASRManager/TTSManager）装配
失败原实现只 `logger.debug`——语音链路静默失能时启动日志零线索，事后归因
全靠猜。fail-soft 语义保持（装配失败不阻断主流程），但失能必须可见。
"""

from __future__ import annotations

import logging

import pytest

from neurova.voice_pipeline import UnifiedVoicePipeline


@pytest.fixture
def broken_imports(monkeypatch):
    """让四个依赖的 import 全部炸——模拟缺依赖/坏装配。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("neurova.voice_context_module") or name.startswith(
            "neurova.voice_memory_bridge"
        ) or name.startswith("neurova.asr") or name.startswith("neurova.tts"):
            raise ImportError(f"模拟缺依赖: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TestAssemblyFailureHonest:
    def test_assembly_failure_logs_warning(self, broken_imports, caplog):
        pipeline = UnifiedVoicePipeline()
        with caplog.at_level(logging.WARNING, logger="neurova.voice_pipeline"):
            pipeline._ensure_initialized()

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "装配失败必须留下 WARNING 级启动读数（原只有 debug 零线索）"
        joined = " ".join(r.getMessage() for r in warnings)
        for component in ("VoiceContextModule", "VoiceMemoryBridge", "ASRManager", "TTSManager"):
            assert component in joined, f"失能清单必须点名 {component}"

    def test_fail_soft_semantics_kept(self, broken_imports):
        """装配失败不抛——主流程 fail-soft 保持。"""
        pipeline = UnifiedVoicePipeline()
        pipeline._ensure_initialized()
        assert pipeline._voice_context_module is None
        assert pipeline._voice_memory_bridge is None
        assert pipeline._asr_manager is None
        assert pipeline._tts_manager is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
