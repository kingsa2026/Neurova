"""Storage class patches must reach the lazy API singleton after import."""

from unittest.mock import Mock


def test_storage_resolves_class_at_first_call_and_reuses_instance(monkeypatch):
    from neurova.api.endpoints import neurflow_api as api
    from neurova.collaboration.neurflow import storage

    getter = api._get_storage
    monkeypatch.delattr(getter, "_instance", raising=False)
    instance = object()
    constructor = Mock(return_value=instance)
    monkeypatch.setattr(storage, "NeurflowStorage", constructor)
    try:
        assert getter() is instance
        assert getter() is instance
        constructor.assert_called_once_with()
    finally:
        if hasattr(getter, "_instance"):
            del getter._instance
