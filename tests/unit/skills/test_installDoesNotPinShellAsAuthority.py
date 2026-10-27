# -*- coding: utf-8 -*-
r"""装侧不许把空壳钉成构件权威——§6-267 只修了 call 侧那一半，本批修写侧这一半（§6-289 第①条）。

复核实状（真咽喉现读，探针即用即删；两条读数）：
① 装一只"目录里只有 `manifest.json`"的包，`install_skill` 当场算 `digestDir(target_dir)`
   并写进账本 ⇒ `装完账本摘要 = sha256:38c1f9d9ca33236a…`，且**它等于那个空目录的现量**；
② 日后真把 `main.py` 补进同一个目录（就是 §6-186/批 35 之后"把字节接上"那条正路），
   `call_skill` 报 `artifact_digest_mismatch`，`expected_digest` 是那份"什么都没有"的摘要、
   `actual_digest` 是补进来的真字节 ⇒ **一次误钉把这条路永久钉死**。

同一根因在 §6-267（批 57）已经处理过 call 侧那一支：账本没钉且落盘无构件 ⇒ 不首钉、不落账。
但**装侧那一支一直在新生这种账本**——所以修在 call 侧只是止血，写侧才是生产该非法状态的上游
（教义第 1 条）。而读面（§6-272 甲案）今天已经把这条判成不可用，本批不动那条：
"看得见但标灰"与"账本里留一颗雷"是两件事。

刻意不做的两件（都写清楚，免得下一个人顺手）：
- **不删条目**：存量所有空壳会在下一次启动集体"蒸发"（§6-267 那条警告仍然成立），
  且用户不知道它曾存在、也无从卸载——本批只让摘要不出现，账本可见性一字不改（第 7 格钉着）。
- **不把 call 侧那一支并进来**：咽喉那一支问的是"有没有 `.py` 入口可以 exec"，
  与本批这个"盘上有没有构件字节"是两个问句；捏成一个会把指令型（只有 `SKILL.md`）
  在 call 时刻多写一次账本——那是把"合并同源"做成"合并异源"。

判据形状：第 5 格按 **AST 数定义与调用点**（一处定义、三处调用＝装侧两处＋读面一处），
双向钉——新增第二份定义即红，把某一处改回内联 `(dir / "SKILL.md").exists()` 也红；
第 6 格是探测器自己的反空转证明。
"""

from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path

import pytest

from tests import ast_scan

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neurova.security import artifact_digest as AD
from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService
from tests.ast_scan import parseSource

SKILL_MD = "# demo\n指令型技能的说明体。\n"
ENTRY = "def main(**kwargs):\n    return {'ok': True, 'saw': sorted(kwargs)}\n"
PREDICATE = "_hasArtifactBytes"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _svc(tmp_path, agent="b64-agent"):
    return SkillService(agent_id=agent, skills_dir=str(tmp_path / "installed"))


def _install(svc, tmp_path, skill_id, files):
    """按给定清单走真安装咽喉（`files` 为空 ⇒ 就是本机那种"只有 manifest.json"的空壳）。"""
    src = (tmp_path / "src") / skill_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0",
                    "source": "marketplace"}, ensure_ascii=False), encoding="utf-8")
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")
    result = svc.install_skill(str(src), skill_id=skill_id)
    assert result.get("success") is True, f"装配本身没成功，样本不成立：{result}"
    return svc.skills_dir / skill_id


def ledgerDigest(svc, skill_id):
    """读**账本本体**（落盘那份），不是内存投影——摘要的读者是装载前的执法接缝。"""
    ledger = json.loads(Path(svc.manifest_path).read_text(encoding="utf-8"))
    return str((ledger.get(skill_id) or {}).get(AD.DIGEST_FIELD) or "")


