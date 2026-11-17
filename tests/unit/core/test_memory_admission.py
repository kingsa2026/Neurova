"""S7 记忆准入轻量先行——红灯测试（先红后绿）。

三道必答（方案 S7 红灯定义）：
1. 含 key 样式（如 sk-test-fake-123 的明显假样式）的写入被拒，且有审计/日志/计数记录；
2. 普通偏好（"用户喜欢深色主题"）照常写入；
3. 准入清单提示词出现在写入链路提示面（拒收反馈内嵌清单，经 memory 技能
   store 的错误回显对模型可见）。

装配纪律：一律走生产装配点——MemCore.memory_manager setter 单点包一层
（installMemoryAdmission），测试不自装闸、不绕过装配点。
"""

import json
import logging

import pytest
from unittest.mock import MagicMock

from neurova.mem_core import MemCore


# ============================================================
# 测试辅助
# ============================================================

class RecordingMemoryManager:
    """最小记忆管理器替身：只真实记录 remember 调用，不做任何拦截。

    生产链路里 MemCore.memory_manager setter 会把它的 remember 包上准入闸；
    本替身保持"闸外"的原始语义，便于断言"写入是否真的发生"。
    """

    def __init__(self):
        self.remembered = []

    def remember(self, content, **kwargs):
        self.remembered.append((content, kwargs))
        return f"mem-{len(self.remembered)}"


def make_gated_memcore():
    """经生产装配点（MemCore.memory_manager setter）接入替身管理器。"""
    agent = MagicMock()
    agent.memory_manager = None
    agent.conversation_buffer = None
    mc = MemCore(agent)
    recording = RecordingMemoryManager()
    mc.memory_manager = recording  # setter 内完成单点包一层
    return mc, recording


FAKE_KEY_CONTENT = "我的 API key 是 sk-test-fake-1234567890，帮我存一下"


@pytest.fixture(autouse=True)
def restoreAdmissionPolicy():
    """每个用例后恢复默认 enforce 策略，避免放行通道测试污染后续用例。"""
    yield
    from neurova.memory_admission import POLICY_ENFORCE, setMemoryAdmissionPolicy

    setMemoryAdmissionPolicy(POLICY_ENFORCE)


# ============================================================
# 红灯 1：含 key 样式的写入被拒且有审计/日志/计数记录
# ============================================================

class TestSensitiveWriteRejected:
    def test_keyStyleWriteRejectedAndRecorded(self, caplog):
        from neurova.memory_admission import (
            MEMORY_ADMISSION_REJECT_ACTION,
            admissionCounters,
        )
        from neurova.security.audit_logger import AuditEventType, get_audit_logger

        mc, recording = make_gated_memcore()
        countersBefore = admissionCounters()

        with caplog.at_level(logging.WARNING, logger="neurova.memory_admission"):
            mc.save_conversation_memory(FAKE_KEY_CONTENT, "好的，我帮你记住了")

        # 拒收：一条都没写进记忆
        assert recording.remembered == [], f"含 key 内容被写入记忆：{recording.remembered}"

        # 计数可见
        countersAfter = admissionCounters()
        assert (
            countersAfter["sensitiveHits"] == countersBefore["sensitiveHits"] + 1
        ), "敏感命中计数未增加"
        assert countersAfter["rejected"] == countersBefore["rejected"] + 1, "拒收计数未增加"

        # 结构化日志可查（含命中规则，不含原文密钥）
        warningTexts = [rec.getMessage() for rec in caplog.records]
        assert any(
            "记忆准入拒收" in text and "openaiStyleKey" in text for text in warningTexts
        ), f"拒收结构化日志缺失：{warningTexts}"
        assert all(
            "sk-test-fake-1234567890" not in text for text in warningTexts
        ), "日志泄漏了原始密钥（应为脱敏摘要）"

        # 审计单源可查（neurova.security.audit_logger）
        entries = get_audit_logger().query(
            event_type=AuditEventType.SECURITY_EVENT, limit=200
        )
        admissionEntries = [
            e for e in entries if e.action == MEMORY_ADMISSION_REJECT_ACTION
        ]
        assert admissionEntries, "审计单源中没有记忆准入拒收记录"
        latest = admissionEntries[0]
        assert latest.details.get("rule") == "openaiStyleKey"
        assert "***" in str(latest.details.get("excerpt")), "审计摘要未脱敏"
        assert (
            "sk-test-fake-1234567890" not in json.dumps(latest.details)
        ), "审计详情泄漏原始密钥"

    def test_privateKeyAndTokenFamiliesAllRejected(self):
        from neurova.memory_admission import enforceMemoryAdmission

        samples = [
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...",
            "ghp_" + "a" * 20,
            "AKIAIOSFODNN7EXAMPLE",
            "Bearer abcdef1234567890abcdef",
            "password=hunter2secret",
            "数据库密码：p4ssw0rd-plain",
        ]
        for sample in samples:
            with pytest.raises(Exception, match="记忆准入拒收"):
                enforceMemoryAdmission(f"请记住 {sample}")

    def test_rejectionExcerptIsRedacted(self):
        from neurova.memory_admission import screenMemoryContent

        secret = "sk-test-fake-1234567890abcdef"
        hit = screenMemoryContent(f"key 是 {secret} 请记")
        assert hit is not None, "key 样式未被识别"
        assert hit.ruleName == "openaiStyleKey"
        assert secret not in hit.redactedExcerpt, "拒收摘要未脱敏"
        assert "***" in hit.redactedExcerpt, "拒收摘要缺少脱敏标记"

    def test_installIsIdempotent(self):
        from neurova.memory_admission import (
            installMemoryAdmission,
            admissionCounters,
        )

        recording = RecordingMemoryManager()
        installMemoryAdmission(recording)
        installMemoryAdmission(recording)  # 重复装配不叠加
        countersBefore = admissionCounters()
        with pytest.raises(Exception, match="记忆准入拒收"):
            recording.remember("key sk-test-fake-1234567890")
        assert recording.remembered == []
        countersAfter = admissionCounters()
        assert (
            countersAfter["sensitiveHits"] == countersBefore["sensitiveHits"] + 1
        ), "重复装配导致闸被叠加执行（计数跳了两格）"


