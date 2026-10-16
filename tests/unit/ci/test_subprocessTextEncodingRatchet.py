# -*- coding: utf-8 -*-
"""只降不升棘轮：文本模式捕获子进程输出，必须显式写 `encoding`（§6-64 的 B 处置）。

成因不重述，见 `audit-reports/simplification-audit-2026-10-05.md` §6-64：
`subprocess.run(..., text=True)` 不给 `encoding` 时，父进程按
`locale.getpreferredencoding()`（开发机是 cp936）解子进程写的 UTF-8 字节，实测三种坏法
——全 ASCII 侥幸没事 / 大输出把 `proc.stdout` **静默置成 None**（同调用改回 bytes 模式
立刻拿回 1.65MB 正常输出）/ 非 ASCII 恰好凑成合法 cp936 序列时**不报错但内容被替换**。
最后一态最险：判据照跑、读的是脏文本。已有一格因此让守卫从未运行
（`test_whole_repo_collection_errors.py`，`aff4ec6b` 修的）。

为什么是棘轮而不是当场扫净：点单口径是人裁选 B（`scripts/ci/` 与 `neurova/` 那 10 处
先冻结、后续按目录分批消化）。当场把 38 个文件一起改，会让"哪条红是哪一个文件带来的"
无法归因，且部分判据在补上 encoding 后会从"假绿"翻成"真红"——那是另一轮改动面。

基线口径（本轮实测，不抄旧数）：**37 个文件 / 59 处**。
（2026-10-09 收：`tests/unit/test_repo_root_pollution_guard.py` 的 1 处已随该文件三处
 子进程文本捕获全部钉上显式 `encoding="utf-8"` 而清零，该文件从基线摘除——
 摘除而不是留 0：日后它再长出一处，`BASELINE.get(f, 0)` 会让棘轮当场红。）
（2026-10-12 收：`scripts/ci/pip_audit_gate.py` 的 1 处随本批离线裁决通路一并清零——
 该文件新增的离线扫描调用点原先与既有直连调用点一样没写 `encoding`，两处一起补上
 显式 `encoding="utf-8", errors="replace"`，站点数回到 0，同样从基线摘除。）
判定形态是**逐文件计数**而不是全局总数：
- 某文件站点数**上升**或**新文件出现** → 红（增长被止住，这是本判据的全部目的）；
- 站点数**下降** → 允许，但本文件会**红着提示"基线该收了"**，逼一次显式改基线，
  避免"偷偷比基线好"变成"再也没人回去核基线"（只降不升要真降，得让降可见）；
- 谓词过宽会误伤（`capture_output=True` 不带 `text` 拿到的是 bytes，没有解码面），
  所以有三条反向断言钉住不 flag 的形态；谓词过窄会空转，所以有注入探针钉住咬得住。
"""

from __future__ import annotations

import ast
import locale
import os
import pathlib
import subprocess
import sys

import pytest

#: 本文件在 `tests/unit/ci/` 下，仓库根是 `parents[3]`。
#: 写错这一层时 `test_scanRootsActuallyCoverTheTree` 当场红（实测首跑就把
#: `parents[2]` 的错抓成"三个根各 0 个文件"）——那条覆盖性断言就是为这种
#: "扫了个空却报绿"的形态准备的，不是装饰。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.ast_scan import filesUnder  # noqa: E402

#: 会被判的 subprocess 入口（这几个都把子进程输出交给父进程解码）
CAPTURE_FUNCS = ("run", "check_output", "check_call", "call", "Popen",
                 "getoutput", "getstatusoutput")

#: 扫描根。刻意含 `tests/`：判据自己的空转就发生在测试侧。
SCAN_ROOTS = ("neurova", "scripts", "tests")