class TestShellInstallStaysUnpinned:
    def testShellInstallLeavesTheLedgerUnpinned(self, tmp_path):
        """本批的主红：盘上什么都没有 ⇒ 不许有一份"代表什么都没有"的构件权威。"""
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "b64-shell", files={})

        assert installed.is_dir() and sorted(p.name for p in installed.iterdir()) == ["manifest.json"], \
            f"样本不是空壳那一形：{installed}"
        assert ledgerDigest(svc, "b64-shell") == "", (
            f"装侧把空壳钉成了构件权威（{ledgerDigest(svc, 'b64-shell')[:24]}）——"
            "这份摘要不代表任何构件，却会把日后补进来的真字节判成篡改")

    def testRealBytesAddedAfterwardsAreNotRefusedAsTampering(self, tmp_path):
        """危害格（本批的价值就在这）：补上真字节之后必须跑得动，而不是永久被钉死。

        改前读数：`{'success': False, 'error': 'artifact_digest_mismatch',
        expected_digest=sha256:38c1…（空壳那份）, actual_digest=sha256:76f4…（真字节那份）}`。
        经**重开实例**再跑——摘要要走写→读闭环才算真的落进了账本（本卷记过的只写不读同族）。
        """
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "b64-shell", files={})
        (installed / "main.py").write_text(ENTRY, encoding="utf-8")

        reopened = _svc(tmp_path)
        outcome = asyncio.run(reopened.call_skill("b64-shell", q=1))

        assert outcome.get("success") is True, (
            f"补进来的真字节被一次误钉判成了篡改：{ {k: str(v)[:60] for k, v in outcome.items()} }")
        assert (outcome.get("result") or {}).get("ok") is True, f"跑的不是那份补进来的字节：{outcome}"
        assert ledgerDigest(reopened, "b64-shell").startswith(AD.DIGEST_PREFIX), (
            "有构件时才首钉——这一支没钉说明判定被整体关掉，那是把闸门拆了")

    def testShellInstallStaysVisibleInTheLedger(self, tmp_path):
        """不钉 ≠ 删条目：这条仍要在账本、列表与详情面看得见（且如实标不可用）。

        §6-267 那条警告仍成立：把空壳从账本摘掉会让存量条目在下一次启动集体"蒸发"，
        用户既不知道它曾存在也无从卸载。本批只让摘要不出现，可见性一字不改。
        """
        svc = _svc(tmp_path)
        _install(svc, tmp_path, "b64-shell", files={})

        reopened = _svc(tmp_path)
        info = reopened.get_skill_info("b64-shell")
        assert info is not None, "空壳条目从详情面消失了——那是另一种故障"
        assert any(s["id"] == "b64-shell" for s in reopened.list_skills()), "列表面看不见这条"
        availability = reopened.availabilityFor("b64-shell")
        assert availability.get("available") is False and availability.get("unavailableReason"), (
            f"读面对空壳的如实读数没了（本批不许动它）：{availability}")


class TestRealArtifactsStillPinned:
    @pytest.mark.parametrize("files", [
        {"main.py": ENTRY},
        {"SKILL.md": SKILL_MD},
    ])
    def testPackagesWithDiskArtifactsGetPinnedAtInstall(self, tmp_path, files):
        """对照格①：盘上真有字节时必须照钉——不许把"不钉"做成一律不钉。

        设计成改前改后都绿，钉的是"不许误伤"（形态集 251：合法归零那一腿要由合成样本续钉）。
        """
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "b64-real", files=files)

        pinned = ledgerDigest(svc, "b64-real")
        assert pinned.startswith(AD.DIGEST_PREFIX), f"有构件的包没被钉：{pinned!r}"
        assert pinned == AD.digestDir(installed), "钉的不是落位那份字节的摘要——口径漂了"

    def testPinnedPackageTamperedAfterwardsIsStillRefused(self, tmp_path):
        """对照格②：已钉的包被改动 ⇒ 摘要不符照旧拒。本批不许把这道闸弄松。"""
        svc = _svc(tmp_path)
        installed = _install(svc, tmp_path, "b64-real", files={"main.py": ENTRY})
        (installed / "main.py").write_text(
            "def main(**kwargs):\n    return {'sneaked': True}\n", encoding="utf-8")

        outcome = asyncio.run(_svc(tmp_path).call_skill("b64-real", q=1))

        assert outcome.get("success") is False and outcome.get("error") == AD.REASON_MISMATCH, (
            f"篡改那一条不报了（钉真字节这一半被本批改坏了）：{outcome}")


