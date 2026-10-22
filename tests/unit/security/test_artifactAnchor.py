# -*- coding: utf-8 -*-
"""根外锚：数据根之外的摘要副本（§6-388，票一甲①，用户 2026-10-22 拍）。

边界必须先写在判据里，免得这条能力被读成"防篡改"：

- 锚**不**防同权限攻击——能改构件与账本的人通常也能改锚；
- 它防的是**只动了数据根**的那类操作：整库恢复/快照回滚、以及"改完构件再把账本
  重钉一次"（后者正是 §6-176 那条「账本与被保护构件同根同权限」的直接后果）；
- 锚里没有这条 ⇒ 维持只读账本的旧读数（TOFU 语义不变），**不悄悄补写**；
- 锚坏了（解析失败/版本不认识）⇒ 改名隔离并响亮报，不把"读不懂"读成"没钉过"。

本档另钉两处接线：技能的钉写口（`SkillService.pinArtifactDigest` 与两处安装钉）要同时落锚；
锚写失败只出声、不回滚账本（账本那份仍是权威，锚缺只是整库回滚检测对它不成立）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from neurova.core import data_root
from neurova.security import artifact_digest

#: 导入期取一份**生产**的落点函数：`tests/conftest.py` 的 autouse 夹具会把
#: `anchorPath` 改指临时目录（避免跑测写真实主目录），所以断言生产形状要用这份原件。
_PRODUCTION_ANCHOR_PATH = artifact_digest.anchorPath


@pytest.fixture()
def anchorFile(tmp_path, monkeypatch):
    path = tmp_path / "outside-root" / "artifact_anchors.json"
    monkeypatch.setattr(artifact_digest, "anchorPath", lambda: path)
    return path


@pytest.fixture()
def artifactDir(tmp_path):
    d = tmp_path / "artifact"
    d.mkdir()
    (d / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    return d


class TestTheAnchorIsASeparateLanding:
    def testAnchorKeyIsChannelPrefixedAndClosed(self):
        assert artifact_digest.artifactKey("skill", "x") != artifact_digest.artifactKey("plugin", "x")
        with pytest.raises(ValueError):
            artifact_digest.artifactKey("mcp", "x")
        with pytest.raises(ValueError):
            artifact_digest.artifactKey("skill", "  ")

    def testTheChannelVocabularyIsExactlyTheTwoLedgers(self):
        assert artifact_digest.ANCHOR_CHANNELS == ("skill", "plugin"), (
            "加第三个通道要同时改两条账本的钉/验点与台账，不能只加一个字符串")

    def testAnchorPathSitsOutsideTheDataRoot(self):
        landing = _PRODUCTION_ANCHOR_PATH()
        dataRoot = Path(data_root.get_data_root()).resolve()

        assert ".neurova" in landing.parts, landing
        assert dataRoot not in landing.resolve().parents, (
            "锚落进了数据根：那样整库回滚会把构件、账本、锚一起回滚，等于没有锚")


class TestRoundTripAndFailureShapes:
    def testRecordThenCheckRoundTrip(self, anchorFile):
        digest = "sha256:" + "a" * 64

        assert artifact_digest.recordAnchor("skill:demo", digest) is True
        assert anchorFile.is_file()
        assert artifact_digest.checkAnchor("skill:demo", digest) == artifact_digest.STATUS_MATCH
        assert artifact_digest.checkAnchor("skill:demo", "sha256:" + "b" * 64) \
            == artifact_digest.STATUS_MISMATCH
        assert artifact_digest.checkAnchor("skill:other", digest) == artifact_digest.STATUS_UNPINNED

    def testCorruptAnchorIsQuarantinedAndLoud(self, anchorFile, caplog):
        anchorFile.parent.mkdir(parents=True)
        anchorFile.write_text("{broken", encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            anchors = artifact_digest.readAnchors()

        assert anchors == {}
        assert not anchorFile.exists(), "坏文件没被改名隔离，下一次成功写入会覆盖真数据"
        assert any("隔离" in rec.message or "无法解析" in rec.getMessage()
                   for rec in caplog.records), [r.getMessage() for r in caplog.records]

    def testUnknownVersionIsAlsoQuarantined(self, anchorFile, caplog):
        anchorFile.parent.mkdir(parents=True)
        anchorFile.write_text(json.dumps({"version": 999, "anchors": {"skill:x": "sha256:aa"}}),
                              encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            anchors = artifact_digest.readAnchors()

        assert anchors == {}
        assert not anchorFile.exists()


class TestTheAnchorGatesRePinning:
    def testLedgerMatchButAnchorMismatchIsRefused(self, artifactDir, anchorFile):
        """核心一格：改了构件、再把账本重钉一次——账本相符，锚不符 ⇒ 拒。"""
        actual = artifact_digest.digestDir(artifactDir)
        artifact_digest.recordAnchor("skill:demo", "sha256:" + "f" * 64)

        status, now = artifact_digest.checkArtifact(
            artifactDir, actual, anchorKey="skill:demo")

        assert status == artifact_digest.STATUS_MISMATCH
        assert now == actual

    def testNoAnchorFallsBackToLedgerOnly(self, artifactDir, anchorFile):
        actual = artifact_digest.digestDir(artifactDir)

        status, now = artifact_digest.checkArtifact(
            artifactDir, actual, anchorKey="skill:demo")

        assert status == artifact_digest.STATUS_MATCH, (
            "锚缺不该把存量条目挡在门外——那会把这条能力做成停机")

    def testMismatchStillReportsTheSameRefusalReason(self, artifactDir, anchorFile):
        artifact_digest.recordAnchor("skill:demo", "sha256:" + "f" * 64)
        actual = artifact_digest.digestDir(artifactDir)

        status, _ = artifact_digest.checkArtifact(artifactDir, actual, anchorKey="skill:demo")

        assert artifact_digest.refusalReason(status) == artifact_digest.REASON_MISMATCH


class TestSkillPinningAlsoWritesTheAnchor:
    def _service(self, tmp_path):
        from neurova.skills.skill_service import SkillService

        return SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))

    def testPinWritesBothLedgerAndAnchor(self, tmp_path, artifactDir, anchorFile):
        service = self._service(tmp_path)
        service._skills["demo"] = {"id": "demo", "name": "demo", "path": str(artifactDir)}
        digest = artifact_digest.digestDir(artifactDir)

        assert service.pinArtifactDigest("demo", digest) is True

        payload = json.loads(anchorFile.read_text(encoding="utf-8"))
        assert payload["anchors"]["skill:demo"] == digest

    def testAnchorFailureIsLoudButDoesNotRollBackTheLedger(self, tmp_path, artifactDir,
                                                          anchorFile, monkeypatch, caplog):
        service = self._service(tmp_path)
        service._skills["demo"] = {"id": "demo", "name": "demo", "path": str(artifactDir)}
        digest = artifact_digest.digestDir(artifactDir)

        def boom(*args, **kwargs):
            raise OSError("anchor disk refuses")

        monkeypatch.setattr(artifact_digest, "atomic_write_text", boom)

        with caplog.at_level(logging.ERROR):
            assert service.pinArtifactDigest("demo", digest) is True, (
                "锚写失败不该把已经落了账的钉回滚——账本那份仍是权威")
        assert service._skills["demo"][artifact_digest.DIGEST_FIELD] == digest
        assert any("锚" in rec.getMessage() for rec in caplog.records), (
            "锚写失败必须出声，否则运维会以为整库回滚检测对这条生效")
