# -*- coding: utf-8 -*-
"""MemorySecurity 主链接线（审计 3.3-5 用户拍板，2026-11-17）：

memory_layer/security.py（731 行）此前主链零消费——加密/敏感检测零生产调用、
遗忘走 memory_enhancement 直调 manager 绕过审计。拍板接线：
1. remember 写入咽喉接 `screenForStorage`：检测证据必记（metadata._security）；
   处置按 SecurityConfig.sensitive_write_action——log_only（默认，零内容漂移，
   与认知安全门 observe 同姿态）/ mask（敏感段掩码）/ encrypt（Fernet 全文，
   运维显式开启）；
2. 遗忘链统一入口：memory_enhancement 的 forget 端点改走
   `MemorySecurity.forget_memory`（审计日志留痕）。

fail-open 与认知安全门同姿态：安全面故障不阻断记忆写入。
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.security import (
    EncryptionMethod,
    SecurityConfig,
    get_memory_security,
    reset_memory_security,
)

# 一段确定命中内置规则的高敏感样本（API Key 形态）
SECRET_SAMPLE = "我的服务器密钥是 sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="sec_test_agent",
        user_id="sec_test_user",
    )


@pytest.fixture(autouse=True)
def _reset_security_singleton():
    reset_memory_security()
    yield
    reset_memory_security()


def _config(action: str) -> SecurityConfig:
    return SecurityConfig(sensitive_write_action=action)


class TestRememberSecurityScreening:
    def test_remember_records_security_metadata_log_only(self, manager):
        """默认 log_only：内容零漂移，检测证据必落 metadata._security。"""
        get_memory_security(_config("log_only"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == SECRET_SAMPLE, "log_only 态内容必须零漂移"
        sec = (mem.get("metadata") or {}).get("_security")
        assert sec, "敏感检测证据必须落 metadata._security（主链零消费根治）"
        assert sec["sensitivity"] in ("high", "critical"), f"API Key 应判高敏感，实得 {sec}"
        assert sec["patterns"], "必须记录命中的规则名"

    def test_benign_content_records_no_security_block(self, manager):
        get_memory_security(_config("log_only"))
        mem_id = manager.remember("用户喜欢蓝色主题", auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert not (mem.get("metadata") or {}).get("_security"), (
            "无敏感命中的内容不得塞空证据块（metadata 只记真实发现）"
        )

    def test_remember_mask_action_masks_secret_segment(self, manager):
        get_memory_security(_config("mask"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] != SECRET_SAMPLE, "mask 态敏感原文不得明文落库"
        assert "sk-proj-AAAA" not in mem["content"], "密钥前缀不得残留在落库内容"
        assert "服务器密钥" in mem["content"], "掩码只动敏感段，正文其余部分保留"
        sec = (mem.get("metadata") or {}).get("_security")
        assert sec and sec.get("encrypted") == EncryptionMethod.MASK.value

    def test_remember_encrypt_action_roundtrip(self, manager):
        get_memory_security(_config("encrypt"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        sec = (mem.get("metadata") or {}).get("_security")
        assert sec and sec.get("encrypted") == EncryptionMethod.FERNET.value
        # 读侧透明解密（用户拍板 2026-11-17）：get_memory 读出的是原文，
        # 密文只存在于落库与内存态内部（写回链一致性）。
        assert mem["content"] == SECRET_SAMPLE, "encrypt 态读路径必须透明解密回原文"

    def test_fail_open_on_security_failure(self, manager, monkeypatch):
        """安全面故障放行原文——记忆不因安全面异常而丢（与认知安全门同姿态）。"""
        def _boom(*a, **kw):
            raise RuntimeError("模拟安全面故障")

        monkeypatch.setattr(
            "neurova.cognitive_layers.memory_layer.security.MemorySecurity.screenForStorage",
            _boom,
        )
        get_memory_security(_config("mask"))
        mem_id = manager.remember(SECRET_SAMPLE, auto_analyze_emotion=False)
        mem = manager.get_memory(mem_id, agent_wide=True)
        assert mem["content"] == SECRET_SAMPLE, "安全面故障必须放行原文（fail-open）"


class TestForgetUnifiedEntry:
    def test_forget_records_audit_log(self, manager):
        """遗忘走统一入口后，审计日志必须留 FORGET 记录（旧直调路径无审计）。"""
        security = get_memory_security(_config("log_only"))
        security.set_memory_manager(manager)

        mem_id = manager.remember("待遗忘记忆", auto_analyze_emotion=False)
        result = security.forget_memory(mem_id, permanent=False)

        assert result["success"] is True
        assert manager.get_memory(mem_id, agent_wide=True).get("lifecycle_stage") == "forgotten"
        logs = security.get_access_log(memory_id=mem_id)
        assert logs, "统一入口必须留访问审计（原直调 manager.forget 零审计）"

    def test_forget_missing_memory_reports_failure(self, manager):
        security = get_memory_security(_config("log_only"))
        security.set_memory_manager(manager)
        result = security.forget_memory("mem_nonexistent", permanent=False)
        assert result["success"] is False, "不存在的记忆必须显式失败（禁假成功）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
