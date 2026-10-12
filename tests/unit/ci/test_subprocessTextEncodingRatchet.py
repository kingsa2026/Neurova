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
判定形态是**逐文件计数**而不是全局总数：
- 某文件站点数**上升**或**新文件出现** → 红（增长被止住，这是本判据的全部目的）；
- 站点数**下降** → 允许，但本文件会**红着提示"基线该收了"**，逼一次显式改基线，
  避免"偷偷比基线好"变成"再也没人回去核基线"（只降不升要真降，得让降可见）；
- 谓词过宽会误伤（`capture_output=True` 不带 `text` 拿到的是 bytes，没有解码面），
  所以有三条反向断言钉住不 flag 的形态；谓词过窄会空转，所以有注入探针钉住咬得住。
"""

from __future__ import annotations

import ast
import pathlib
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

#: 冻结基线（本轮实测：37 文件 / 59 站点）。只准降不准升。
BASELINE: dict[str, int] = {
    "scripts/ci/npc_branch_cleanup.py": 3,
    "scripts/ci/osv_audit.py": 1,
    "scripts/ci/perf_gate.py": 1,
    "scripts/ci/pip_audit_gate.py": 1,
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
    "tests/unit/cognitive_layers/memory_layer/test_temperature_single_source.py": 1,
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
