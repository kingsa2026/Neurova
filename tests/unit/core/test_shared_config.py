"""shared_config 共享配置管理器单元测试（对齐真实实现）。

真实 API（neurova/shared_config.py）：
    SharedConfigManager(config_path)      # 兼容 str/Path；不存在则建默认配置
    list_llm_providers / get_llm_provider(id) / add_llm_provider / update_llm_provider / remove_llm_provider
    list_mcp_servers / get_mcp_server(id) / add_mcp_server / update_mcp_server / remove_mcp_server
    export_config(path) / import_config(path)
    get_provider_for_agent(agent_id) -> {"provider","model","agent_id"}
    get_settings / update_settings
    get_shared_config_manager(path) / reset_shared_config_manager 单例

配置为扁平结构：llm_providers / mcp_servers / default_provider / default_model / settings。
默认内置提供商：openai(启用,prio1) / anthropic(启用,prio2) / local(禁用,prio3)。
无公共 .config 访问器，测试通过公共方法断言；提供商按 id 查找（openai 的 name 为 "OpenAI"）。
"""

import json
from pathlib import Path

import pytest

from neurova.shared_config import (
    SharedConfigManager,
    get_shared_config_manager,
    reset_shared_config_manager,
)


def make_manager(tmp_path: Path) -> SharedConfigManager:
    return SharedConfigManager(str(tmp_path / "shared_config.json"))


def write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class TestInit:
    def test_creates_default_config_file(self, tmp_path):
        cfg = tmp_path / "shared_config.json"
        SharedConfigManager(str(cfg))
        assert cfg.exists()

    def test_loads_existing_config(self, tmp_path):
        cfg = tmp_path / "shared_config.json"
        custom = {"id": "custom", "name": "Custom", "enabled": True}
        write_config(cfg, {"version": "2.0", "llm_providers": [custom], "mcp_servers": []})
        mgr = SharedConfigManager(str(cfg))
        ids = [p["id"] for p in mgr.list_llm_providers()]
        assert ids == ["custom"]

    def test_bad_json_falls_back_to_default(self, tmp_path):
        cfg = tmp_path / "shared_config.json"
        cfg.write_text("{not valid json", encoding="utf-8")
        mgr = SharedConfigManager(str(cfg))
        ids = {p["id"] for p in mgr.list_llm_providers()}
        assert {"openai", "anthropic", "local"} <= ids

    def test_default_config_has_builtin_providers(self, tmp_path):
        mgr = make_manager(tmp_path)
        ids = {p["id"] for p in mgr.list_llm_providers()}
        assert {"openai", "anthropic", "local"} <= ids


class TestSingletonHelpers:
    def test_returns_singleton_and_resets(self, tmp_path):
        reset_shared_config_manager()
        try:
            a = get_shared_config_manager(str(tmp_path / "s.json"))
            b = get_shared_config_manager()
            assert a is b
        finally:
            reset_shared_config_manager()


