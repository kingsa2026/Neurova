"""应用设置持久化 + 全局输出预算（真机问题：最大输出 token 无入口）

- app_settings：data/app_settings.json 按 section 持久化（替换内存 stub）
- apply_global_output_budget：全局默认输出预算只补"未显式设置"的 agent
  （max_tokens == LLMConfig 数据类默认 131072 视为未设置），显式配置不动
- settings API：GET/PUT 真实读写该存储（见 test_app_settings_endpoint）
"""

from pathlib import Path

import pytest

from neurova.core import app_settings as asm


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "app_settings.json"


class TestLoadSave:
    def test_defaults_when_missing(self, settings_file):
        s = asm.load_app_settings(settings_file)
        assert s["advanced"]["max_output_tokens"] == asm.LLM_DEFAULT_MAX_TOKENS
        assert s["advanced"]["log_level"] == "info"
        assert s["general"]["language"] == "zh-CN"

    def test_save_merges_and_persists(self, settings_file):
        asm.save_app_settings("advanced", {"max_output_tokens": 32768}, settings_file)
        s = asm.load_app_settings(settings_file)
        assert s["advanced"]["max_output_tokens"] == 32768
        assert s["advanced"]["log_level"] == "info", "未保存的键保留默认"
        # 真实落盘（重启可恢复）
        s2 = asm.load_app_settings(settings_file)
        assert s2["advanced"]["max_output_tokens"] == 32768

    def test_corrupt_file_falls_back_to_defaults(self, settings_file):
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text("{broken json", encoding="utf-8")
        s = asm.load_app_settings(settings_file)
        assert s["advanced"]["max_output_tokens"] == asm.LLM_DEFAULT_MAX_TOKENS


class TestApplyGlobalOutputBudget:
    class FakeLLMConfig:
        def __init__(self, max_tokens):
            self.max_tokens = max_tokens

    def test_applies_to_default_config(self, settings_file):
        """数据类默认 131072 视为"未显式设置"→ 应用全局预算"""
        asm.save_app_settings("advanced", {"max_output_tokens": 65536}, settings_file)
        cfg = self.FakeLLMConfig(asm.LLM_DEFAULT_MAX_TOKENS)
        assert asm.apply_global_output_budget(cfg, settings_file) is True
        assert cfg.max_tokens == 65536

    def test_never_overrides_explicit_config(self, settings_file):
        """显式小配置（用户真实设置）不被全局默认覆盖——只补默认不改显式"""
        asm.save_app_settings("advanced", {"max_output_tokens": 65536}, settings_file)
        cfg = self.FakeLLMConfig(8192)
        assert asm.apply_global_output_budget(cfg, settings_file) is False
        assert cfg.max_tokens == 8192

    def test_no_setting_or_same_value_noop(self, settings_file):
        cfg = self.FakeLLMConfig(asm.LLM_DEFAULT_MAX_TOKENS)
        assert asm.apply_global_output_budget(cfg, settings_file) is False
        assert cfg.max_tokens == asm.LLM_DEFAULT_MAX_TOKENS

    def test_none_config_safe(self, settings_file):
        assert asm.apply_global_output_budget(None, settings_file) is False

    def test_invalid_setting_noop(self, settings_file):
        asm.save_app_settings("advanced", {"max_output_tokens": "abc"}, settings_file)
        cfg = self.FakeLLMConfig(asm.LLM_DEFAULT_MAX_TOKENS)
        assert asm.apply_global_output_budget(cfg, settings_file) is False

    def test_reapply_follows_new_global_value(self, settings_file):
        """二次修改全局预算：此前由本函数应用过的配置要能跟进新值（不能卡死在旧值）"""
        asm.save_app_settings("advanced", {"max_output_tokens": 65536}, settings_file)
        cfg = self.FakeLLMConfig(asm.LLM_DEFAULT_MAX_TOKENS)
        assert asm.apply_global_output_budget(cfg, settings_file) is True
        assert cfg.max_tokens == 65536

        asm.save_app_settings("advanced", {"max_output_tokens": 32768}, settings_file)
        assert asm.apply_global_output_budget(cfg, settings_file) is True
        assert cfg.max_tokens == 32768

    def test_explicit_config_never_flagged(self, settings_file):
        """显式配置即便数值恰好等于某次全局值，也永不跟进（无来源标记）"""
        asm.save_app_settings("advanced", {"max_output_tokens": 8192}, settings_file)
        cfg = self.FakeLLMConfig(8192)  # 用户显式设置，恰与全局相同
        assert asm.apply_global_output_budget(cfg, settings_file) is False


class TestRealLLMConfigIntegration:
    def test_real_llmconfig_default_is_sentinel(self):
        """LLMConfig 数据类默认必须仍是哨兵值 131072——若上游改默认，
        本测试拦截并要求同步 LLM_DEFAULT_MAX_TOKENS"""
        from neurova.llm_client import LLMConfig

        assert LLMConfig().max_tokens == asm.LLM_DEFAULT_MAX_TOKENS

    def test_apply_on_real_config(self, settings_file):
        from neurova.llm_client import LLMConfig

        asm.save_app_settings("advanced", {"max_output_tokens": 49152}, settings_file)
        cfg = LLMConfig()  # 默认 131072
        assert asm.apply_global_output_budget(cfg, settings_file) is True
        assert cfg.max_tokens == 49152
