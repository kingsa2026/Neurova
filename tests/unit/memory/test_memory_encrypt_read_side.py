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


class TestEncryptReadSideBypassingToDict:
    """绕过 to_dict 的现役读出口（U2 补漏批）：同样必须透明解密。

    to_dict 出口（70d54c11e）覆盖不了自拼 dict/行直读的三族读面：
    1. get_top_memories_by_temperature——温度通道（neurova_recall 消费）自拼 dict；
    2. MoE ExpertDrilldownRetriever L0——persist 行直读（绕过 _row_to_memory）；
    3. update_memory 内容变更——带标记行的内容改写必须维持
       「标记⇔行内容是密文」不变量，否则该行从此读不出。
    """

    def test_top_temperature_lane_returns_plaintext(self, manager):
        get_memory_security(_security("encrypt"))
        manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        tops = manager.get_top_memories_by_temperature(limit=5)
        assert tops, "温度通道应返回候选"
        assert tops[0]["content"] == SECRET_SAMPLE, (
            "温度通道自拼 dict 直用 mem.content 会把密文喂给召回面"
        )

    def test_moe_l0_lane_returns_plaintext(self, manager):
        get_memory_security(_security("encrypt"))
        manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)

        import sqlite3

        from neurova.cognitive_layers.memory_layer.moe_router import (
            ExpertDrilldownRetriever,
        )
        from neurova.mem_core import _PersistDbStore

        conn = sqlite3.connect(manager.persistenceDbPath())
        try:
            agentId, neuserId, userId = conn.execute(
                "SELECT agent_id, neuser_id, user_id FROM memories LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        store = _PersistDbStore(manager.persistenceDbPath(), agentId, neuserId, userId)
        try:
            retriever = ExpertDrilldownRetriever(expert_def={}, store=store)
            rows = retriever._layer0_exact_index()
        finally:
            store.close()
        assert rows, "L0 应捞到候选行"
        assert rows[0]["content"] == SECRET_SAMPLE, (
            "L0 行直读面必须按标记透明解密——密文进上下文即乱码注入"
        )

    def test_update_content_keeps_encrypted_row_readable(self, manager):
        get_memory_security(_security("encrypt"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        newContent = "替换后的新密钥 sk-proj-BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
        assert manager.update_memory(mem_id, content=newContent, agent_wide=True)

        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == newContent, (
            "带标记行改内容必须重新加密落行——明文配标记会让读侧解密必然抛错"
        )
        # 行面仍是密文（at-rest 语义不因改写降级）；正文表在配对库
        import json as _json
        import sqlite3

        conn = sqlite3.connect(manager.persistenceDbPath())
        try:
            row = conn.execute(
                "SELECT content, metadata FROM memories WHERE id = ?", (mem_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row[0] != newContent, "改写后的行内容必须仍是密文"
        assert _json.loads(row[1])["_security"]["encrypted"] == "fernet"

    def test_fernet_without_cipher_fails_fast(self):
        """密钥缺失（加密器缺席）必须点名拒绝——静默回密文/明文都是假读数。"""
        from neurova.cognitive_layers.memory_layer.security import (
            EncryptionMethod,
            MemorySecurity,
        )

        noCipher = MemorySecurity(
            SecurityConfig(default_encryption=EncryptionMethod.NONE)
        )
        with pytest.raises(RuntimeError):
            noCipher.encrypt_sensitive_content("x", EncryptionMethod.FERNET)
        with pytest.raises(RuntimeError):
            noCipher.decrypt_sensitive_content("gAAAAAB", EncryptionMethod.FERNET.value)


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