#: 冻结基线（**表内现量为准**：35 文件 / 57 站点，逐档单跑现复算）。只准降不准升。
#: 建档那轮（批 51）写的是"37 文件 / 59 站点"——那是一批时间性快照，此后各批收掉的落点
#: 都按本表逐格摘除（批 54 摘的是 `test_temperature_single_source.py` 那一处，它改走
#: `ast_scan` 单点后不再自己起文本模式子进程），注释留着旧数就等于留一条没人对的账。
BASELINE: dict[str, int] = {
    "scripts/ci/npc_branch_cleanup.py": 3,
    "scripts/ci/osv_audit.py": 1,
    "scripts/ci/perf_gate.py": 1,
    "scripts/desktop/bundle_backend.py": 1,
    "scripts/desktop/package_installer_zip.py": 3,
    "scripts/desktop/win_installer_kit.py": 4,
    "scripts/diagnostics/_tmp_check_tracked.py": 1,
    "scripts/generate_api_inventory.py": 1,
    "scripts/setup_computer_use.py": 1,
    "tests/manual/channel_migration_dialog_326.py": 1,
    "tests/manual/context_ledger_batching_90.py": 1,
    "tests/manual/context_ledger_recall_scope_90.py": 1,
    "tests/manual/context_persistence_baseline_90.py": 2,
    "tests/manual/context_persistence_restart_90.py": 1,
    "tests/manual/image_runtime_selfproof_330.py": 1,
    "tests/unit/agent/test_tool_experience_loop_offline_probe.py": 3,
    "tests/unit/ci/test_issue197_judgement_registration.py": 1,
    "tests/unit/ci/test_npc_auto_continue_wiring.py": 2,
    "tests/unit/ci/test_npc_handoff_role_continuity.py": 2,
    "tests/unit/ci/test_npc_turn_handoff_execution.py": 1,
    "tests/unit/cognitive_layers/memory_layer/test_torch_lazy_import.py": 1,
    "tests/unit/context/test_b5_scale_batch_registration.py": 1,
    "tests/unit/core/test_safe_paths.py": 1,
    "tests/unit/evolution/test_rsi_result_summary_wiring.py": 1,
    "tests/unit/memory_ingest/test_protected_registration.py": 1,
    "tests/unit/sandbox/test_c22_process_tree_kill.py": 1,
    "tests/unit/test_adminBootstrapLanding.py": 2,
    "tests/unit/test_api_inventory_freshness_guard.py": 1,
    "tests/unit/test_pip_audit_gate.py": 1,
    "tests/unit/test_pytest_runner_guards.py": 1,
    "tests/unit/test_session_landing_guard.py": 1,
    "tests/unit/test_start_script.py": 2,
    "tests/unit/tools/test_git_tool.py": 1,
    "tests/unit/tools/test_tool_layer_breakpoints_zoom_out.py": 1,
    "tests/unit/tools/test_tool_parallelism_readout.py": 9,
}


