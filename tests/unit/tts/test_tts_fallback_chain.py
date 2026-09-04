# -*- coding: utf-8 -*-
"""P1-12 TTS 有序 fallback 表配置化（OpenClaw autoSelectOrder 启发）— TDD 测试

锁定：
1. TTSConfig.fallback_chain 显式有序表 → 管理器按表顺序初始化/fallback；
2. 非法引擎名被过滤（注册表闭集），全非法时回退默认链；
3. 默认不传 → 行为与模块常量 FALLBACK_CHAIN 完全一致（等价性）；
4. 管理器暴露 effective fallback 链（前端语音设置页展示依赖）。
"""
import pytest

from neurova.tts import manager as tts_manager_mod
from neurova.tts.manager import FALLBACK_CHAIN, TTSConfig, TTSManager


class TestFallbackChainConfig:
    """有序 fallback 表"""

    def test_config_default_none(self):
        cfg = TTSConfig()
        assert cfg.fallback_chain is None

    def test_default_chain_equivalence(self):
        """不配置 → 等价默认链"""
        mgr = TTSManager(TTSConfig())
        assert mgr.fallback_chain == FALLBACK_CHAIN

    def test_custom_chain_order_respected(self):
        """显式链顺序生效（mock 优先于 moss-nano）"""
        cfg = TTSConfig(fallback_chain=["mock", "moss-nano"])
        mgr = TTSManager(cfg)
        assert mgr.fallback_chain == ["mock", "moss-nano"]

    def test_unknown_engines_filtered(self):
        """未知引擎名过滤（注册表闭集），合法项保留"""
        cfg = TTSConfig(fallback_chain=["bogus-engine", "mock", "nope"])
        mgr = TTSManager(cfg)
        assert mgr.fallback_chain == ["mock"]

    def test_all_invalid_falls_back_to_default(self):
        """全非法 → 回退默认链（fail-safe，不禁用 TTS）"""
        cfg = TTSConfig(fallback_chain=["bogus1", "bogus2"])
        mgr = TTSManager(cfg)
        assert mgr.fallback_chain == FALLBACK_CHAIN

    def test_initialize_respects_custom_chain(self):
        """auto 模式初始化按自定义链顺序尝试"""
        import asyncio

        cfg = TTSConfig(engine="auto", fallback_chain=["mock"])
        mgr = TTSManager(cfg)
        ok = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(mgr.initialize())
        assert ok is True
        assert mgr.engine_name == "mock"

    def test_chain_deduplicated(self):
        """重复引擎去重，保序"""
        cfg = TTSConfig(fallback_chain=["mock", "mock", "edge-tts"])
        mgr = TTSManager(cfg)
        assert mgr.fallback_chain == ["mock", "edge-tts"]
