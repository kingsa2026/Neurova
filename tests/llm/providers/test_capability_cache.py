"""
tests/llm/providers/test_capability_cache.py — TDD RED for CachedCapability placeholder.
"""
from dataclasses import is_dataclass
import pytest


class TestCachedCapability:
    def test_is_dataclass(self):
        from neurova.llm.providers.capability_cache import CachedCapability
        assert is_dataclass(CachedCapability)

    def test_can_instantiate(self):
        from neurova.llm.providers.capability_cache import CachedCapability
        cap = CachedCapability(
            model="gpt-4",
            capabilities={"chat": True, "vision": False},
        )
        assert cap.model == "gpt-4"
        assert cap.capabilities["vision"] is False
