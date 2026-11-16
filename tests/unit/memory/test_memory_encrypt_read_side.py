# -*- coding: utf-8 -*-
"""MemorySecurity encrypt 态**读侧透明解密**（用户拍板 2026-11-17：本轮做读侧）。

R3 已把 encrypt 态写侧接进 remember 咽喉（Fernet 全文），但读侧 9+ 处经
`_row_to_memory` 的读路径仍直读密文——开启 encrypt 后"写得进、读不出"。
本档钉住读侧契约：
1. encrypt 行经现役读路径（get_memory/reload 装载）读出**原文**；
2. log_only 明文行与 mask 掩码行不受影响（mask 不可逆，原样即正确）;
3. 密文损坏/密钥不匹配时诚实抛错，不静默返回密文或空串。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.security import (
    SecurityConfig,
    get_memory_security,
    reset_memory_security,
)


def _security(action: str) -> SecurityConfig:
    return SecurityConfig(sensitive_write_action=action)

SECRET_SAMPLE = "我的服务器密钥是 sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "mem.db")


@pytest.fixture
def manager(db_path):
    return MemoryManager(
        db_path=db_path,
        agent_id="sec_test_agent",
        user_id="sec_test_user",
    )


@pytest.fixture(autouse=True)
def _reset_security_singleton():
    reset_memory_security()
    yield
    reset_memory_security()


class TestEncryptReadSide:
    def test_encrypt_state_read_path_returns_plaintext(self, manager):
        """encrypt 态经现役读路径（get_memory）读出原文，而非密文。"""
        get_memory_security(_security("encrypt"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == SECRET_SAMPLE, (
            "encrypt 态读侧必须透明解密——读到密文即「写得进读不出」"
        )

    def test_encrypt_state_survives_reload(self, db_path):
        """持久化后重启（新实例装载）仍读出原文——解密在装载出口生效。"""
        get_memory_security(_security("encrypt"))
        first = MemoryManager(
            db_path=db_path, agent_id="sec_test_agent", user_id="sec_test_user"
        )
        mem_id = first.remember(SECRET_SAMPLE, auto_analyze_emotion=False)

        reloaded = MemoryManager(
            db_path=db_path, agent_id="sec_test_agent", user_id="sec_test_user"
        )
        mem = reloaded.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == SECRET_SAMPLE, "重启装载后必须仍能解密读出原文"

    def test_plaintext_rows_unaffected(self, manager):
        """log_only 明文行零影响（读侧只对带加密标记的行解密）。"""
        mem_id = manager.remember("用户喜欢蓝色主题", auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == "用户喜欢蓝色主题"

    def test_mask_rows_stay_masked(self, manager):
        """mask 行读出掩码（不可逆，原样即正确——不得二次处理）。"""
        get_memory_security(_security("mask"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert "sk-proj-AAAA" not in mem["content"]
        assert "服务器密钥" in mem["content"]

    def test_corrupted_ciphertext_is_honest(self, manager):
        """密文损坏/密钥不匹配：读路径诚实抛错，不静默回密文/空串。

        MemoryManager 按作用域注册表复用实例，库面篡改够不着内存态；直接在
        作用域注册表塞一条带坏密文+fernet 标记的记忆（等价于装载了损坏行），
        读路径（to_dict→plaintextContent）必须诚实抛错。
        """
        get_memory_security(_security("encrypt"))
        from neurova.cognitive_layers.memory_layer.models import Memory

        bad = Memory(
            id="bad1",
            content="not-a-fernet-token",
            metadata={"_security": {"encrypted": "fernet"}},
            agent_id="sec_test_agent",
            user_id="sec_test_user",
        )
        manager._memories["bad1"] = bad
        with pytest.raises(Exception):
            manager.get_memory("bad1", agent_wide=True)