def _violationCount(source: str) -> int:
    """数"文本模式捕获子进程输出但未显式指定 encoding"的调用点。

    只认代码形态（AST 里的 `subprocess.<fn>(...)` 关键字），不搜文本——
    docstring 里写一句 `text=True` 不该把文件判红（本仓被自己的文档撞红过一次）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                and fn.value.id == "subprocess" and fn.attr in CAPTURE_FUNCS):
            continue
        kws = {k.arg for k in node.keywords if k.arg is not None}
        # 文本模式：显式 text/universal_newlines，或 getoutput/getstatusoutput（恒文本）
        textMode = ("text" in kws) or ("universal_newlines" in kws) \
            or fn.attr in ("getoutput", "getstatusoutput")
        if textMode and "encoding" not in kws:
            count += 1
    return count


def scanViolations(roots=SCAN_ROOTS) -> dict[str, int]:
    perFile: dict[str, int] = {}
    for root in roots:
        for path in filesUnder(REPO_ROOT / root):
            if path.suffix != ".py":
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "subprocess" not in source:
                continue
            n = _violationCount(source)
            if n:
                perFile[path.relative_to(REPO_ROOT).as_posix()] = n
    return perFile


def test_scanRootsActuallyCoverTheTree():
    """谓词过窄就会空转：先证扫描面真覆盖了三个根、且文件量级在。"""
    seen = {r: sum(1 for p in filesUnder(REPO_ROOT / r) if p.suffix == ".py") for r in SCAN_ROOTS}
    assert all(v > 50 for v in seen.values()), f"扫描面被收窄到不可用的程度：{seen}"
    assert sum(seen.values()) > 1000, f"三个根的 .py 总量异常低：{seen}"


def test_ratchetDoesNotRise():
    """每个文件只能持平或下降；新文件一律拦。"""
    now = scanViolations()
    grew = {f: (now[f], BASELINE.get(f, 0)) for f in now if now[f] > BASELINE.get(f, 0)}
    assert not grew, (
        "子进程文本捕获又出现未显式 encoding 的落点（本机 locale 是 cp936 时，"
        "这会让 proc.stdout 静默变 None 或把内容替换掉）：\n"
        + "\n".join(f"  {f} 现 {n} 处 / 基线 {b} 处" for f, (n, b) in sorted(grew.items()))
        + "\n修法：subprocess.run(..., text=True, encoding=\"utf-8\", errors=\"replace\")，"
          "并让子进程写侧也钉成 UTF-8（env PYTHONIOENCODING）。"
    )


def test_ratchetRecordsImprovementLoudly():
    """降了要**看得见**：只降不升要真降，就得逼一次显式收基线。

    与尺寸棘轮同法——留一条"比基线好"的红，比"悄悄比基线好、再没人回来核"强。
    """
    now = scanViolations()
    dropped = {f: (BASELINE[f], now.get(f, 0)) for f in BASELINE if now.get(f, 0) < BASELINE[f]}
    assert not dropped, (
        "以下文件的未指定 encoding 落点比基线少了——把基线收下去再提交，"
        f"别让它悬着：\n"
        + "\n".join(f"  {f} 基线 {b} 处 / 现 {n} 处" for f, (b, n) in sorted(dropped.items()))
    )


def test_baselineIsNotInflatedWithFalsePositives():
    """反向钉三条**不该**被判的形态，防谓词宽到把正确写法一起算进基线。"""
    okForms = [
        # capture_output 不带 text → 拿到是 bytes，没有解码面
        "subprocess.run(['x'], capture_output=True)",
        # 显式给了 encoding（本判据要的正解）
        "subprocess.run(['x'], capture_output=True, text=True, encoding='utf-8', errors='replace')",
        # 不取输出，只等退出码
        "subprocess.call(['x'])",
    ]
    for src in okForms:
        assert _violationCount(src) == 0, f"正确形态被误判为违规：{src}"


def test_ratchetBitesOnAnInjectedViolation(tmp_path):
    """探针：往扫描根种一条违规，必须被数到——不咬人的棘轮等于没有。

    与 §6-43/`9d4befb9` 同一取向：判据不能只在"本机恰好没东西可扫"时绿。
    """
    probeDir = REPO_ROOT / "tests" / "unit" / "ci"
    probe = probeDir / "test_subprocessEncodingRatchetProbe_tmp.py"
    assert not probe.exists(), "上一次探针残留会污染基线"
    try:
        probe.write_text(
            "import subprocess\n"
            "\n"
            "def fetch():\n"
            "    return subprocess.run(['git', 'rev-parse', 'HEAD'], "
            "capture_output=True, text=True)\n",
            encoding="utf-8",
        )
        now = scanViolations()
        rel = probe.relative_to(REPO_ROOT).as_posix()
        assert now.get(rel) == 1, f"注入的违规未被扫到（棘轮空转）：{now.get(rel)!r}"
    finally:
        probe.unlink(missing_ok=True)


def test_probeRemovedFromBaselineAfterRun():
    """探针文件必须已消失：残留会让下一条用例把临时文件算进真实基线。"""
    leftovers = list((REPO_ROOT / "tests" / "unit" / "ci").glob("*RatchetProbe_tmp.py"))
    assert not leftovers, f"探针残留：{[p.name for p in leftovers]}"


@pytest.mark.parametrize("bad", [
    "subprocess.run(['x'], text=True)",
    "subprocess.check_output(['x'], universal_newlines=True)",
    "subprocess.getoutput(['x'])",
])
def test_knownBadFormsAreCounted(bad):
    assert _violationCount(bad) == 1, f"该被判的形态没判到：{bad}"


#: ── 半修计数自身的形状判据（§6-235 存量消化第一步）
#: 计数格读的是"该文件有没有任何一处真把写侧钉上"，所以**识别器漏一个形制＝多记一处半修**，
#: 而多记的那些恰恰是已经修对的——账越不准，下一次收数越会把"识别器坏了"读成"存量在涨"。
#: 实测现仓有两处用 `env=dict(os.environ, PYTHONIOENCODING="utf-8")`（关键字实参形）真钉过，
#: 而旧谓词只认字典字面与下标赋值 ⇒ 它们被记进了 29 处的账。
@pytest.mark.parametrize("snippet, expectPinned", [
    ("subprocess.run([sys.executable], env={'PYTHONIOENCODING': 'utf-8'})", True),
    ("os.environ['PYTHONIOENCODING'] = 'utf-8'", True),
    ("env = dict(os.environ, PYTHONIOENCODING='utf-8')", True),
    ("import os\nsubprocess.run([sys.executable], env=dict(os.environ, PYTHONIOENCODING='utf-8'))", True),
    ('"""说明里提一句 PYTHONIOENCODING 这个词而已"""\nsubprocess.run([sys.executable])', False),
    ("subprocess.run([sys.executable], env=os.environ.copy())", False),
])
def test_writesSidePinShapesAreJudgedByCodeForm(snippet, expectPinned):
    """写侧钉没钉只按代码形态判：正检三形＋反检两形，缺一形就是账不准。"""
    got = _writesSideIsPinnedInFile(snippet)
    assert got is expectPinned, (
        f"形状判定与实状不符（期望 pinned={expectPinned}，现读 {got}）：{snippet[:70]}")


def test_knownBothPinnedFilesAreNotCountedAsHalfPinned():
    """存量账里不许留着"其实已两头钉"的文件——这一格把假阳性点名钉死。

    写明去向：**从 29 收到 27 不是治理改进**，是识别器第一次认得这一形。收数时把它如实写进
    提交说明，否则下一轮会把"谓词修准"读成"有人吃掉了两处存量"。
    """
    sites = {f for f, _ in halfPinnedSites()}
    for name in ("tests/unit/memory/test_regression_worker_cleanup.py",
                 "tests/unit/test_manual_scripts_are_not_collectible.py"):
        assert name not in sites, f"{name} 已两头钉却被记成半修——识别器漏形，不是存量复发"
#: ── 批 51（§6-225）补的下半张：本文件原本只钉"有没有写 encoding"，不钉**写的是不是对的那一个**。
#: 于是出现一种比原缺陷更隐蔽的形态——**半修**：父端按 utf-8 解，子端（本仓的 Python 件）没钉
#: `PYTHONIOENCODING`，仍按本机码页（cp936）吐字节 ⇒ 非 ASCII 被换成 U+FFFD，而代码看起来"已修"。
#: 本文件自己的修法文案早就写了"并让子进程写侧也钉成 UTF-8"，那句话此前**只落在散文里没有通道**
#: （AGENTS.md 反证守卫那条：一条纪律若只写在文档里，根因是缺自动复核通道，不是这次忘了查）。
CAPTURE_FUNCS_PY = CAPTURE_FUNCS

#: 半修站点现读：**等号格**——多一处即红（半修蔓延），少一处也红
#: （逼一次显式收数，与本文件"降要看得见"同一手法）。
#:
#: 34 → 29 这一步不是放宽，是"先把看不见的挖出来、再吃掉生产与 CI 脚本那 5 处"：
#: 旧基线 27 是在**盲谓词**下量的——它只认字面 list 形态的 argv，且把"全文出现过
#: `PYTHONIOENCODING` 这个词"当成钉过写侧（docstring 提一句就整档免检）。两处修好后真值 34，
#: 本批把 `neurova/` 与 `scripts/` 的 5 处两头钉齐（这两族的子进程跑在真流水线里，
#: 中文路径下坏得最静默），剩 29 处全在 `tests/` 下，按档继续分批消化。
#:
#: 29 → 27（§6-235 消化第一步）：**这两处不是被吃掉的存量，是识别器第一次认得
#: `env=dict(os.environ, PYTHONIOENCODING=...)` 这一形**——那两个文件本来就两头钉齐了
#: （`tests/unit/memory/test_regression_worker_cleanup.py`、
#: `tests/unit/test_manual_scripts_are_not_collectible.py`）。假阳性留在账里，下一轮收数
#: 就会把"谓词修准"读成"有人治理了两处"，所以由
#: `test_knownBothPinnedFilesAreNotCountedAsHalfPinned` 反过来钉住这两档不许再进账。
HALF_PINNED_BASELINE = 27


def _callNodes(source: str):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                and fn.value.id == "subprocess" and fn.attr in CAPTURE_FUNCS:
            out.append(node)
    return out


def _pythonChildArgvNames(source: str) -> set:
    """收集 `name = [sys.executable, ...]` 这类变量形态的 argv 名。

    原谓词只认**字面 list**，于是 `argv = [sys.executable, "-c", code]` 先落变量再传给
    `subprocess.run(argv, ...)` 的写法一概看不见——实测这种"半修"另有 6 处（本仓路径含中文，
    它们和字面形态一样会静默毁读数）。看不见就不是"没病"，是"病历上没写"。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        first = node.value.elts[0] if node.value.elts else None
        isPy = (isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name)
                and first.value.id == "sys" and first.attr == "executable")
        if not isPy:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                names.add(tgt.id)
    return names


