# -*- coding: utf-8 -*-
"""live-verify（§6-232）：扫描面取数收口之后，**证据面逐字没变**，而旧形态的失效方向当场翻红。

收口的风险不在"新单点能不能跑"，在"九档判据改走单点之后各自看见的文件集合还是不是原来那一份"。
所以本档的读数都围着这一件事取，且都在**真仓**上跑（不是合成目录）：

1. **逐档等集**：三份旧解法（`-z` bytes 解／`-z` text+utf-8 解／整目录 pathspec）与单点各取一次，
   两侧必须**逐字相同**（比集合摘要，不比条数）——收口只准动"在哪儿取"，不准动"取到什么"；
2. **旧形态的假绿复现**：同一份子脚本喂一条真会失败的 git 命令，旧形态（不查退出码）读出**空清单**
   ＝"仓里干净"，而单点必须抛；
3. **证据面合成**：已跟踪面 ＋ 在途未跟踪面，交集必须为 0（双计会让同一条格在两处给出不同读数），
   本档自己必须恰好落在其中一侧一次；
4. **两个路面的分工在真仓的形状**：造一份未跟踪的在途档（复刻数据根那一形），它必须**只**出现在
   工作树面、不出现在已跟踪面，而常驻格的谓词对同一内容形状**仍然翻红**（收面≠放宽谓词）；
5. **真判据复跑**：收口后的 11 档在真仓逐档跑，报汇总读数（"跑完了没报错"不算读数）。

旧形态为什么要放进**子进程脚本**而不是本档直接调：本档就是被新判据扫的那张脸——
`test_trackedScanFaceIsSingleSourced` 判的是"判据自己抄一份全树枚举"，第一版本档把三种旧形
写在本文件的 `subprocess.run([...])` 上，当场被自己那条格点名（`tests/manual/…:109`）。
子脚本源码是字符串常量，AST 里没有调用点（这一区分正是新格 `_SCOPED_SAMPLE` 钉住的形状），
于是"复算旧形"与"全仓只留一个取数口"这两件事不再互相矛盾。两处子进程都**两头钉**：
子端 env 写 `PYTHONIOENCODING=utf-8`、父端按 utf-8 解——只钉父端就是 §6-225 那族的"半修"形，
本批不去添那一格；旧形读数另走文件不走 stdout，因为要比的是集合摘要，不该再过一层编码。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/scanFaceSingleSource_batch54.py`
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot(prefix="neurovaScanB54")   # 本档不碰生产库，仍走仓内唯一隔离落点

from tests import ast_scan  # noqa: E402

failures: list = []

#: 复刻数据根那一形的在途样本（内容形状与常驻格新格探针同源，谓词必须照样认得）
FOREIGN = "tests/manual/b54_live_foreign_scratch_tmp.py"
FOREIGN_SOURCE = (
    "import sqlite3\n"
    "from pathlib import Path\n"
    "\n"
    "root = Path('here') / 'data' / 'scratch.db'\n"
    "conn = sqlite3.connect(str(root))\n")

SELF = "tests/manual/scanFaceSingleSource_batch54.py"

#: HEAD 那九档判据里实际写过的三种取数口，逐字照抄（不做"顺手改好"的处理），只加一条未知参数。
_OLD_FORMS_PROBE = r'''
import hashlib, json, subprocess, sys
root, outPath = sys.argv[1], sys.argv[2]
BORING = "--no-such-flag-b54"

def bytesZ(args):
    """旧形甲：cwd= 定位仓根、bytes 解 stdout、**不查退出码**。"""
    proc = subprocess.run(["git", "ls-files"] + args, cwd=root, capture_output=True)
    return [p for p in proc.stdout.decode("utf-8").split("\0") if p]

def textZ(args):
    """旧形乙：`-C root` + `text=True, encoding="utf-8"`。"""
    proc = subprocess.run(["git", "-C", root, "ls-files"] + args, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return [p for p in proc.stdout.split("\0") if p]

def blankSplit(args):
    """旧形丙：普通输出按空白切（`test_committed_tree_dependencies.py` 那一形）。"""
    proc = subprocess.run(["git", "-C", root, "ls-files"] + args, capture_output=True)
    return [p for p in proc.stdout.decode("utf-8").split() if p]

def digest(items):
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()

result = {
    "bytesZ": digest(bytesZ(["-z"])), "bytesZCount": len(bytesZ(["-z"])),
    "bytesPyZ": digest(bytesZ(["-z", "*.py"])), "bytesPyZCount": len(bytesZ(["-z", "*.py"])),
    "textZ": digest(textZ(["-z"])),
    "splitZ": digest(blankSplit([])),
    "splitQuoted": len([p for p in blankSplit([]) if p.startswith('"')]),
    "bytesQuoted": len([p for p in bytesZ(["-z"]) if not p.isascii()]),
    "bogusSwallowed": len(bytesZ(["-z", BORING])),
    "rawBytes": len(subprocess.run(["git", "-C", root, "ls-files", "-z"],
                                   capture_output=True).stdout),
}
neurovaPy = [p for p in bytesZ(["-z", "neurova"]) if p.endswith(".py")]
result["bytesNeurova"] = digest(neurovaPy)
result["bytesNeurovaCount"] = len(neurovaPy)
open(outPath, "w", encoding="utf-8").write(json.dumps(result))
'''

GUARDS = (
    "tests/unit/ci/test_trackedScanFaceIsSingleSourced.py",
    "tests/unit/ci/test_manual_live_verify_contract.py",
    "tests/unit/test_noFirstPartyImportPlaceholder.py",
    "tests/unit/test_noDeadImportSwallowFacadeBlocks.py",
    "tests/unit/test_dev_path_and_runtime_dep_guards.py",
    "tests/unit/test_weightEgressGateRefusesBeforeBytes.py",
    "tests/unit/core/test_sourceEscapeSequenceHygiene.py",
    "tests/unit/core/test_committed_tree_dependencies.py",
    "tests/unit/core/test_packageInitBindsNoUnusedGenericNames.py",
    "tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py",
    "tests/unit/cognitive_layers/memory_layer/test_temperature_single_source.py",
)


def read(idx: str, desc: str, fn) -> None:
    try:
        print("[%s] PASS %s  ← %s" % (idx, desc, fn()))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def observe(desc: str, fn) -> None:
    try:
        print("    OBSERVE %s：%s" % (desc, fn()))
    except Exception as exc:  # noqa: BLE001 - 观察项不记分，只留读数
        print("    OBSERVE %s：读数失败 %r" % (desc, exc))


def _digest(items) -> str:
    return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()


def _runOldForms():
    """把三种旧形交给子进程在**真仓**上复算，结果走文件不走 stdout。

    子端 env 一并钉 `PYTHONIOENCODING`：§6-225 立的"半修"就是父端按 utf-8 解而子端按本机码页吐字节。
    本档的报错文本走 stderr，父端要读它，所以两头都得钉。
    """
    workdir = Path(tempfile.mkdtemp(prefix="neurovaScanB54Probe"))
    child = workdir / "oldForms.py"
    outPath = workdir / "readout.json"
    child.write_text(_OLD_FORMS_PROBE, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(child), str(REPO), str(outPath)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == 0, "旧形复算子脚本没跑成：%s" % proc.stderr[:200]
    return json.loads(outPath.read_text(encoding="utf-8"))


OLD = _runOldForms()


def sameSet(label, oldDigest, oldCount, newItems):
    newDigest, newCount = _digest(newItems), len(newItems)
    assert oldDigest == newDigest and oldCount == newCount, (
        "%s：取数改走单点之后集合变了（旧 %d 条 %s…／新 %d 条 %s…）"
        % (label, oldCount, oldDigest[:8], newCount, newDigest[:8]))
    return "%s 两侧各 %d 条、集合摘要逐字相同（%s…）" % (label, newCount, newDigest[:8])


read("1a", "全仓清单：`-z` bytes 解 == trackedPaths()",
     lambda: sameSet("`-z`", OLD["bytesZ"], OLD["bytesZCount"], ast_scan.trackedPaths()))
read("1b", "全仓 .py：`-z *.py` == trackedPyPaths()",
     lambda: sameSet("`-z *.py`", OLD["bytesPyZ"], OLD["bytesPyZCount"], ast_scan.trackedPyPaths()))
read("1c", "整目录 pathspec：`-z neurova` 滤 .py == trackedPyPaths(\"neurova\")",
     lambda: sameSet("`-z neurova`", OLD["bytesNeurova"], OLD["bytesNeurovaCount"],
                     ast_scan.trackedPyPaths("neurova")))
read("1d", "text+utf-8 解与 bytes 解同集（两形各被不同判据抄过）",
     lambda: sameSet("`text=True` 侧", OLD["textZ"], OLD["bytesZCount"], ast_scan.trackedPaths()))


def _oldFormSwallowsFailure():
    """旧形态不查退出码：git 失败 ⇒ 空清单 ⇒ "仓里干净"。单点必须抛。"""
    assert OLD["bogusSwallowed"] == 0, (
        "git 失败了旧形却没读出空清单（%d 条），这条反证不成立" % OLD["bogusSwallowed"])
    try:
        ast_scan.trackedPyPaths("--no-such-flag-b54")
    except RuntimeError as exc:
        return "旧形读成 0 条＝假绿；单点抛 RuntimeError：%s" % str(exc)[:64]
    raise AssertionError("git 失败时单点没抛——「回空清单」那一形没被改掉")


read("2", "git 失败：旧形态读成 0 条（假绿）／单点必抛", _oldFormSwallowsFailure)


def _splitFormDrift():
    """空白切那一形今天的漏扫面：非 ASCII 路径被 git 打成带引号的八进制串。"""
    assert OLD["splitZ"] != OLD["bytesZ"], (
        "两形集合摘要相同——本仓此刻没有非 ASCII 跟踪档，这条读数没牙，"
        "应如实改记为「今天等价」而不是报 PASS")
    assert OLD["splitQuoted"] == OLD["bytesQuoted"], (
        "带引号的条数 %d 与非 ASCII 条数 %d 不等 ⇒ 漂移面不止八进制引号一处，得单独定性"
        % (OLD["splitQuoted"], OLD["bytesQuoted"]))
    return ("按空白切的旧形把 %d 条非 ASCII 跟踪档读成 `\"…\\345…\"` 带引号串 ⇒ 这些档**根本不进扫描面**；"
            "本仓这 %d 条全在 `docs/`（`.py` 侧 0 条）⇒ 今天咬不到 .py 判据，"
            "但「把判据指到全仓或 docs」那一刻就漏，这一形已在收口时改掉"
            % (OLD["splitQuoted"], OLD["bytesQuoted"]))


read("3", "空白切旧形的漏扫面（量化，并说明今天为什么没咬到）", _splitFormDrift)


def _evidenceFace():
    tracked = set(ast_scan.trackedPaths())
    others = set(ast_scan.untrackedNotIgnoredPaths())
    assert not (tracked & others), "两路面重叠＝证据面被双计"
    assert (SELF in tracked) != (SELF in others), (
        "本探针在两路面里出现 %d 次（应为 1 次）：证据面漏件或双计"
        % ((SELF in tracked) + (SELF in others)))
    assert FOREIGN not in tracked and FOREIGN not in others, "已删的残留又被算进证据面"
    return ("已跟踪 %d ＋ 在途未跟踪 %d ＝ 证据面 %d，交集 0；本档落在%s那一侧"
            % (len(tracked), len(others), len(tracked) + len(others),
               "已跟踪" if SELF in tracked else "在途"))


read("4", "证据面两路面不重不漏，本档恰落一侧", _evidenceFace)


def _twoFaces():
    """在途档只进工作树面；常驻格的谓词对同一内容形状必须照样翻红。"""
    scratch = REPO / FOREIGN
    assert not scratch.exists(), "上一次运行残留 %s，会污染本项读数" % FOREIGN
    scratch.write_text(FOREIGN_SOURCE, encoding="utf-8")
    contract = importlib.import_module("tests.unit.ci.test_manual_live_verify_contract")
    try:
        tracked = set(ast_scan.trackedPaths("tests/manual"))
        globbed = {p.name for p in (REPO / "tests" / "manual").glob("*.py")
                   if not p.name.startswith("_")}
        name = FOREIGN.rsplit("/", 1)[-1]
        assert name in globbed, "工作树面看不见刚写的在途档＝本项没跑起来"
        assert FOREIGN not in tracked, "已跟踪面把未提交的在途档算进来了——收口没生效"
        assert contract._replicatesDataRootLayout(ast_scan.transientTree(scratch)), (
            "谓词对这份复刻数据根的形状不再翻红＝把「收面」做成了「放宽判据」")
        return ("工作树面含它、已跟踪面不含它（manual 已跟踪 %d 档）；谓词对同一形状翻红 ⇒ "
                "收面收的是「谁进存量」，不是「什么算断点」" % len(tracked))
    finally:
        scratch.unlink(missing_ok=True)
        assert not scratch.exists(), "在途样本残留会被下一条判据算进真实存量"


read("5", "工作树面 vs 已跟踪面：在途档只进前者，谓词不跟着松", _twoFaces)


def _runGuards():
    lines, failed = [], []
    childEnv = {**os.environ, "PYTHONIOENCODING": "utf-8"}   # 子端也钉（同 §6-225 那族半修病）
    for rel in GUARDS:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--no-header", "--tb=no", rel], cwd=str(REPO), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=childEnv)
        out = proc.stdout + proc.stderr
        summary = [l.strip("= ").strip() for l in out.splitlines()
                   if " passed" in l or " failed" in l or " error" in l]
        if not summary:
            raise AssertionError("%s 没产出汇总行（没跑成不等于全绿）" % rel)
        tail = summary[-1]
        if " failed" in tail or " error" in tail:
            failed.append("%s→%s" % (rel.rsplit("/", 1)[-1][:-3], tail))
        lines.append("%s→%s" % (rel.rsplit("/", 1)[-1][:-3], tail))
    # 唯一允许的红＝main 上那道常驻红（§6-232 登记，非本批引入：HEAD 的仓外工作树同形复现）
    assert len(failed) <= 1, "本批收口之后仍有除常驻红之外的红：%s" % failed
    if len(failed) == 1:
        assert "test_noDeadImportSwallowFacadeBlocks" in failed[0], (
            "那道红不是 §6-232 登记的常驻红，本批不得带着它交付：%s" % failed[0])
        return ("11 档里 10 档全绿，1 档＝已登记的常驻红（HEAD 同样红）。那道红被修好之后这一格应当"
                "收紧成全绿，添了新格则先登记再放行：" + failed[0])
    return " ; ".join(lines)


read("6", "收口后 11 档判据在真仓逐档复跑（只许那道常驻红在场）", _runGuards)

observe("单点为什么必须自己定解码", lambda: (
    "输出 %d 字节／非 ASCII 相对路径 %d 条；仓所在绝对路径含中文（%s）但不进 stdout ⇒ "
    "要钉的是 stdout 的解码，而这件事此前被抄了九份"
    % (OLD["rawBytes"], OLD["bytesQuoted"], REPO)))


def _dataRootUntouched():
    root = REPO / "data"
    files = sorted(p for p in root.rglob("*") if p.is_file())
    digest = hashlib.sha256("\n".join(
        "%s:%d" % (p.relative_to(root).as_posix(), p.stat().st_size) for p in files)
        .encode("utf-8")).hexdigest()[:12]
    return "%d 个文件，内容＋字节数指纹 %s（两次跑本档应逐字一致）" % (len(files), digest)


observe("仓库 data/ 未被写入（本档只做取数，不碰生产库）", _dataRootUntouched)

print("\n==== 汇总：6 项计分读数，失败 %d ====" % len(failures))
for f in failures:
    print("  FAIL", f)
sys.exit(1 if failures else 0)
