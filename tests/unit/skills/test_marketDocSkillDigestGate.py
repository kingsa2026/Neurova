# -*- coding: utf-8 -*-
"""注册表那条执行腿的构件闸（§6-383 票三甲案，用户 2026-10-22 拍）。

活体已证（`tests/manual/marketTicketThreeDigestPath.py`）：同一本账有两条执行腿，
`call_skill` 那条过闸、注册表那条（`SkillDocSkill.execute`，LLM 实际走的那条）**改一个字节
照原样把指令体交给模型，`checkArtifact` 被调 0 次**。本档钉的就是把同一道闸接到这条腿上：

- 钉过且相符 ⇒ 照常回指令体；
- 钉过但不符 / 目录没了 ⇒ **如实拒**（拒因取 `artifact_digest.refusalReason` 那一处，
  不在这里拼第二套文案），并且**指令体一个字节都不许进回执**；
- 没钉过（存量/旁路落地）⇒ 与 `call_skill` 同一口径的 TOFU：有落账回调就现算现钉并放行一次，
  没有回调就**拒**（`artifact_digest_unpinned`）——不许"没账可写所以放行"。
- `pinnedDigest=None` 是**刻意**的非生产口径（直接构造实例做单元实验），不跑闸；
  生产两个构造点（link 与冷启动 restore）必须传字符串，另有一格按 AST 钉住，
  否则这个默认值就成了静默旁路。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from tests import ast_scan

from neurova.security import artifact_digest
from neurova.skills import market_registry
from neurova.skills.market_registry import _build_executable_skill
from neurova.skills.skill_service import SkillService

SKILL_MD = """---
name: demo-skill
description: 演示技能
---

# 演示技能

