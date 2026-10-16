# -*- coding: utf-8 -*-
r"""安装门的两条形状规则必须判**代码形态**，不判字面串（§6-259，用户裁甲）。

撞见过程（真产物现读，不抄旧账）：仓内自带的 `market_bundles/adaptive-presentation-studio.zip`
一直在安装门上被拒，旧票面写的是"自带 .py 的 27× `exec(` + 4× subprocess 属真代码形状"。逐条读
**证据行**才发现：那 27 条 `dangerous_exec` 里 **26 条的证据行是 `re.compile(...)`** ——
规则本体 `r"\b(exec|eval|compile)\s*\("` 里 `.` 与 `c` 之间 `\b` 照样成立，于是"正则预编译"
被当成 critical 级危险执行；而门走 `ScanPolicy.DENY`（critical **和 high** 都参与裁决），
critical 命中直接决定命运。另有 2 条 `dangerous_path_traversal`（high）落在 `.mjs` 的
**ES 相对导入** `from "../…/runtime_helpers.mjs"` 上——那是模块说明符，不是文件系统路径。

本格钉的是"窄化之后不许把门关掉"这件事的**两侧**：

- 误判侧必须不再翻红：`re.compile(` / ES 相对导入 / 数据字面量里的 `"../x"` ⇒ 放行；
- 真形态侧必须照旧翻红：裸 `exec(`、`eval(`、`compile(`，以及**文件系统 API 参数里**的 `..`。
  窄化不降低实际安全性还有一条结构性理由：真防线在 `neurova/security/safe_archive.py` 的
  `_resolve_within`（成员名归一化后仍须在目标目录内，显式拦 `..`），扫描器这条行级正则只是**信号**，
  把信号打在无害形态上只会淹没真信号——这才是本批要修的。
- 第 7 格钉"拒因文本只准念参与裁决的条目"：今天的 `error` 串取的是 `findings[:5]`，
  会把不参与裁决的读数当拒因念出去（回执不诚实的同族）。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from neurova.security.skill_scanner import SkillScanner, ScanPolicy, blockingFindings

from tests import execShapes

REPO = Path(__file__).resolve().parents[3]
BUNDLE = REPO / "neurova" / "skills" / "market_bundles" / "adaptive-presentation-studio.zip"

SKILL_MD = "# demo\n用于安装门读数的最小技能包。\n"

#: 每只合成包：{相对路径: 内容}。**这些串只是被扫描的字节**——落成 tmp 文件后从不被 import、
#: 也不被执行；本档读的始终是扫描器给出的读数（写进真 `exec/eval` 是为了钉"真形态照旧拦"）。
PACKAGES = {
    "regexPrecompile": {"run.py": 'import re\nDATE = re.compile(r"日期|date", re.I)\n'},
    "bareExec": {"run.py": "data = {}\nexec('x = 1', data)\n"},
    "bareEval": {"run.py": "print(eval('1 + 1'))\n"},
    "bareCompile": {"run.py": 'compile("x = 1", "<str>", "exec")\n'},
    "moduleRelativeImport": {"helper.mjs":
                             'import { load } from "../container_tools/runtime_helpers.mjs";\n'
                             'export const go = () => load();\n'},
    "dataLiteralRelativePath": {"spec.py": 'THUMB = {"previewPng": "../assets/previews/slide-01.png"}\n'},
    "escapingOpen": {"run.py": 'open("../../etc/passwd", "r").read()\n'},
    "escapingJoin": {"run.py": 'from pathlib import Path\nPath(OUT) / "../escape"\n'},
    "escapingExtract": {"run.py": 'import zipfile\nzipfile.ZipFile(z).extract("../evil.txt")\n'},
    "clean": {"run.py": "def go(x):\n    return x + 1\n"},
}


def buildPackage(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    for rel, text in PACKAGES[name].items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return dest


@pytest.fixture()
def gate():
    """安装门的同一套策略（DENY），不另写一份裁决口径。"""
    scanner = SkillScanner(workspace_path=".")
    scanner.policy = ScanPolicy.DENY
    return scanner


def verdict(gate, tmp_path: Path, name: str) -> dict:
    return gate.scan_skill(name, str(buildPackage(tmp_path, name)))


# ── 误判侧：修后必须放行 ──────────────────────────────────────────────────────

def testRegexPrecompileIsNotCodeExecution(gate, tmp_path):
    """`re.compile(` 是正则预编译，不是动态执行——它不得决定一次安装的死活。"""
    res = verdict(gate, tmp_path, "regexPrecompile")
    hits = [f for f in blockingFindings(res) if f.rule_id == "dangerous_exec"]
    assert not hits, (
        f"属性调用被当成危险执行：{[(f.file_path, f.evidence) for f in hits]}")
    assert res.passed is True, f"只含 re.compile( 的包仍被拦：{[f.rule_id for f in blockingFindings(res)]}"


def testModuleRelativeImportIsNotPathTraversal(gate, tmp_path):
    """.mjs 里的 `from "../x.mjs"` 是 ES 模块说明符，不是拿去落地的文件系统路径。"""
    res = verdict(gate, tmp_path, "moduleRelativeImport")
    hits = [f for f in blockingFindings(res) if f.rule_id == "dangerous_path_traversal"]
    assert not hits, f"ES 相对导入被判成路径遍历：{[(f.file_path, f.evidence) for f in hits]}"
    assert res.passed is True, f"只含模块相对导入的包仍被拦：{[f.rule_id for f in blockingFindings(res)]}"
    readings = [f for f in res.findings if f.rule_id == "dangerous_path_traversal"]
    assert readings and all(f.severity == "low" for f in readings), (
        f"模块说明符这条读数的形状不对：{[(f.severity, f.evidence) for f in readings]}")


def testDataLiteralRelativePathIsNotTraversal(gate, tmp_path):
    """数据字面量里的 `"../assets/x.png"` 不经过任何文件系统调用——它是内容，不是落点。"""
    res = verdict(gate, tmp_path, "dataLiteralRelativePath")
    hits = [f for f in blockingFindings(res) if f.rule_id == "dangerous_path_traversal"]
    assert not hits, f"数据串里的相对路径被判成遍历：{[(f.file_path, f.evidence) for f in hits]}"
    assert res.passed is True
    # 但读数不许消失：降级不是删除（批 37 的口径），报告面还得看得见这条相对路径引用
    readings = [f for f in res.findings if f.rule_id == "dangerous_path_traversal"]
    assert readings and all(f.severity == "low" for f in readings), (
        f"读数被删了或没降级：{[(f.severity, f.evidence) for f in readings]}")
    assert (res.metadata or {}).get("blocking_rule_count") == 0, (
        f"blocking_rule_count 与 passed 不自洽：{res.metadata}")


# ── 真形态侧：窄化之后必须照旧拦 ──────────────────────────────────────────────

@pytest.mark.parametrize("name", ["bareExec", "bareEval", "bareCompile"])
def testRealDynamicExecutionStillDenies(gate, tmp_path, name):
    """裸名 `exec/eval/compile` 照旧 critical ⇒ 拦。这一半不许随窄化一起松掉。"""
    res = verdict(gate, tmp_path, name)
    assert res.passed is False, f"{name} 不拦了——窄化越界到了真动态执行面"
    assert any(f.rule_id == "dangerous_exec" for f in blockingFindings(res)), (
        f"{name} 拦了，但拦的不是 dangerous_exec：{[f.rule_id for f in blockingFindings(res)]}")


@pytest.mark.parametrize("name", ["escapingOpen", "escapingJoin", "escapingExtract"])
def testEscapingPathInFilesystemCallStillDenies(gate, tmp_path, name):
    """`..` 出现在**要拿去打开/拼接/解包的路径**里 ⇒ 照旧拦（这才是规则原本想抓的东西）。"""
    res = verdict(gate, tmp_path, name)
    hits = [f for f in blockingFindings(res) if f.rule_id == "dangerous_path_traversal"]
    assert hits, f"{name} 的真遍历形态不再被点名：{[(f.rule_id, f.evidence) for f in blockingFindings(res)]}"
    assert res.passed is False, f"{name} 该被拦却放行"


def testCleanPackageStillPasses(gate, tmp_path):
    """反向控制：干净包必须过——上面几条"仍拦"若连正常包也拦，等于什么都没修。"""
    res = verdict(gate, tmp_path, "clean")
    assert res.passed is True, f"干净包被拦：{[(f.rule_id, f.evidence) for f in blockingFindings(res)]}"


# ── 真产物：这只资产包今天的命运由谁决定 ────────────────────────────────────


def test_shapeNeedlesSeparateTheTwoForms(gate):
    """两把针在这两个样本上必须给**相反**答案——不然分类只是空场自证。

    形态集 220 记过同形账：针自己打空时，读数看着像"判据没牙"，实为探针没扎到地方。
    属性调用那一侧的针是测试造的（生产没有"这是属性调用"的正向 pattern，它正是旧规则误判
    的那一类形状），所以它本身要被钉住：命中 `re.compile(` 那行、不命中裸名那行，
    而生产规则对这两行的答案恰好相反。任何一侧写成恒真/恒假，这格先红。
    """
    attributeLine = 'DATE = re.compile(r"日期|date", re.I)'
    bareLine = 'compile("x = 1", "<str>", "exec")'
    rule = execShapes.execRule(gate)

    assert execShapes.classifyEvidence(attributeLine) == "attribute"
    assert execShapes.classifyEvidence(bareLine) == "bare"
    assert execShapes.isAttributeOnly(attributeLine) is True
    assert execShapes.isAttributeOnly(bareLine) is False, (
        "同一行里出现裸名 compile( 时不许只按属性调用判 ⇒ 这条闸会把真信号一起关掉")
    assert rule.severityFor(attributeLine) is None, (
        "属性调用形又被生产规则算成危险执行——上面那条分类随之失去意义")


# ── 真产物：这只资产包今天的命运由谁决定 ────────────────────────────────────

def testRealBundleDeniesOnItsOwnTrueShapesNotOnRegex(gate, tmp_path):
    """真 zip 现读：误判关掉之后，这只包**仍然该被拦**——但拦它的是真形态，不是 `re.compile(`。

    钉三件事，少一件就是自欺：
    ① `dangerous_exec` 的证据行里不得再出现属性调用（`X.compile(` 这一形）；
    ② 参与裁决的 exec 命中只剩裸名调用那 1 条（真信号）；
    ③ 修完不许偷偷变成放行——本批改的是误判，不是"给这只包开后门"，
      要不要开白名单/撤条目仍是另一次裁定（§6-250 乙/丙案）。
    """
    assert BUNDLE.exists(), f"包内资产缺失，本格的根据就没了：{BUNDLE}"
    dest = tmp_path / "studio"
    dest.mkdir(parents=True)
    with zipfile.ZipFile(BUNDLE) as zf:
        zf.extractall(dest)

    res = gate.scan_skill("builtin--adaptive-presentation-studio", str(dest))
    execHits = [f for f in blockingFindings(res) if f.rule_id == "dangerous_exec"]
    attributeish = [f for f in execHits if execShapes.isAttributeOnly(str(f.evidence))]

    assert not attributeish, (
        f"仍有 {len(attributeish)} 条属性调用被当危险执行，例：{[(f.file_path, f.evidence) for f in attributeish[:3]]}")
    assert len(execHits) == 1, (
        f"真裸名动态执行读数应为 1 条（`package_check.py` 的 compile(...)），现读 {len(execHits)}："
        f"{[(f.file_path, f.evidence) for f in execHits]}")
    assert res.passed is False, "误判关掉后这只包反而放行了——真信号（动态编译/子进程）也判没了？"


# ── 拒因文本只准念参与裁决的条目 ─────────────────────────────────────────────

def testDenyReasonNamesOnlyBlockingFindings(tmp_path):
    """`error` 串是回执的一部分：不许把不参与裁决的读数当拒因念出去。

    今天的实现取 `findings[:5]`，于是一只靠 critical 被拒的包，拒因里念的可能是 `.json` 里的
    `../`（文档侧报告项，根本不参与 DENY）——读的人据此去改资产文档，方向全错。
    """
    from neurova.skills.skill_install_gate import scan_skill_for_install

    dest = buildPackage(tmp_path, "regexPrecompile")
    (dest / "notes.md").write_text(
        "# 说明\n相对链接示例：../assets/a.png\n", encoding="utf-8")
    scan = scan_skill_for_install("demo", str(dest))
    assert scan["blocked"] is False, (
        f"合成包仍被拦（拒因：{scan.get('error')}）——上面几条修没修，这格会跟着给答案")

    dest2 = buildPackage(tmp_path, "bareExec")
    (dest2 / "data.json").write_text('{"p": "../assets/x.png"}', encoding="utf-8")
    scan2 = scan_skill_for_install("demo2", str(dest2))
    assert scan2["blocked"] is True, "真 exec 包必须被拦"
    error = str(scan2.get("error") or "")
    # 不参与裁决的那条形形态（`data.json` 里的 `../` 无落地调用 ⇒ 降级 low）也得造出来，
    # 否则下面"只念 dangerous_exec"是空场上白过。
    ruleIds = {f.get("rule_id") for f in scan2.get("findings") or []}
    assert "dangerous_path_traversal" in ruleIds, (
        f"夹具没造出非裁决条目，这格就成了空场自证：{sorted(ruleIds)}")
    assert "dangerous_exec" in error, f"拒因没点名真正拦它的那条规则：{error}"
    assert "dangerous_path_traversal" not in error, (
        f"拒因里念出了不参与裁决的规则（{sorted(ruleIds)}），全文＝{error}")
