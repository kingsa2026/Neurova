r"""未钉的**空壳条目**不许被首钉成权威（§6-259 末段"假可得"那格的写侧污染半区）。

撞见过程（现读实据）：本机 `data/agents/default/skills/manifest.json` 里有一条
`builtin--adaptive-presentation-studio`，`enabled: true` 而它的落盘目录里**只有 manifest.json、0 个 .py**
（mtime 2026-10-06，早于真字节那批 `66030ba1`＝10-13 ⇒ 旧代码留下的陈态，今天的 `install_skill`
在门拦下时删 `.incoming` 且不建 `target_dir`，造不出这一形）。真正的代码缺陷在**读一遍就写一遍**：
`call_skill` 里构件摘要的对账发生在入口判定**之前**（`skill_service.py:1696-1715` 在 `:1717-1727` 前面），
而未钉分支是"现算现钉并放行一次"——于是每一次调用这只空壳，都会把**空壳的摘要**钉进账本并落盘，
然后才在下一行报 `No entry point found`。后果有两层：① 账本被一份不代表任何构件的摘要占住；
② 日后真把字节补进那个目录，`checkArtifact` 会拿这份空壳摘要判**篡改**——一次无害的误点
就把"以后装上了"这条路钉死。

修法只在写侧的次序上收：入口判定抽成一处（`_resolveEntryPoint`），未钉分支**只有在该目录真有可执行
构件时**才首钉落账。已钉条目的比对次序一字不动——篡改（含"把入口文件删了"这一形）仍先报摘要不符，
不让"没入口"盖掉"被改过"这个更准的读数。

不在本格范围（读面显示什么属产品语义，另一次裁定）：列表/详情/工具 schema/目录面把这条画成"可得"
——它们只认账本的 `enabled`（`market_registry.py:376-379` 甚至兜底注册一个 `status=ACTIVE` 的裸基类，
点到才 `NotImplementedError`）。
"""
from __future__ import annotations

import ast
import asyncio
import io
import json
from pathlib import Path

import pytest

from neurova.security import artifact_digest as AD
from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
SERVICE_SRC = REPO / "neurova" / "skills" / "skill_service.py"