按以下步骤执行任务…
"""


@pytest.fixture()
def skillDir(tmp_path):
    d = tmp_path / "agent-skills" / "demo--doc"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return d


@pytest.fixture()
def service(tmp_path):
    return SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))


def _run(skill):
    return asyncio.run(skill.execute({"task": "probe"}))


def _text(result):
    return str(getattr(result, "data", None) or getattr(result, "output", None) or "")


class TestTheGateIsOnTheRegistryLeg:
    def testCleanPinnedSkillStillReturnsItsInstructions(self, skillDir):
        pinned = artifact_digest.digestDir(skillDir)
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest=pinned)

        result = _run(built)

        assert result.success is True, getattr(result, "error", None)
        assert "按以下步骤执行任务" in _text(result)

    def testTamperedBytesAreRefusedAndNoInstructionEscapes(self, skillDir):
        pinned = artifact_digest.digestDir(skillDir)
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest=pinned)
        marker = "<!-- tampered -->"
        (skillDir / "SKILL.md").write_text(SKILL_MD + marker, encoding="utf-8")

        result = _run(built)

        assert result.success is False
        assert result.error == artifact_digest.REASON_MISMATCH, (
            "拒因必须取 artifact_digest 那一处，不在执行腿拼第二套文案")
        assert marker not in _text(result), "被篡改的指令体漏进了回执"

    def testMissingDirectoryIsNamedMissingNotMismatch(self, skillDir):
        pinned = artifact_digest.digestDir(skillDir)
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest=pinned)
        import shutil

        shutil.rmtree(skillDir)

        result = _run(built)

        assert result.success is False
        assert result.error == artifact_digest.REASON_MISSING

    def testTheGateRunsExactlyOncePerCall(self, skillDir, monkeypatch):
        pinned = artifact_digest.digestDir(skillDir)
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest=pinned)
        calls = []
        real = artifact_digest.checkArtifact

        def counting(root, pinnedValue, **kwargs):
            calls.append(str(root))
            return real(root, pinnedValue, **kwargs)

        monkeypatch.setattr(artifact_digest, "checkArtifact", counting)

        _run(built)

        assert len(calls) == 1, calls

    def testUnpinnedEntryPinsOnceThroughTheCallbackThenGuards(self, skillDir):
        seen = []
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest="",
                                        onPin=lambda digest: seen.append(digest))

        first = _run(built)
        assert first.success is True, getattr(first, "error", None)
        assert len(seen) == 1 and seen[0].startswith(artifact_digest.DIGEST_PREFIX), seen

        marker = "<!-- after-pin tamper -->"
        (skillDir / "SKILL.md").write_text(SKILL_MD + marker, encoding="utf-8")
        # 首钉之后，**这个实例自己**就该把这枚值当成口径（不靠调用方回填私有字段）
        second = _run(built)

        assert second.success is False
        assert second.error == artifact_digest.REASON_MISMATCH
        assert marker not in _text(second)

    def testUnpinnedWithoutACallbackIsRefusedNotSilentlyAllowed(self, skillDir):
        built = _build_executable_skill("demo--doc", "演示", skillDir, pinnedDigest="")

        result = _run(built)

        assert result.success is False
        assert result.error == artifact_digest.REASON_UNPINNED, (
            "没有落账回调就等于没有账可写——此时放行会把"
            "「没钉」洗成「钉过且相符」")

    def testUnmanagedConstructionKeepsLegacyBehaviourDeliberately(self, skillDir):
        """`pinnedDigest=None`＝直接构造做实验的口径，不跑闸；生产构造点不许走它。"""
        from neurova.skills.market_registry import SkillDocSkill

        skill = SkillDocSkill("demo--doc", skillDir, description="演示")

        result = _run(skill)

        assert result.success is True

    def testMappedExecutorIsUntouchedAndChecksNoDigest(self, monkeypatch):
        calls = []
        monkeypatch.setattr(artifact_digest, "checkArtifact",
                            lambda root, pinned: calls.append(root) or ("match", ""))
        built = _build_executable_skill("web-search", "搜索")
        assert built is not None
        assert calls == [], "映射型执行体不读盘上字节，不该被这道闸扫到"


class TestProductionBuildersCarryThePin:
    def _builderCalls(self, tree):
        """挑出对 `_build_executable_skill(` 的调用点，返回是否带了 pinnedDigest。"""
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "_build_executable_skill":
                found.append(any(kw.arg == "pinnedDigest" for kw in node.keywords))
        return found

    def testEveryProductionCallSitePassesThePin(self):
        """扫**整个 `neurova/`**：任何构造点不传 pin，都会落进 `None` 的静默旁路。"""
        package = Path(market_registry.__file__).resolve().parents[1]
        offenders = []
        checked = 0
        # 枚举走共享预算（filesUnder）：一次性全仓判据用私有 rglob 会把
        # 「代码总量」编码成墙钟上界（Issue #148 的根因形态）。
        for path in ast_scan.filesUnder(package):
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "_build_executable_skill" not in source:
                continue
            flags = self._builderCalls(ast_scan.transientTree(path))
            checked += len(flags)
            if any(flag is False for flag in flags):
                offenders.append(str(path.relative_to(package)))
        assert checked >= 2, ("构造点数比预期少（%d）：规则可能与代码脱节" % checked)
        assert offenders == [], (
            "这些文件的构造点没传 pinnedDigest ⇒ 执行腿的闸对它们形同虚设：%s" % offenders)

    def testTheDetectorCatchesAMissingKeyword(self):
        """变异对照：探测器必须抓得到"没传"，否则上一格恒绿。"""
        good = "x = _build_executable_skill('a', 'b', c, pinnedDigest=p)"
        bad = "x = _build_executable_skill('a', 'b', c)"

        assert self._builderCalls(ast.parse(good)) == [True]
        assert self._builderCalls(ast.parse(bad)) == [False]


class TestThePinCanBePersistedAtTheService:
    def testPinIsWrittenIntoTheManifestAndSurvivesReload(self, tmp_path, skillDir):
        service = SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))
        service._skills["demo--doc"] = {
            "id": "demo--doc", "name": "demo", "description": "", "version": "1.0.0",
            "enabled": True, "path": str(skillDir),
        }
        digest = artifact_digest.digestDir(skillDir)

        assert service.pinArtifactDigest("demo--doc", digest) is True

        reloaded = SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))
        assert reloaded._skills["demo--doc"][artifact_digest.DIGEST_FIELD] == digest

    def testPinningAnUnknownSkillSaysSoInsteadOfInventingAnEntry(self, tmp_path):
        service = SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))

        assert service.pinArtifactDigest("no-such-skill", "sha256:abc") is False
        assert "no-such-skill" not in service._skills
