"""L-18 回归测试：clamp_max_tokens 容忍 None + 截断告警（不刷屏）。

红绿：无修复时 clamp_max_tokens(None, model) 在 min(None, ...) 处抛
TypeError（调用方 llm_client.py 直接透传 config.max_tokens=None）；
未知模型 4096 上限静默截断。断言：None 回落 DEFAULT_MAX_TOKENS 语义、
截断发生时告警且按模型去重、未截断不告警。

2026-10-21 政策收口：DEFAULT_MAX_TOKENS 是「没配置时用什么」，不是「未知模型
最多能输出多少」；未知模型的显式值只受全局 MAX_MAX_TOKENS 约束。
"""

import pytest

import neurova.llm.model_limits as ml


@pytest.fixture(autouse=True)
def _reset_warned(monkeypatch):
    ml._clamp_warned_models.clear()
    ml.clear_persisted_output_limits()
    yield
    ml._clamp_warned_models.clear()
    ml.clear_persisted_output_limits()


class _WarningRecorder:
    def __init__(self):
        self.msgs = []

    def warning(self, msg, *args):
        self.msgs.append(msg % args if args else msg)

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


@pytest.fixture
def recorder(monkeypatch):
    rec = _WarningRecorder()
    monkeypatch.setattr(ml, "logger", rec)
    return rec


class TestL18NoneTolerant:
    def test_none_with_known_model_falls_back_to_default(self):
        """max_tokens=None 不抛 TypeError，按 DEFAULT_MAX_TOKENS 参与夹紧。"""
        assert ml.clamp_max_tokens(None, "gpt-4o") == ml.DEFAULT_MAX_TOKENS

    def test_none_with_unknown_model_returns_default(self):
        assert ml.clamp_max_tokens(None, "totally-unknown-model") == ml.DEFAULT_MAX_TOKENS

    def test_none_with_lower_limit_model_returns_model_limit(self):
        """None→4096 后仍被模型上限（glm-3-turbo=2048）夹紧。"""
        assert ml.clamp_max_tokens(None, "glm-3-turbo") == 2048


class TestL18ClampWarning:
    def test_clamp_logs_warning_once_per_model(self, recorder):
        # 2026-10-21：DEFAULT_MAX_TOKENS 不再是未知模型的上限；只有超过全局
        # 安全上限 MAX_MAX_TOKENS 才截断并告警。
        r1 = ml.clamp_max_tokens(300000, "some-unknown-model-x")
        r2 = ml.clamp_max_tokens(300000, "some-unknown-model-x")
        assert r1 == r2 == ml.MAX_MAX_TOKENS
        assert len(recorder.msgs) == 1, "L-18: 截断告警须按模型去重，不刷屏"
        assert "some-unknown-model-x" in recorder.msgs[0]

    def test_known_model_clamp_also_warns(self, recorder):
        """已知模型（gpt-3.5-turbo 上限 4096）截断同样告警。"""
        assert ml.clamp_max_tokens(999999, "gpt-3.5-turbo") == 4096
        assert len(recorder.msgs) == 1

    def test_no_warning_when_no_clamp(self, recorder):
        assert ml.clamp_max_tokens(1000, "gpt-4o") == 1000
        assert recorder.msgs == []


class TestProbedCapsAndExplicitValues:
    """2026-10-21：AMD 实测上限 + 显式值优先（DEFAULT 是默认，不是未知模型的上限）。"""

    def test_probed_amd_models_keep_explicit_65536(self):
        """探针实测值走 providers.json 持久化（不再写死在静态目录）。"""
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        ml.set_persisted_output_limit("amd", "DeepSeek-V4-Flash-Vision-Exp", 65536)
        assert ml.clamp_max_tokens(65536, "GLM-5.3-Flash", "amd") == 65536
        assert ml.clamp_max_tokens(65536, "DeepSeek-V4-Flash-Vision-Exp", "amd") == 65536

    def test_unknown_model_explicit_value_not_silently_capped_to_default(self):
        """未收录模型不能拿 DEFAULT=4096 当上限；显式值只受全局安全上限约束。"""
        assert ml.clamp_max_tokens(65536, "some-new-model") == 65536

    def test_unknown_model_above_global_max_is_capped_and_warns(self, recorder):
        assert ml.clamp_max_tokens(300000, "some-new-model") == ml.MAX_MAX_TOKENS
        assert len(recorder.msgs) == 1, "超过全局安全上限必须留痕"