SKILL_MD = "# helper\n最小可执行技能说明。\n"
MAIN_BODY = "def main(**kwargs):\n    return {'ok': True}\n"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _makeSrc(base: Path, skillId: str) -> Path:
    src = base / skillId
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skillId, "name": skillId, "version": "1.0.0"}), encoding="utf-8")
    (src / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (src / "main.py").write_text(MAIN_BODY, encoding="utf-8")
    return src


def _readLedger(svc: SkillService) -> dict:
    """读**账本本体**而不是 `get_skill_info`——后者是一份投影，看不到摘要那一格。"""
    return json.loads(io.open(svc.manifest_path, encoding="utf-8").read())


def _installedRealSkill(tmp_path, skillId="shell-b57"):
    """走真装配点装一个真技能，返回 (service, 落盘目录)。"""
    svc = SkillService(agent_id="shell-b57-agent", skills_dir=str(tmp_path / "installed"))
    result = svc.install_skill(str(_makeSrc(tmp_path / "src", skillId)))
    assert result.get("success") is True, result
    return svc, svc.skills_dir / skillId


def _stripToShellShape(svc: SkillService, skillId: str, *, dropEntryFiles: bool) -> None:
    """把刚装好的条目退成 10-06 本机那一形：账本里剥掉摘要（存量没有这一格），
    落盘目录里删掉可执行构件（只留记账件 manifest.json）。"""
    ledger = _readLedger(svc)
    ledger[skillId].pop(AD.DIGEST_FIELD, None)
    io.open(svc.manifest_path, "w", encoding="utf-8").write(json.dumps(ledger, ensure_ascii=False))
    if dropEntryFiles:
        installed = svc.skills_dir / skillId
        for name in ("main.py", "SKILL.md"):
            victim = installed / name
            if victim.exists():
                victim.unlink()
        assert list(installed.glob("*.py")) == [], "空壳没造成，样本不成立"


def _reopen(svc: SkillService) -> SkillService:
    """另起一个实例读回同一份账本——生产里这就是"重启后从账本读回"那条路。"""
    return SkillService(agent_id=svc.agent_id, skills_dir=str(svc.skills_dir))


class TestUnpinnedShellIsNotPinnedAsAuthority:
    def test_callingAnUnpinnedShellDoesNotWriteADigest(self, tmp_path):
        """本批的红：调用空壳 ⇒ 如实拒，而**账本不许多出一份摘要**。"""
        svc, installed = _installedRealSkill(tmp_path)
        skillId = "shell-b57"
        _stripToShellShape(svc, skillId, dropEntryFiles=True)

        reopened = _reopen(svc)
        result = asyncio.run(reopened.call_skill(skillId))

        assert result.get("success") is False, f"空壳被当成可执行技能跑通了：{result}"
        after = _readLedger(svc)[skillId]
        assert AD.DIGEST_FIELD not in after, (
            "空壳的摘要被首钉进账本了——日后真补上字节会被这份不代表任何构件的读数判篡改："
            f"{after.get(AD.DIGEST_FIELD)}")

    def test_callingTheSameShellTwiceStillLeavesTheLedgerUntouched(self, tmp_path):
        """读数面复证：污染不是一次性的，是**每次调用写一次**。"""
        svc, _ = _installedRealSkill(tmp_path, "shell-b57b")
        _stripToShellShape(svc, "shell-b57b", dropEntryFiles=True)
        reopened = _reopen(svc)
        for _ in range(2):
            assert asyncio.run(reopened.call_skill("shell-b57b")).get("success") is False
        assert AD.DIGEST_FIELD not in _readLedger(svc)["shell-b57b"]

    def test_unpinnedRealSkillStillPinsOnceAndRuns(self, tmp_path):
        """对照格（不许误伤）：未钉但**有可执行构件**的存量条目，TOFU 首钉一次并照常放行——
        这条语义一字不能动，本批改的只是"没有构件就别钉"。"""
        svc, _ = _installedRealSkill(tmp_path, "real-b57")
        _stripToShellShape(svc, "real-b57", dropEntryFiles=False)

        reopened = _reopen(svc)
        result = asyncio.run(reopened.call_skill("real-b57"))

        assert "安全扫描" not in str(result.get("error") or "") and \
            "digest" not in str(result.get("error") or "").lower(), f"真技能被摘要环节拦了：{result}"
        after = _readLedger(svc)["real-b57"]
        assert after.get(AD.DIGEST_FIELD), f"首钉没发生，TOFU 那条腿被改断了：{list(after)}"


class TestPinnedComparisonKeepsPrecedence:
    def test_tamperedBytesStillRefuseOnDigestNotOnEntryPoint(self, tmp_path):
        """已钉条目被改（把入口文件删掉这一形）⇒ 必须先报**摘要不符**，不许被"没入口"盖过去。

        这一格钉的是次序：本批把入口判定提到首钉之前，如果顺手把整段比对往后挪，
        "篡改"就读成"缺入口"了——那是把一个更准的读数换成更差的（教义第 2 条的反面）。
        """
        svc, installed = _installedRealSkill(tmp_path, "tamper-b57")
        assert _readLedger(svc)["tamper-b57"].get(AD.DIGEST_FIELD), "装配后本就该钉好，样本不成立"
        (installed / "main.py").unlink()

        reopened = _reopen(svc)
        result = asyncio.run(reopened.call_skill("tamper-b57"))

        assert result.get("success") is False, "删掉入口文件的已钉技能竟跑通了"
        refused = str(result.get("error") or "")
        assert "entry point" not in refused.lower(), (
            f"篡改被读成『没入口』了，摘要比对让位给后一步：{refused}")
        assert result.get("expected_digest") and result.get("actual_digest"), (
            f"摘要不符的结构化拒因缺字段（后来人无法判是谁改的）：{result}")


class TestEntryPointResolutionIsSingleSourced:
    def _bodiesWithBothShapes(self, source: str):
        """找出**同时**含 `"main.py"` 字面量与 `glob(...)` 调用的函数体——入口判定该只有一处。"""
        hits = []
        for node in ast.walk(parseSource(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            literals = {getattr(x, "value", None) for x in ast.walk(node)
                        if isinstance(x, ast.Constant) and isinstance(x.value, str)}
            globs = [x for x in ast.walk(node)
                     if isinstance(x, ast.Call) and getattr(x.func, "attr", None) == "glob"]
            if any(str(v).endswith("main.py") for v in literals) and globs:
                hits.append(node.name)
        return hits

    def test_serviceHasExactlyOneEntryPointResolver(self):
        hits = self._bodiesWithBothShapes(io.open(SERVICE_SRC, encoding="utf-8").read())
        assert hits == ["_resolveEntryPoint"], (
            f"入口判定散在 {len(hits)} 处：{hits}——两处就会各自演化，未钉分支问的那一份"
            "和执行那一份可能不是同一个答案")

    def test_detectorSeesTheShapeAndNotTheWord(self):
        """反空转格：探测器必须真认得这个形状，否则上一条绿得没道理。"""
        sample = (
            "def _probe():\n"
            "    p = Path('x') / 'main.py'\n"
            "    for f in p.parent.glob('*.py'):\n"
            "        return f\n"
            "def unrelated():\n"
            "    return 1\n"
        )
        assert self._bodiesWithBothShapes(sample) == ["_probe"], self._bodiesWithBothShapes(sample)
