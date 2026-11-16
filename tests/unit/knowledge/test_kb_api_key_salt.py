# -*- coding: utf-8 -*-
"""知识库 API Key 哈希盐规格（审计 3.3-4，2026-11-17）：

`_hash_api_key` 原用全仓固定盐 "neurova-knowledge-salt"——同一 Key 在所有
部署里哈希一致，等价于给彩虹表发邀请。改为每条目独立随机盐：
`<salt>$<digest>` 形态，verify 用 hmac.compare_digest（恒时比较）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from neurova.knowledge.storage import KnowledgeStorage


@pytest.fixture
def storage(tmp_path) -> KnowledgeStorage:
    return KnowledgeStorage(str(tmp_path))


class TestApiKeyHashSaltSpec:
    def test_same_key_hashes_differently_per_entry(self, storage):
        """同一 Key 两次哈希必须不同（随机盐生效；固定盐形态下恒等=红）。"""
        a = storage._hash_api_key("sk-test")
        b = storage._hash_api_key("sk-test")
        assert a != b, "固定盐让同 Key 哈希全库一致——必须每条目独立随机盐"

    def test_salt_is_persisted_in_digest(self, storage):
        """`<salt>$<digest>` 形态：盐随条目落盘，验证可复算。"""
        digest = storage._hash_api_key("sk-test")
        assert "$" in digest
        salt, _ = digest.split("$", 1)
        assert len(salt) >= 16, "盐至少 16 hex（64bit）熵"

    def test_verify_correct_and_wrong_key(self, storage):
        hashed = storage._hash_api_key("sk-real")
        assert storage.verify_api_key("sk-real", hashed) is True
        assert storage.verify_api_key("sk-wrong", hashed) is False
        assert storage.verify_api_key("", hashed) is False
        assert storage.verify_api_key("sk-real", "") is False

    def test_legacy_fixed_salt_digest_is_rejected(self, storage):
        """旧固定盐形态的存量哈希不再可用（盐解析失败 → False，不误真）。"""
        import hashlib

        legacy = hashlib.sha256(
            f"neurova-knowledge-salt:sk-old".encode("utf-8")
        ).hexdigest()
        assert storage.verify_api_key("sk-old", legacy) is False

    def test_no_hardcoded_salt_in_source(self):
        src = Path(inspect.getfile(KnowledgeStorage)).read_text(encoding="utf-8")
        assert "neurova-knowledge-salt" not in src, "固定盐字面量必须从源码消失"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