class TestPinDecisionComesFromOnePredicate:
    def _definitions(self):
        """`PREDICATE` 在全仓 `neurova/` 的定义点——取数走共享预算（§6-314 的 D22）。"""
        out = []
        for path, node in ast_scan.nodeScan(ast_scan.PRODUCTION_ROOT, ".py",
                                            ast_scan.textHints(PREDICATE)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == PREDICATE:
                out.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
        return out

    def _callSites(self, rel):
        src = (REPO / rel).read_text(encoding="utf-8")
        tree = parseSource(src, filename=rel)
        return [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == PREDICATE]

    def testOneDefinitionThreeCallSites(self):
        """一处定义、三处调用（装侧本地口＋装侧 hub 口＋读面那条判据），双向钉。

        少一处调用＝那一处又写回内联形状（`(d / "SKILL.md").exists() or _resolveEntryPoint(d)`），
        四处各写一份正是本批要收的东西；多一处定义＝第二份实装长出来了（教义第 7 条）。
        """
        defs = self._definitions()
        assert len(defs) == 1 and defs[0].startswith("neurova/skills/skill_service.py"), (
            f"`{PREDICATE}` 的实装应全仓一处且在 skill_service，实得 {defs}")

        sites = self._callSites("neurova/skills/skill_service.py")
        assert len(sites) == 3, (
            f"钉摘要那一问应有三处经同一条谓词（装两处＋读面一处），实得 {len(sites)} 处 {sites}——"
            "有一处改回内联判断了，四处各写一份就是本批收掉的东西")

    def _inlinedRestatements(self, source: str, where: str) -> list:
        """内联重述"盘上有没有构件"的表达式（`SKILL.md` 或 `_resolveEntryPoint` 拼起来的 BoolOp）。

        **唯一实装自己那一处不算**——豁免按 AST 判（函数名），不按行号也不按文件名：
        按行号会在下次编辑后错位，按文件名会把整个文件的复查一起放掉（形态集 223）。
        """
        tree = parseSource(source, filename=where)
        insideDefinition = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == PREDICATE:
                insideDefinition = {id(n) for n in ast.walk(fn)}
        hits = []
        for node in ast.walk(tree):
            if id(node) in insideDefinition or not isinstance(node, ast.BoolOp):
                continue
            names = {n.func.attr for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            consts = {n.value for n in ast.walk(node)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            if "_resolveEntryPoint" in names and "SKILL.md" in consts:
                hits.append(node.lineno)
        return hits

    def testNoInlinedRestatementOutsideTheDefinition(self):
        """这一问的口径全仓只许写在 `_hasArtifactBytes` 里；调用点一律经它。"""
        src = (REPO / "neurova/skills/skill_service.py").read_text(encoding="utf-8")
        hits = self._inlinedRestatements(src, "neurova/skills/skill_service.py")
        assert not hits, (
            f"有 {hits} 处把「盘上有没有构件」内联重述了一遍——四处各写一份就是本批收掉的东西，"
            "`testOneDefinitionThreeCallSites` 的三处基线也会变成虚的")

    def testDetectorBitesAnInlinedCopyOfTheQuestion(self):
        """豁免不是洞：把这条判据内联写回一处，探测器必须点名；实装内部那一处必须被它认下来。"""
        withInline = (
            "class S:\n"
            "    def _hasArtifactBytes(self, p):\n"
            '        return (p / "SKILL.md").exists() or self._resolveEntryPoint(p) is not None\n'
            "    def availability(self, p):\n"
            '        if (p / "SKILL.md").exists() or self._resolveEntryPoint(p):\n'
            "            return True\n")
        onlyDefinition = withInline.replace(
            "    def availability(self, p):\n"
            '        if (p / "SKILL.md").exists() or self._resolveEntryPoint(p):\n'
            "            return True\n",
            "    def availability(self, p):\n"
            "        return self._hasArtifactBytes(p)\n")

        assert len(self._inlinedRestatements(withInline, "synthetic.py")) == 1, (
            "调用点上重述的那一处没被点名——豁免把整个文件一起放掉了")
        assert self._inlinedRestatements(onlyDefinition, "synthetic.py") == [], (
            "干净形态被误报，说明豁免没按 AST 认函数身份")
        src = (REPO / "neurova/skills/skill_service.py").read_text(encoding="utf-8")
        tree = parseSource(src, filename="skill_service.py")
        bodies = [n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == PREDICATE]
        assert len(bodies) == 1 and any(isinstance(n, ast.BoolOp) for n in ast.walk(bodies[0])), (
            "实装里那一处不在了——上面两格的豁免就成了空口白话")
