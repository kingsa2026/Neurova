"""
TTS lazy_release 默认值解析测试

背景（启动性能 2026-09-09）：moss-nano 启动同步加载 + 预热推理实测 17.5s，
是后端启动 48s 中的最大单项。H2-C 已实现 lazy_release 模式（启动跳过引擎
加载，首次合成时 _ensure_ready 按需初始化），但默认关。本批将默认值翻转为开，
env NEUROVA_TTS_LAZY_RELEASE 保持部署级显式开关优先。
"""
import os

import pytest

from neurova.api.app import _resolve_tts_lazy_release


class TestResolveTtsLazyRelease:
    def test_default_on_when_unset(self):
        """默认开：不再同步加载 TTS 引擎"""
        assert _resolve_tts_lazy_release("", None) is True

    def test_default_on_when_config_key_absent(self):
        """调用点 config.get(key) 缺键返回 None → 默认开"""
        assert _resolve_tts_lazy_release("", None) is True

    def test_env_empty_after_strip_treated_as_unset(self):
        assert _resolve_tts_lazy_release("   ", None) is True

    def test_env_off_wins_over_default(self):
        """NEUROVA_TTS_LAZY_RELEASE=0 显式关闭（部署级逃生口）"""
        assert _resolve_tts_lazy_release("0", None) is False

    def test_env_off_wins_over_config_true(self):
        assert _resolve_tts_lazy_release("0", True) is False

    def test_env_on_wins_over_config_false(self):
        assert _resolve_tts_lazy_release("1", False) is True

    def test_env_whitespace_tolerant(self):
        assert _resolve_tts_lazy_release(" 0 ", True) is False
        assert _resolve_tts_lazy_release(" 1 ", False) is True

    def test_config_key_can_turn_off_when_env_unset(self):
        assert _resolve_tts_lazy_release("", False) is False

    def test_config_key_true_when_env_unset(self):
        assert _resolve_tts_lazy_release("", True) is True
