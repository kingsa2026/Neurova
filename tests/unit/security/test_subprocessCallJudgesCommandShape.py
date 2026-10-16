# -*- coding: utf-8 -*-
r"""`subprocess_call` 必须判**命令是怎么交给系统的**，不判"有没有起进程"（用户裁甲）。

实状（本机真 HTTP 面现读，不抄旧账）：随包内置的 `adaptive-presentation-studio` 在面板安装时
先被暂存长路径拒在门外（本批第一刀，§6-2xx），修好后门才第一次真的被调用，读数是一句
`409 … high(subprocess_call) ×4 + critical(dangerous_exec) ×1`。逐条读**证据行**：那 4 条是

    proc = subprocess.run(            # 渲染幻灯片，argv 列表在下一行
    completed = subprocess.run(command, check=False)
    return subprocess.run(command, capture_output=True, ...)

——**全是 argv 列表形态，没有一条带 `shell=True`，也没有一条把字符串当命令交出去**。
这正是"批 56 那条路"的续集：规则只看字节看不见语义时，信号打在无害形态上就会淹没真信号，
而这只包的"起外部进程"就是它的功能本身（渲染 deck）。

甲案的口径钉成两侧，缺一侧就是自欺：

- **降级侧**：argv 列表（含单行/跨行/变量名三种形态）⇒ 读数**照常上报**（severity=low），
  不参与裁决。降级不是删除（批 37 定的口径），报告面与审计面还得看得见"这里起了进程"。
- **照旧拦侧**：首参是**字符串命令**（字面量或 f-string）⇒ 仍 high 参与 DENY；
  `shell=True`、`os.system` 这两道真闸一条不许跟着松。

另有一处**已明码接受的边界**：`subprocess.run(` 换行后才写字符串首参那种形，行级正则看不见，
今天会落到 low。本格把它钉成"我们知道没拦什么"（写成断言而不是注释），将来上 AST 判定就改这格。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from neurova.security.skill_scanner import SkillScanner, ScanPolicy, blockingFindings

REPO = Path(__file__).resolve().parents[3]
BUNDLE = REPO / "neurova" / "skills" / "market_bundles" / "adaptive-presentation-studio.zip"

SKILL_MD = "# demo\n用于安装门读数的最小技能包。\n"
RULE = "subprocess_call"

#: 每只合成包：{相对路径: 内容}。**这些串只是被扫描的字节**——落成 tmp 文件后从不 import、
#: 也不执行；本档读的始终是扫描器给出的读数。
PACKAGES = {
    "argvInline": {
        "render.py": 'import subprocess\n'
                     'subprocess.run(["node", "render.mjs", "--dpi", "96"], check=True)\n'},
    "argvMultiline": {
        "render.py": 'import subprocess, sys\n'
                     'proc = subprocess.run(\n'
                     '    [sys.executable, "-m", "ensure"],\n'
                     '    capture_output=True,\n'
                     ')\n'},
    "argvBuiltThenRun": {
        "pipeline.py": 'import subprocess, sys\n'
                       'command = [sys.executable, "build_deck.py", "--quiet"]\n'
                       'subprocess.run(command, check=False)\n'},
    "stringLiteralCommand": {
        "wipe.py": 'import subprocess\n'
                   'subprocess.run("del C:\\\\Windows\\\\system32\\\\*", check=True)\n'},
    "fStringCommand": {
        "convert.py": 'import subprocess\n'
                      'src = "a.svg"\n'
                      'subprocess.run(f"convert {src} out.png")\n'},
    "shellTrue": {
        "listing.py": 'import subprocess\nsubprocess.run("ls -la /etc", shell=True)\n'},
    "osSystem": {
        "rm.py": 'import os\nos.system("rm -rf /tmp/whatever")\n'},
    "crossLineString": {
        "boundary.py": 'import subprocess\n'
                       'subprocess.run(\n'
                       '    "rm -rf /tmp/x",\n'
                       '    check=True,\n'
                       ')\n'},
    "clean": {"run.py": "def go(x):\n    return x + 1\n"},
}

#: 甲案里必须降级的三种 argv 形态（都是真包里出现过或同形的写法）。
ARGV_SHAPES = ["argvInline", "argvMultiline", "argvBuiltThenRun"]
#: 必须照旧拦的字符串命令形态。
STRING_COMMAND_SHAPES = ["stringLiteralCommand", "fStringCommand"]


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
    """安装门那一套策略（DENY），不在测试里另写一份裁决口径。"""
    scanner = SkillScanner(workspace_path=".")
    scanner.policy = ScanPolicy.DENY
    return scanner


def verdict(gate, tmp_path: Path, name: str):
    return gate.scan_skill(name, str(buildPackage(tmp_path, name)))


# ── 降级侧：argv 列表不得决定一次安装的死活 ─────────────────────────────────

@pytest.mark.parametrize("name", ARGV_SHAPES)
def testArgvListIsReportedNotAdjudicated(gate, tmp_path, name):
    """argv 列表 ⇒ ①读数仍在 ②severity=low ③不参与裁决 ④整包放行。"""
    res = verdict(gate, tmp_path, name)
    readings = [f for f in res.findings if f.rule_id == RULE]
    assert readings, f"{name} 这条『起了外部进程』的读数被删了：降级不等于看不见"
    assert all(f.severity == "low" for f in readings), (
        f"{name} 的 argv 形态仍按 {[(f.severity, f.evidence) for f in readings]} 参与裁决")
    assert not [f for f in blockingFindings(res) if f.rule_id == RULE], (
        f"{name} 的 argv 形态仍在 blocking 集合里：{[f.rule_id for f in blockingFindings(res)]}")
    assert res.passed is True, (
        f"只含 argv 列表 subprocess 的包被拦：{[(f.rule_id, f.severity) for f in blockingFindings(res)]}")


# ── 照旧拦侧：窄化不许把真闸一起关掉 ────────────────────────────────────────

@pytest.mark.parametrize("name", STRING_COMMAND_SHAPES)
def testStringCommandStillDenies(gate, tmp_path, name):
    """首参是字符串命令（字面量 / f-string）⇒ 照旧 high 拦。这一半是甲案的代价边界。"""
    res = verdict(gate, tmp_path, name)
    assert res.passed is False, f"{name} 把字符串当命令交给 subprocess 却不拦了"
    hits = [f for f in blockingFindings(res) if f.rule_id == RULE]
    assert hits, f"{name} 拦了，但拦它的不是 subprocess_call：{[f.rule_id for f in blockingFindings(res)]}"
    assert all(f.severity == "high" for f in hits), [(f.severity, f.evidence) for f in hits]


def testShellTrueGateDidNotLoosen(gate, tmp_path):
    """`shell=True` 那道闸独立存在，不随 subprocess_call 降级而松。"""
    res = verdict(gate, tmp_path, "shellTrue")
    assert res.passed is False, "shell=True 不拦了——那才是真注入面"
    assert any(f.rule_id == "shell_true" for f in blockingFindings(res)), (
        f"拦它的不是 shell_true 这条闸：{[(f.rule_id, f.severity) for f in blockingFindings(res)]}")


def testOsSystemGateDidNotLoosen(gate, tmp_path):
    """`os.system` 一直是字符串命令进 shell，照旧拦。"""
    res = verdict(gate, tmp_path, "osSystem")
    assert res.passed is False, "os.system 不拦了"
    assert any(f.rule_id in ("dangerous_os_command", "os_system", "subprocess_call")
               and f.severity in ("critical", "high") for f in blockingFindings(res)), (
        f"拦它的不是命令面那条闸：{[(f.rule_id, f.severity) for f in blockingFindings(res)]}")


def testCleanPackageStillPasses(gate, tmp_path):
    """反向控制：干净包必须过——上面几条"仍拦"若连正常包也拦，等于什么都没修。"""
    res = verdict(gate, tmp_path, "clean")
    assert res.passed is True, (
        f"干净包被拦：{[(f.rule_id, f.severity, f.evidence) for f in blockingFindings(res)]}")


def test_downgradeIsJudgedByShapeNotByRuleNameWhitelist(gate):
    """两把针在同一张规则表上必须给**相反**答案——否则"降级"只是按 rule_id 名单豁免。

    形态集 239 记过同形账：取值太干净时改回原样也不红。这里用规则本体的
    `severityFor` 直接喂两行：一行 argv 列表、一行字符串命令，答案必须分别是 low / high；
    再喂一行"裸名 subprocess.run 后换行"（看不见首参），它必须落 low——那是明码接受的边界。
    """
    from neurova.security.skill_scanner import PatternAnalyzer

    matches = [a.rules[RULE] for a in gate.analyzers
               if isinstance(a, PatternAnalyzer) and RULE in a.rules]
    assert len(matches) == 1, (
        f"装配面上 `subprocess_call` 规则本体取到 {len(matches)} 份 ⇒ 本格失去根据，"
        "去查规则表而不是改断言")
    rule = matches[0]
    argvLine = 'subprocess.run(["node", "render.mjs"], check=True)'
    stringLine = 'subprocess.run("del C:\\\\Windows\\\\x", check=True)'
    openLine = "proc = subprocess.run("

    assert rule.severityFor(argvLine) == "low", rule.severityFor(argvLine)
    assert rule.severityFor(stringLine) == "high", rule.severityFor(stringLine)
    assert rule.severityFor(openLine) == "low", (
        "跨行/看不见首参那一形今天按报告项处理——本格把已接受的边界钉成断言，不是注释")


def testCrossLineStringCommandIsAnAcceptedBlindSpotNamedAsSuch(gate, tmp_path):
    """`subprocess.run(` 换行后才写字符串首参：行级正则看不见 ⇒ 今天按报告项放行。

    这一格**故意钉的是没拦什么**（同 §6-273 那条"整串扁平输入"的明码边界）。上 AST 判定那天，
    这格必须改成断 high——它不会因为改动而静默失效，只会当场红在那里提醒改口径。
    """
    res = verdict(gate, tmp_path, "crossLineString")
    readings = [f for f in res.findings if f.rule_id == RULE]
    assert readings, "跨行那形连读数都不出了——报告面也不见了才是真危险"
    assert all(f.severity == "low" for f in readings), [(f.severity, f.evidence) for f in readings]
    assert res.passed is True, "跨行字符串命令已被拦：边界收窄了，请把本格的期望改成 high 并同步 docstring"


# ── 真产物：这只包今天不再因为 argv 被拒 ────────────────────────────────────

def testRealBundleIsNotDeniedForItsArgvReadings(gate, tmp_path):
    """真 zip 现读：blocking 集合里不得再有 subprocess_call；读数仍要在报告面看得见。

    只断这一件。整包放行要等资产那一处裸名 `compile(` 也改掉（本批第三刀）才算得数，
    在这里一起断会把两刀的因果搅成一格。
    """
    assert BUNDLE.exists(), f"包内资产缺失，本格的根据就没了：{BUNDLE}"
    dest = tmp_path / "studio"
    dest.mkdir(parents=True)
    with zipfile.ZipFile(BUNDLE) as zf:
        zf.extractall(dest)

    res = gate.scan_skill("builtin--adaptive-presentation-studio", str(dest))
    blocking = blockingFindings(res)
    argvish = [f for f in blocking if f.rule_id == RULE]
    assert not argvish, (
        f"真包的 argv 形态仍有 {len(argvish)} 条参与裁决："
        f"{[(f.file_path, f.evidence) for f in argvish]}")
    readings = [f for f in res.findings if f.rule_id == RULE]
    assert len(readings) >= 4, (
        f"报告面只剩 {len(readings)} 条起进程读数（改前是 4 条）——降级被做成了删数")
    assert all(f.severity == "low" for f in readings), (
        f"这 {len(readings)} 条的严重度不全是 low：{[(f.severity, f.evidence) for f in readings]}")
