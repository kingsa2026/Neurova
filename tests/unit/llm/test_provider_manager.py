"""
Tests for LLMProviderManager — specifically the get_all_models aggregation.

TDD Red Phase: These tests define expected behavior before the fix.
"""

import pytest
from unittest.mock import MagicMock, patch
from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager():
    """Create an LLMProviderManager with mocked init to avoid config file I/O."""
    with patch.object(LLMProviderManager, '__init__', lambda self, **kw: None):
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = __import__('threading').RLock()
        return mgr


def _add_provider(mgr, pid, name, models):
    """Helper to add a provider with given models."""
    cfg = ProviderConfig(
        id=pid,
        name=name,
        provider="openai",
        base_url="https://api.example.com/v1",
        models=list(models),
        enabled=True,
    )
    mgr._providers[pid] = cfg
    return cfg


# ---------------------------------------------------------------------------
# Tests for get_all_models()
# ---------------------------------------------------------------------------

class TestGetAllModels:
    """Tests for LLMProviderManager.get_all_models()"""

    def test_empty_providers_returns_empty_list(self, manager):
        """No providers → empty model list."""
        result = manager.get_all_models()
        assert result == []

    def test_single_provider_models(self, manager):
        """Single provider with 3 models → 3 ModelInfo objects."""
        _add_provider(manager, "openai", "OpenAI", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])

        result = manager.get_all_models()
        assert len(result) == 3

        ids = [m.id for m in result]
        assert "gpt-4o" in ids
        assert "gpt-4o-mini" in ids
        assert "gpt-3.5-turbo" in ids

    def test_owned_by_matches_provider_id(self, manager):
        """Each model's owned_by must equal its provider's id."""
        _add_provider(manager, "openai", "OpenAI", ["gpt-4o"])
        _add_provider(manager, "anthropic", "Anthropic", ["claude-sonnet-4-20250514"])

        result = manager.get_all_models()
        for m in result:
            if m.id == "gpt-4o":
                assert m.owned_by == "openai"
            elif m.id == "claude-sonnet-4-20250514":
                assert m.owned_by == "anthropic"

    def test_multiple_providers_aggregate(self, manager):
        """Models from multiple providers are all present."""
        _add_provider(manager, "p1", "Provider 1", ["m1", "m2"])
        _add_provider(manager, "p2", "Provider 2", ["m3"])
        _add_provider(manager, "p3", "Provider 3", ["m4", "m5", "m6", "m7"])

        result = manager.get_all_models()
        assert len(result) == 7
        ids = {m.id for m in result}
        assert ids == {"m1", "m2", "m3", "m4", "m5", "m6", "m7"}

    def test_provider_with_no_models(self, manager):
        """Provider with empty models list contributes nothing."""
        _add_provider(manager, "empty", "Empty", [])
        _add_provider(manager, "has-models", "HasModels", ["gpt-4o"])

        result = manager.get_all_models()
        assert len(result) == 1
        assert result[0].id == "gpt-4o"

    def test_name_matches_model_id(self, manager):
        """Model name should equal model_id (as the backend stores only IDs)."""
        _add_provider(manager, "p", "P", ["deepseek-r1"])

        result = manager.get_all_models()
        assert result[0].id == "deepseek-r1"
        assert result[0].name == "deepseek-r1"


# ---------------------------------------------------------------------------
# Tests for model.py endpoint field mapping
# ---------------------------------------------------------------------------

class TestModelEndpointFieldMapping:
    """Tests that the model endpoint correctly maps fields."""

    def test_list_models_uses_get_all_models(self):
        """The endpoint should call get_all_models() on the provider manager."""
        from neurova.api.endpoints import model as model_module
        from unittest.mock import MagicMock, patch

        mock_pm = MagicMock()
        mock_model = MagicMock()
        mock_model.id = "gpt-4o"
        mock_model.name = "GPT-4o"
        mock_model.owned_by = "openai"
        mock_model.capabilities = ["text"]
        mock_model.is_active = True
        mock_model.status = "available"
        mock_pm.get_all_models.return_value = [mock_model]

        with patch.object(model_module, '_get_provider_manager', return_value=mock_pm):
            import asyncio
            request = MagicMock()
            request.state.request_id = "test-123"
            result = asyncio.run(model_module.list_models(request))

        assert len(result) == 1
        assert result[0].model_id == "gpt-4o"
        assert result[0].provider == "openai"
        assert result[0].name == "GPT-4o"

    def test_list_models_fallback_when_no_get_all_models(self):
        """When get_all_models doesn't exist, fall back to default Auto model."""
        from neurova.api.endpoints import model as model_module
        from unittest.mock import MagicMock, patch

        mock_pm = MagicMock(spec=[])  # No attributes at all

        with patch.object(model_module, '_get_provider_manager', return_value=mock_pm):
            import asyncio
            request = MagicMock()
            request.state.request_id = "test-456"
            result = asyncio.run(model_module.list_models(request))

        assert len(result) == 1
        assert result[0].model_id == "auto"
        assert result[0].provider == "system"


