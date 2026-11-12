# -*- coding: utf-8 -*-
"""C2 工件级内容地址溯源（specs/2026-11-12 §18）：SHA-256 校验＋归属卡读数＋
版本漂移显式报（不静默换版）＋事实级 lineage 单源不动。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.ontology.domain_pack import (
    packAttribution,
    packChecksum,
    verifyPackIntegrity,
)


class TestPackChecksum:
    def test_deterministic(self):
        first = packChecksum("standard")
        second = packChecksum("standard")
        assert first == second
        assert len(first) == 64, "SHA-256 hex 长度"

    def test_unknownPack(self):
        with pytest.raises(ValueError):
            packChecksum("ghost_pack")


class TestAttribution:
    def test_cardFields(self):
        card = packAttribution("standard")
        assert card["packId"] == "standard"
        assert card["license"], "license 读数非空"
        assert "sha256" in card
        assert card["termCount"] > 0


class TestIntegrity:
    def test_unverifiedWithoutBaseline(self):
        result = verifyPackIntegrity("standard")
        assert result["status"] == "unverified", "无注册哈希＝unverified"
        assert "sha256" in result, "当前哈希如实返回"

    def test_untamperedPasses(self):
        current = packChecksum("standard")
        result = verifyPackIntegrity("standard", registeredChecksum=current)
        assert result["status"] == "ok", "哈希匹配通过"

    def test_tamperedDriftDetected(self, tmp_path):
        """篡改包字节→SHA-256 漂移显式报（不静默换版）。"""
        from neurova.knowledge.ontology.domain_pack import _PACKS_DIR

        src = _PACKS_DIR / "standard_pack.json"
        backup = src.read_bytes()
        registered = packChecksum("standard")
        try:
            src.write_bytes(backup + b"\n")
            result = verifyPackIntegrity("standard", registeredChecksum=registered)
            assert result["status"] == "drift", "篡改后 SHA-256 漂移显式报"
            assert "registered" in result and "sha256" in result, "漂移读数含注册哈希与当前哈希"
        finally:
            src.write_bytes(backup)
