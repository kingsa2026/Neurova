"""Tests for neurova.llm.config_console — TDD RED phase."""
import json
import threading

import pytest


@pytest.fixture
def console(tmp_path, monkeypatch):
    """Build a fresh LLMConfigConsole rooted at tmp_path.

    Resets the module-level singleton so each test gets a clean instance.
    """
    import neurova.llm.config_console as cc_mod

    monkeypatch.setattr(cc_mod, "_singleton", None)
    monkeypatch.setattr(cc_mod, "_singleton_lock", threading.Lock())
    config_file = tmp_path / "llm_config.json"
    return cc_mod.LLMConfigConsole(config_path=str(config_file))


class TestProviderCRUD:
    def test_add_and_get_provider(self, console):
        provider_id = console.add_provider({
            "name": "OpenAI",
            "provider_type": "openai",
            "api_key": "sk-test",
            "default_model": "gpt-4o",
        })
        assert isinstance(provider_id, str)
        assert provider_id.startswith("pv_")

        provider = console.get_provider(provider_id)
        assert provider is not None
        assert provider["name"] == "OpenAI"
        assert provider["provider_type"] == "openai"
        assert provider["api_key"] == "sk-test"

    def test_add_provider_missing_required_field_raises(self, console):
        with pytest.raises(ValueError):
            console.add_provider({"name": "Incomplete"})

    def test_update_provider_merges_fields(self, console):
        pid = console.add_provider({
            "name": "Original",
            "provider_type": "openai",
        })
        ok = console.update_provider(pid, {"name": "Renamed", "enabled": False})
        assert ok is True
        provider = console.get_provider(pid)
        assert provider["name"] == "Renamed"
        assert provider["enabled"] is False
        assert provider["provider_type"] == "openai"

    def test_update_unknown_provider_returns_false(self, console):
        assert console.update_provider("pv_nope", {"name": "x"}) is False

    def test_remove_provider_drops_record(self, console):
        pid = console.add_provider({
            "name": "Doomed",
            "provider_type": "anthropic",
        })
        assert console.remove_provider(pid) is True
        assert console.get_provider(pid) is None
        assert console.remove_provider(pid) is False

    def test_list_providers_returns_all(self, console):
        console.add_provider({"name": "A", "provider_type": "openai"})
        console.add_provider({"name": "B", "provider_type": "anthropic"})
        console.add_provider({"name": "C", "provider_type": "ollama"})
        providers = console.list_providers()
        names = {p["name"] for p in providers}
        assert names == {"A", "B", "C"}


class TestDefaultParams:
    def test_default_params_have_expected_keys(self, console):
        params = console.get_default_params()
        assert "temperature" in params
        assert "top_p" in params
        assert "max_tokens" in params
        assert params["temperature"] == 0.7

    def test_update_default_params_persists(self, console, tmp_path):
        ok = console.update_default_params({
            "temperature": 0.3,
            "top_p": 0.5,
            "max_tokens": 8192,
        })
        assert ok is True
        params = console.get_default_params()
        assert params["temperature"] == 0.3
        assert params["top_p"] == 0.5
        assert params["max_tokens"] == 8192

        config_file = tmp_path / "llm_config.json"
        assert config_file.exists()
        on_disk = json.loads(config_file.read_text(encoding="utf-8"))
        assert on_disk["default_params"]["temperature"] == 0.3

    def test_update_default_params_ignores_unknown_keys(self, console):
        console.update_default_params({"temperature": 0.1, "bogus_key": "x"})
        assert console.get_default_params()["temperature"] == 0.1
        assert "bogus_key" not in console.get_default_params()


class TestTokenStats:
    def test_record_token_usage_aggregates_totals(self, console):
        console.record_token_usage("p1", "m1", prompt_tokens=100, completion_tokens=50, cost=0.01)
        console.record_token_usage("p1", "m1", prompt_tokens=200, completion_tokens=80, cost=0.02)
        console.record_token_usage("p2", "m2", prompt_tokens=50, completion_tokens=25, cost=0.005)

        stats = console.get_token_stats()
        assert stats["total_prompt_tokens"] == 350
        assert stats["total_completion_tokens"] == 155
        assert stats["total_requests"] == 3
        assert abs(stats["total_cost"] - 0.035) < 1e-9

    def test_token_stats_filter_by_provider(self, console):
        console.record_token_usage("p1", "m1", 10, 5, 0.001)
        console.record_token_usage("p2", "m2", 20, 10, 0.002)

        stats = console.get_token_stats(provider_id="p1")
        assert "p1" in stats["by_provider"]
        assert "p2" not in stats["by_provider"]


class TestThreadSafety:
    def test_concurrent_adds_do_not_corrupt_state(self, console):
        n_threads = 8
        per_thread = 25

        def worker(tid):
            for i in range(per_thread):
                console.add_provider({
                    "name": f"Provider-{tid}-{i}",
                    "provider_type": "openai",
                })

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        providers = console.list_providers()
        assert len(providers) == n_threads * per_thread


class TestSingleton:
    def test_factory_returns_singleton(self, tmp_path, monkeypatch):
        import neurova.llm.config_console as cc_mod

        monkeypatch.setattr(cc_mod, "_singleton", None)
        monkeypatch.setattr(cc_mod, "_singleton_lock", threading.Lock())
        config_file = tmp_path / "singleton.json"

        a = cc_mod.get_llm_config_console(config_path=str(config_file))
        b = cc_mod.get_llm_config_console(config_path=str(config_file))
        assert a is b

    def test_factory_persists_across_instances(self, tmp_path, monkeypatch):
        import neurova.llm.config_console as cc_mod

        monkeypatch.setattr(cc_mod, "_singleton", None)
        monkeypatch.setattr(cc_mod, "_singleton_lock", threading.Lock())
        config_file = tmp_path / "persist.json"

        first = cc_mod.get_llm_config_console(config_path=str(config_file))
        pid = first.add_provider({
            "name": "Survives",
            "provider_type": "openai",
        })
        first.record_token_usage(pid, "m1", 10, 5, 0.001)

        second = cc_mod.get_llm_config_console(config_path=str(config_file))
        assert second.get_provider(pid) is not None
        stats = second.get_token_stats()
        assert stats["total_prompt_tokens"] == 10