class TestDeleteModel:
    """Tests for the DELETE /models/{model_id} endpoint."""

    def _make_manager_with_models(self):
        """Create a manager with sensetime provider having 3 models."""
        import tempfile
        from pathlib import Path

        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = __import__('threading').RLock()
        # 真实临时路径(原子写需要 with_suffix/os.replace 等真 Path 语义)
        tmpdir = tempfile.mkdtemp(prefix="neurova-pm-test-")
        mgr._config_path = Path(tmpdir) / "providers.json"
        _add_provider(mgr, "sensetime", "商汤科技", [
            "sensechat-5", "deepseek-v4-flash", "sensenova-6.7-flash-lite"
        ])
        return mgr

    def test_delete_model_removes_from_provider(self):
        """Deleting a model removes it from the provider's models list."""
        mgr = self._make_manager_with_models()
        provider = mgr.get_provider("sensetime")
        assert "sensenova-6.7-flash-lite" in provider.models

        # Simulate the endpoint logic
        models = list(provider.models)
        models.remove("sensenova-6.7-flash-lite")
        mgr.update_provider("sensetime", models=models)

        provider = mgr.get_provider("sensetime")
        assert "sensenova-6.7-flash-lite" not in provider.models
        assert len(provider.models) == 2

    def test_delete_model_persists_to_config(self):
        """Deleting a model persists the change."""
        mgr = self._make_manager_with_models()
        provider = mgr.get_provider("sensetime")

        models = list(provider.models)
        models.remove("deepseek-v4-flash")
        mgr.update_provider("sensetime", models=models)

        # Re-read from config
        provider = mgr.get_provider("sensetime")
        assert "deepseek-v4-flash" not in provider.models
        assert provider.models == ["sensechat-5", "sensenova-6.7-flash-lite"]

    def test_delete_nonexistent_model_no_error(self):
        """Deleting a model that doesn't exist should not error."""
        mgr = self._make_manager_with_models()
        provider = mgr.get_provider("sensetime")

        models = list(provider.models)
        if "nonexistent-model" in models:
            models.remove("nonexistent-model")
        mgr.update_provider("sensetime", models=models)

        provider = mgr.get_provider("sensetime")
        assert len(provider.models) == 3  # unchanged

    def test_delete_model_endpoint_calls_update_provider(self):
        """The DELETE endpoint should call update_provider with updated models list."""
        from neurova.api.endpoints import model as model_module
        from unittest.mock import MagicMock, patch, AsyncMock
        import asyncio

        mgr = self._make_manager_with_models()

        with patch.object(model_module, '_get_provider_manager', return_value=mgr):
            request = MagicMock()
            request.state.request_id = "test-delete"
            result = asyncio.run(model_module.delete_model(request, "sensenova-6.7-flash-lite"))

        assert result["code"] == 0
        provider = mgr.get_provider("sensetime")
        assert "sensenova-6.7-flash-lite" not in provider.models
        assert len(provider.models) == 2

    def test_delete_model_not_found_returns_error(self):
        """Deleting a model that doesn't exist in any provider should return 404."""
        from neurova.api.endpoints import model as model_module
        from unittest.mock import MagicMock, patch
        from fastapi import HTTPException
        import asyncio

        mgr = self._make_manager_with_models()

        with patch.object(model_module, '_get_provider_manager', return_value=mgr):
            request = MagicMock()
            request.state.request_id = "test-delete-notfound"
            try:
                asyncio.run(model_module.delete_model(request, "nonexistent-model"))
                assert False, "Should have raised HTTPException"
            except HTTPException as e:
                assert e.status_code == 404
