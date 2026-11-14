"""Provider 模板数据驱动化（P1-5）。

内置服务商模板从代码元组迁到 config/llm_provider_templates.json（单一事实源），
装载时逐条校验（必填字段 / base_url 形态 / id 唯一）；仓库数据坏了就显式红，
不静默少装一批。11 个内置 id 与迁移前逐一对齐（防迁移丢数据）。
"""

import json
from pathlib import Path

import pytest

from neurova.llm import provider_manager as pm

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "config" / "llm_provider_templates.json"

EXPECTED_IDS = [
    "openrouter",
    "opencode",
    "kilo-code",
    "github-models",
    "sensetime",
    "volcengine",
    "volcengine-agentplan",
    "mimo",
    "mimo-tokenplan",
    "agnes-intl",
    "agnes-cn",
]


class TestTemplateFile:
    def test_file_exists_and_parses(self):
        data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert isinstance(data.get("providers"), list)
        assert isinstance(data.get("revision"), int)

    def test_raw_file_entries_match_loader(self):
        data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        rawIds = [e.get("id") for e in data["providers"]]
        assert rawIds == EXPECTED_IDS


class TestLoader:
    def test_eleven_builtin_ids_preserved_in_order(self):
        defs = pm.builtinProviderDefs()
        assert [d["id"] for d in defs] == EXPECTED_IDS

    def test_each_template_valid(self):
        for d in pm.builtinProviderDefs():
            assert d["name"], d["id"]
            assert d["provider"], d["id"]
            assert d["base_url"].startswith("https://"), d["id"]
            assert isinstance(d["models"], list), d["id"]

    def test_ids_unique(self):
        ids = [d["id"] for d in pm.builtinProviderDefs()]
        assert len(ids) == len(set(ids))

    def test_keyless_providers_still_keyless(self):
        # 迁移不改变「哪些 id 免 key」的口径
        defs = {d["id"]: d for d in pm.builtinProviderDefs()}
        assert defs["opencode"].get("api_key_prefix", "") == "" or True
        assert "api_key_prefix" not in defs["opencode"] or defs["opencode"]["api_key_prefix"] == ""

    def test_missing_file_raises_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            pm, "_providerTemplatePath", lambda: tmp_path / "nope.json"
        )
        with pytest.raises(FileNotFoundError, match="内置服务商模板文件缺失"):
            pm.builtinProviderDefs()

    def test_corrupt_json_raises_clear_error(self, tmp_path, monkeypatch):
        bad = tmp_path / "llm_provider_templates.json"
        bad.write_text('{"providers": [ { "broken"', encoding="utf-8")
        monkeypatch.setattr(pm, "_providerTemplatePath", lambda: bad)
        with pytest.raises(ValueError, match="JSON 损坏"):
            pm.builtinProviderDefs()

    def test_invalid_entry_raises_with_index(self, tmp_path, monkeypatch):
        bad = tmp_path / "llm_provider_templates.json"
        bad.write_text(
            json.dumps({"revision": 1, "providers": [{"id": "x"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(pm, "_providerTemplatePath", lambda: bad)
        with pytest.raises(ValueError, match="第 0 条校验失败"):
            pm.builtinProviderDefs()

    def test_duplicate_id_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "llm_provider_templates.json"
        entry = {
            "id": "dup",
            "name": "D",
            "provider": "openai",
            "base_url": "https://x.example.com/v1",
        }
        bad.write_text(
            json.dumps({"revision": 1, "providers": [entry, entry]}), encoding="utf-8"
        )
        monkeypatch.setattr(pm, "_providerTemplatePath", lambda: bad)
        with pytest.raises(ValueError, match="id 重复"):
            pm.builtinProviderDefs()

    def test_manager_seeds_from_templates(self, tmp_path, monkeypatch):
        """管理器种子行为不变：模板文件是唯一事实源。"""
        from neurova.llm.provider_manager import LLMProviderManager

        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        manager = LLMProviderManager()
        ids = {p.id for p in manager.list_providers()}
        assert set(EXPECTED_IDS) <= ids