def _argvFirstIsPythonChild(node, varNames=frozenset()) -> bool:
    """argv 首项是 `sys.executable`（字面）或指向一个已知以它为头元素的变量 ⇒ 子进程是本仓 Python 件。"""
    argv = node.args[0] if node.args else None
    if isinstance(argv, ast.Name):
        return argv.id in varNames
    if not isinstance(argv, ast.List) or not argv.elts:
        return False
    first = argv.elts[0]
    if isinstance(first, ast.Name):
        return first.id in varNames
    return (isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name)
            and first.value.id == "sys" and first.attr == "executable")


def _writesSideIsPinnedInFile(source: str) -> bool:
    """写侧到底钉没钉——按**代码形态**判，不按"全文有没有这个词"判。

    原判定是 `"PYTHONIOENCODING" in source`：在 docstring 里提一句这个词就整档免检，
    而被放行的恰好是"写了说明、没钉 env"那一类——最像已修的样子（AGENTS.md「钉形态不钉词」）。
    现在只认真写法：字典键（`env={..., "PYTHONIOENCODING": ...}`）、下标赋值
    （`os.environ["PYTHONIOENCODING"] = ...` / `env["PYTHONIOENCODING"] = ...`）、
    以及 `dict(...)` 的**关键字实参**形（`env=dict(os.environ, PYTHONIOENCODING="utf-8")`）。
    第三形是本轮补的：漏认它不会让计数"更严"，只会把**已经修对的文件**记进半修账——
    账越不准，下一次收数越会把"识别器坏了"读成"存量在涨"（现仓实测两处，见
    `test_knownBothPinnedFilesAreNotCountedAsHalfPinned`）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "PYTHONIOENCODING"
                for k in node.keys):
            return True                      # env={..., "PYTHONIOENCODING": "utf-8"}
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value == "PYTHONIOENCODING":
            return True                      # os.environ["PYTHONIOENCODING"] = "utf-8"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "dict" and any(
                    kw.arg == "PYTHONIOENCODING" for kw in node.keywords):
            return True                      # dict(os.environ, PYTHONIOENCODING="utf-8")
    return False


def halfPinnedSites() -> list:
    """`(文件, 行号)`：按 utf-8 解 Python 子件，而该文件里没有一处真把写侧钉上 `PYTHONIOENCODING`。"""
    out = []
    for root in SCAN_ROOTS:
        for path in filesUnder(REPO_ROOT / root):
            if path.suffix != ".py":
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "subprocess" not in source or "sys.executable" not in source:
                continue
            varNames = _pythonChildArgvNames(source)
            pinned = _writesSideIsPinnedInFile(source)
            for node in _callNodes(source):
                kws = {k.arg for k in node.keywords if k.arg}
                if "encoding" not in kws or not _argvFirstIsPythonChild(node, varNames):
                    continue
                encNode = next(k for k in node.keywords if k.arg == "encoding")
                enc = ast.unparse(encNode.value).strip("'\"").lower().replace("-", "")
                if enc == "utf8" and not pinned:
                    out.append((path.relative_to(REPO_ROOT).as_posix(), node.lineno))
    return sorted(out)


def test_halfPinnedPythonChildSitesMatchTheCountedBaseline():
    """半修面等号格：不许蔓延，也不许悄悄变好不收数。"""
    now = halfPinnedSites()
    assert len(now) == HALF_PINNED_BASELINE, (
        "半修（父端 utf-8 解 Python 子件、子端没钉 PYTHONIOENCODING）站点数与基线不符："
        "现读 %d / 基线 %d。\n多了＝新写了一处半修，把子端 env 一起钉上；"
        "少了＝有人收掉了存量，把 `HALF_PINNED_BASELINE` 收下去再提交。\n%s"
        % (len(now), HALF_PINNED_BASELINE, now[:HALF_PINNED_BASELINE + 6]))


def test_bothEndsPinnedRoundTripsNonAsciiWhileHalfPinDoesNot():
    """行为对照格：两头钉 ⇒ 中文原样回；只钉父端 ⇒ 在本机码页非 UTF-8 时必然读坏。

    这一格是**探测器自身的自证**：上面那条数形状，这条证形状背后那个危害是真的。
    本机 locale 已是 UTF-8 时反向那半恰好不成立——如实 skip，不假装验过。
    """
    marker = "项目Neurova-中文回显"
    code = "import sys\nsys.stdout.write(%r)\n" % marker
    envPinned = dict(os.environ)
    envPinned["PYTHONIOENCODING"] = "utf-8"
    pinned = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=envPinned, timeout=120)
    assert pinned.returncode == 0, pinned.stderr[-400:]
    assert pinned.stdout == marker, f"两头钉后仍读坏：{pinned.stdout!r}"

    preferred = locale.getpreferredencoding(False).lower().replace("-", "")
    if preferred == "utf8":
        pytest.skip("本机首选编码已是 UTF-8——半修在这一台机器上恰好读得对，反向那半无从验")
    if os.environ.get("PYTHONIOENCODING"):
        pytest.skip("父进程环境已带 PYTHONIOENCODING，半修那一发不再代表真实形态")
    half = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert half.stdout != marker, (
        "半修那发竟读对了（本机首选编码 %s）——探测口径变了，重定这一半而不是留着当恒真"
        % locale.getpreferredencoding(False))


def test_consoleToolChildUsesTheConsoleCodecNotUtf8():
    """原生控制台件（`schtasks`）不许"顺手统一"成 utf-8：它按控制台码页输出，回显里带中文路径。

    记的是**判断**而不是编码常量：`scripts/desktop/wsl_crash_cleanup.py` 那两处按
    `locale.getpreferredencoding(False)` 显式解（写出来而不是靠默认值，默认值随父进程 locale 漂）。
    将来若有人加 `wsl` 件的捕获，那是第三种编码（UTF-16LE），本格不含它 ⇒ 必须另判，不许并进这一条。
    """
    src = (REPO_ROOT / "scripts" / "desktop" / "wsl_crash_cleanup.py").read_text(encoding="utf-8")
    sites = []
    for node in _callNodes(src):
        argv = node.args[0] if node.args else None
        if not (isinstance(argv, ast.List) and argv.elts
                and getattr(argv.elts[0], "value", None) == "schtasks"):
            continue
        enc = next((k for k in node.keywords if k.arg == "encoding"), None)
        assert enc is not None, f"schtasks 调用没写 encoding（回到 §6-64 那一态）：行 {node.lineno}"
        sites.append((node.lineno, ast.unparse(enc.value)))
    assert sites, "schtasks 捕获点形状变了——本格会空转，先按实状重定取数口径"
    wrong = [(lineno, enc) for lineno, enc in sites if "getpreferredencoding" not in enc]
    assert not wrong, (
        f"原生控制台件被改成按 utf-8 解：{wrong}——schtasks 按控制台码页输出且回显含中文路径，"
        "utf-8 会把回显里的中文换成 U+FFFD（看着像没报错、实际读坏）")
