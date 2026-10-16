# -*- coding: utf-8 -*-
r"""随包内置的真资产包必须能装上——且是靠"资产自己不再有危险形状"装上的（用户裁甲＋改资产）。

三张判据钉三件事，方向各不相同：

1. **门侧闭环**：真 zip 解出来过安装门 ⇒ `blocked is False`。今天它是 409，拦点有两处，
   分别由本批第二刀（argv 形态改判形状，§6-2xx）与第三刀（资产里那处裸名 `compile(`）解决。
   这格断的是**两刀合起来的得数**，所以它的红不说明哪一刀没生效——下面两格各断一刀。
2. **资产侧形状**：包内那份自检脚本 `scripts/package_check.py` 的语法校验步骤仍必须在
   （断 `ast.parse` 调用在场），但不得再用裸名 `compile(`。只断"没有 compile"会被
   **删掉整步检查**骗过去（形态集 235 的同族：换了产生读数的来源，断言却只管读数没变）。
3. **不许开后门**：裁决收窄之后，白名单面仍然必须是空的——本批改的是**形状判定**与**资产**，
   不是给这只包开豁免（用户口径：动手面在 zip 内容，禁开白名单）。
"""
from __future__ import annotations

import ast
import io
import zipfile
from pathlib import Path

import pytest

from neurova.skills.market_importer import read_builtin_bundle
from neurova.skills.skill_install_gate import reset_install_gate_scanner, scan_skill_for_install

BUNDLE_NAME = "adaptive-presentation-studio.zip"
SKILL_ID = "builtin--adaptive-presentation-studio"
#: 包内那份自检脚本；它用裸名 `compile(` 给自己的 scripts/*.py 做语法校验。
SELF_CHECK_MEMBER = "scripts/package_check.py"
#: 真包里 argv 形态起进程的读数条数（本机现读 4 条：render_slides / quick_start / run_pipeline / self_test）。
EXPECTED_ARGV_READINGS = 4


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


@pytest.fixture()
def unpacked(tmp_path: Path) -> Path:
    payload = read_builtin_bundle(BUNDLE_NAME)
    assert payload, f"包内资产缺失，本档全部格失去根据：{BUNDLE_NAME}"
    dest = tmp_path / SKILL_ID
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(dest)
    return dest


class TestGateAcceptsTheShippedAsset:
    def test_bundleInstallsThroughTheGate(self, unpacked):
        verdict = scan_skill_for_install(SKILL_ID, str(unpacked))
        assert verdict.get("blocked") is False, (
            f"真资产包仍被门拒：{verdict.get('error')}")

    def test_argvReadingsAreStillOnTheReportFace(self, unpacked):
        """放行不许是把读数删掉：起进程那 4 条仍得在报告面上，只是不再参与裁决。"""
        verdict = scan_skill_for_install(SKILL_ID, str(unpacked))
        readings = [f for f in verdict.get("findings") or [] if f.get("rule_id") == "subprocess_call"]
        assert len(readings) >= EXPECTED_ARGV_READINGS, (
            f"报告面只剩 {len(readings)} 条起进程读数（改前 {EXPECTED_ARGV_READINGS} 条）——"
            "裁决收窄被做成了读数消失")
        assert all(f.get("severity") == "low" for f in readings), (
            f"这些读数不再参与裁决却仍标着 {sorted({f.get('severity') for f in readings})}")


class TestAssetCarriesNoBareDynamicExecutionShape:
    def _memberSource(self) -> str:
        payload = read_builtin_bundle(BUNDLE_NAME)
        assert payload, f"包内资产缺失：{BUNDLE_NAME}"
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            return zf.read(SELF_CHECK_MEMBER).decode("utf-8")

    def test_syntaxCheckStepIsStillThereAndNoLongerUsesBareCompile(self):
        """语法校验这一能力不许被删——它只是换了等价写法（`ast.parse` 同样抛 SyntaxError）。"""
        source = self._memberSource()
        tree = ast.parse(source, filename=SELF_CHECK_MEMBER)
        bareCompile = [n.lineno for n in ast.walk(tree)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "compile"]
        assert not bareCompile, (
            f"包内第 {bareCompile} 行仍是裸名 compile( ——安装门按 critical 拒它是正确的")
        astParse = [n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "parse" and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "ast"]
        assert astParse, (
            "语法校验步骤被删掉了：这是把门的问题'抹平'而不是改掉危险形状，教义第 2 条")


class TestGateNotWeakenedByThisBatch:
    def testInjectingABareExecIntoTheSameTreeStillDenies(self, unpacked):
        """往同一棵树里加一条真裸名 `exec(...)`，必须照样被拒。

        这格与上面那格**必须同向绿**：只"能装"绿＝门被放宽了；只这格绿＝资产仍然装不上。
        本批动过两处裁决面（argv 形态降级 + 资产改掉裸名 compile），所以这道锁是必需的。
        """
        probe = unpacked / "scripts" / "_injectedProbe.py"
        probe.write_text("def go(payload):\n    return exec(payload)\n", encoding="utf-8")

        verdict = scan_skill_for_install(SKILL_ID, str(unpacked))
        assert verdict.get("blocked") is True, (
            "包内塞进真裸名 exec 却仍然放行——降级被做成了把门拆掉")
        blocking = [f for f in verdict.get("findings") or []
                    if f.get("rule_id") == "dangerous_exec" and f.get("severity") in ("critical", "high")]
        assert blocking, f"拦它的必须是 dangerous_exec，实得 {[f.get('rule_id') for f in verdict.get('findings') or []][:8]}"


class TestNoBackdoorWasOpened:
    def test_thisBundleIsNotWhitelisted(self, unpacked):
        """本批收窄的是形状判定，不是给这只包开豁免——它不许出现在白名单里。

        只断"这只包不在名单上"，不断"名单是空的"：后者会随别档在同一次跑测里
        `add` 过一条而误红（判据不许依赖执行顺序）。真闸没松那一半由
        `test_subprocessCallJudgesCommandShape.py` 的照旧拦侧钉。
        """
        from neurova.security.skill_scanner import WhitelistManager

        manager = WhitelistManager()
        assert not manager.is_whitelisted(SKILL_ID), (
            f"这只真资产包被加进了白名单：{manager.list_all()}——用户口径是改资产，禁开白名单")

        verdict = scan_skill_for_install(SKILL_ID, str(unpacked))
        assert verdict.get("blocked") is False and verdict.get("action") == "allow", (
            f"没豁免却被放行是靠别的什么？读数不自洽：{verdict}")