# ============================================================
# 红灯 2：普通偏好照常写入
# ============================================================

class TestNormalPreferencePasses:
    def test_normalPreferenceWrittenAsUsual(self):
        from neurova.memory_admission import admissionCounters

        mc, recording = make_gated_memcore()
        countersBefore = admissionCounters()

        mc.save_conversation_memory("用户喜欢深色主题", "已记住你的偏好")

        assert len(recording.remembered) == 2, "普通偏好应照常写入用户+助手两条"
        assert recording.remembered[0][0] == "用户: 用户喜欢深色主题"
        assert recording.remembered[1][0] == "助手: 已记住你的偏好"
        countersAfter = admissionCounters()
        assert (
            countersAfter["rejected"] == countersBefore["rejected"]
        ), "普通偏好被误拒收"

    def test_everydayTextHasNoFalseHit(self):
        from neurova.memory_admission import screenMemoryContent

        for text in (
            "用户喜欢深色主题",
            "我喜欢在晚上跑步，偶尔喝咖啡",
            "密码学是一门有趣的学科",
            "项目的配置文件在 config 目录",
        ):
            assert screenMemoryContent(text) is None, f"误命中：{text}"


# ============================================================
# 红灯 3：准入清单提示词出现在写入链路提示面
# ============================================================

class TestChecklistPromptSurfaces:
    def test_checklistCoversAdmissionRules(self):
        from neurova.memory_admission import admissionChecklistPrompt

        checklist = admissionChecklistPrompt()
        for phrase in ("该记", "不记", "绝不记", "密钥", "偏好", "一次性感想", "中间"):
            assert phrase in checklist, f"准入清单缺少关键守则：{phrase}"

    def test_checklistReachesModelViaMemorySkillStoreError(self):
        """拒收反馈经 memory 技能 store 的错误回显对模型可见（写入链路提示面）。"""
        from neurova.memory_admission import admissionChecklistPrompt
        from neurova.skills.builtin.memory_executor import MemorySkillExecutor

        mc, _recording = make_gated_memcore()
        executor = MemorySkillExecutor(memory_manager=mc.memory_manager)

        result = executor.execute(
            {"action": "store", "content": "我的 key: sk-test-fake-1234567890"}
        )

        assert result.success is False, "含 key 的 store 应失败"
        checklist = admissionChecklistPrompt()
        distinctiveLine = next(
            line for line in checklist.splitlines() if "绝不记" in line
        )
        assert "记忆准入拒收" in result.error, "错误回显缺少可解释的拒收原因"
        assert distinctiveLine.strip() in result.error, "错误回显未内嵌准入清单"

    def test_rejectionMessageCarriesRuleAndChecklist(self):
        from neurova.memory_admission import (
            MemoryAdmissionRejected,
            admissionChecklistPrompt,
        )

        mc, _recording = make_gated_memcore()
        with pytest.raises(MemoryAdmissionRejected) as excinfo:
            mc.memory_manager.remember(FAKE_KEY_CONTENT)
        assert "openaiStyleKey" in str(excinfo.value), "异常未点名命中规则"
        assert "sk-test-fake-1234567890" not in str(excinfo.value), "异常泄漏原始密钥"
        distinctiveLine = next(
            line
            for line in admissionChecklistPrompt().splitlines()
            if "绝不记" in line
        )
        assert distinctiveLine.strip() in str(excinfo.value), "异常未内嵌准入清单"


# ============================================================
# 放行通道：宁可拒收可查，不可静默放行
# ============================================================

class TestReleaseChannel:
    def test_auditOnlyPolicyReleasesButRecords(self):
        from neurova.memory_admission import (
            POLICY_AUDIT_ONLY,
            admissionCounters,
            setMemoryAdmissionPolicy,
        )

        setMemoryAdmissionPolicy(POLICY_AUDIT_ONLY)
        mc, recording = make_gated_memcore()
        countersBefore = admissionCounters()

        mc.save_conversation_memory(FAKE_KEY_CONTENT, "好的")

        assert len(recording.remembered) == 2, "audit 策略下应放行写入"
        countersAfter = admissionCounters()
        assert (
            countersAfter["auditOnlyPassed"] == countersBefore["auditOnlyPassed"] + 1
        ), "audit 策略放行未计数（静默放行）"
        assert (
            countersAfter["rejected"] == countersBefore["rejected"]
        ), "audit 策略下不应计拒收"

    def test_unknownPolicyRejected(self):
        from neurova.memory_admission import setMemoryAdmissionPolicy

        with pytest.raises(ValueError):
            setMemoryAdmissionPolicy("whatever")