class TestLlmProviders:
    def test_get_provider_found(self, tmp_path):
        mgr = make_manager(tmp_path)
        provider = mgr.get_llm_provider("openai")
        assert provider is not None
        assert provider["id"] == "openai"
        assert provider["name"] == "OpenAI"

    def test_get_provider_not_found(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.get_llm_provider("missing") is None

    def test_add_provider(self, tmp_path):
        mgr = make_manager(tmp_path)
        ok = mgr.add_llm_provider({"id": "new", "name": "New", "enabled": True})
        assert ok is True
        assert mgr.get_llm_provider("new") is not None

    def test_add_provider_duplicate_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.add_llm_provider({"id": "openai", "name": "dup"}) is False

    def test_update_provider(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.update_llm_provider("openai", {"enabled": False}) is True
        assert mgr.get_llm_provider("openai")["enabled"] is False

    def test_update_missing_provider_returns_false(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.update_llm_provider("missing", {"enabled": False}) is False

    def test_remove_provider(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.remove_llm_provider("local") is True
        assert mgr.get_llm_provider("local") is None


class TestMcpServers:
    def test_get_server_found(self, tmp_path):
        mgr = make_manager(tmp_path)
        server = mgr.get_mcp_server("filesystem")
        assert server is not None
        assert server["id"] == "filesystem"

    def test_add_server(self, tmp_path):
        mgr = make_manager(tmp_path)
        # 严格 schema（ZCode 模式）要求 stdio 配置提供 command
        assert (
            mgr.add_mcp_server({"id": "git", "name": "Git", "command": "uvx", "args": ["mcp-server-git"], "enabled": True})
            is True
        )
        assert mgr.get_mcp_server("git") is not None

    def test_add_server_invalid_rejected(self, tmp_path):
        """严格 schema：缺 transport 输入（command/url）的配置应被拒绝"""
        mgr = make_manager(tmp_path)
        assert mgr.add_mcp_server({"id": "git", "name": "Git", "enabled": True}) is False
        assert mgr.get_mcp_server("git") is None

    def test_add_server_duplicate_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        # 带合法 command 使其通过 schema 校验，落到重复 id 检查
        assert mgr.add_mcp_server({"id": "filesystem", "name": "dup", "command": "npx"}) is False

    def test_update_and_remove_server(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.update_mcp_server("filesystem", {"enabled": False}) is True
        assert mgr.get_mcp_server("filesystem")["enabled"] is False
        assert mgr.remove_mcp_server("filesystem") is True
        assert mgr.get_mcp_server("filesystem") is None

    def test_update_to_invalid_config_rejected(self, tmp_path):
        """严格 schema：更新后整体配置非法时应拒绝，原配置保持不变"""
        mgr = make_manager(tmp_path)
        assert mgr.update_mcp_server("filesystem", {"command": ""}) is False
        server = mgr.get_mcp_server("filesystem")
        assert server["command"] == "npx"


class TestImportExport:
    def test_export_writes_file(self, tmp_path):
        mgr = make_manager(tmp_path)
        export_path = tmp_path / "export.json"
        assert mgr.export_config(export_path) is True
        assert export_path.exists()
        data = json.loads(export_path.read_text(encoding="utf-8"))
        assert "llm_providers" in data

    def test_import_config(self, tmp_path):
        mgr = make_manager(tmp_path)
        import_path = tmp_path / "import.json"
        write_config(import_path, {"llm_providers": [{"id": "x", "name": "X"}], "mcp_servers": []})
        assert mgr.import_config(import_path) is True
        assert [p["id"] for p in mgr.list_llm_providers()] == ["x"]

    def test_import_invalid_structure_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        import_path = tmp_path / "bad.json"
        write_config(import_path, {"foo": "bar"})
        assert mgr.import_config(import_path) is False

    def test_import_missing_file_rejected(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.import_config(tmp_path / "nope.json") is False


class TestGetProviderForAgent:
    def test_returns_default_provider(self, tmp_path):
        mgr = make_manager(tmp_path)
        result = mgr.get_provider_for_agent("agent1")
        assert result["provider"]["id"] == "openai"
        assert result["model"] == "gpt-3.5-turbo"
        assert result["agent_id"] == "agent1"

    def test_falls_back_to_first_enabled_when_default_missing(self, tmp_path):
        mgr = make_manager(tmp_path)
        mgr.remove_llm_provider("openai")
        result = mgr.get_provider_for_agent()
        assert result["provider"]["id"] == "anthropic"

    def test_no_enabled_providers_returns_none(self, tmp_path):
        mgr = make_manager(tmp_path)
        mgr.remove_llm_provider("openai")
        mgr.remove_llm_provider("anthropic")
        mgr.remove_llm_provider("local")
        result = mgr.get_provider_for_agent()
        assert result["provider"] is None


class TestSettings:
    def test_get_settings(self, tmp_path):
        mgr = make_manager(tmp_path)
        settings = mgr.get_settings()
        assert settings["log_level"] == "INFO"

    def test_update_settings(self, tmp_path):
        mgr = make_manager(tmp_path)
        assert mgr.update_settings({"log_level": "DEBUG"}) is True
        assert mgr.get_settings()["log_level"] == "DEBUG"


class TestPersistence:
    def test_add_provider_persists_to_file(self, tmp_path):
        cfg = tmp_path / "shared_config.json"
        mgr = SharedConfigManager(str(cfg))
        mgr.add_llm_provider({"id": "persisted", "name": "P"})
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert any(p["id"] == "persisted" for p in data["llm_providers"])
