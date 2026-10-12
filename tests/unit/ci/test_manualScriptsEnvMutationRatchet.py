# -*- coding: utf-8 -*-
"""只降不升棘轮：`tests/manual/` 脚本不得新增"模块顶层改进程 env"的落点（§6-66 的实际待办）。

为什么不退役拦截层、却要拦住新增：`tests/manual/conftest.py` 的两道收集拦截
（`pytest_configure` 拒显式点名 + `pytest_ignore_collect` 兜默认收集）是**收集期根修**，
不是 consumer-side guard——这些脚本必须在 `import neurova` **之前**改环境，
被 pytest 导入就是把变量带进整个跑测进程、无声掩盖一切依赖数据根的判据
（本仓实测掩盖过一次会话落点守卫，见 §6-31 与 `4ef87e3d`）。
所以"改造完脚本就拆掉拦截"这条路不成立；成立的是**别让它继续长**。

现值本轮 AST 实测：**20 个文件 / 25 处**模块顶层 env 改写
（`os.environ[...] = ...`、`os.environ.setdefault(...)`、`os.environ.update(...)`）。
`tests/manual/conftest.py` 的 docstring 自记"21 个文件 27 处"——与本数基本吻合，
差 1 个文件 2 处，属口径微差或后续一次动过，**不构成"记载已漂"**。

（这里有一段自纠值得留着：本判据第一版把 `ast.walk` 直接从顶层语句下钻，
于是连函数体内的 `os.environ[...] = ` 也算了进去，量出 24 文件 / 32 处；
差点据此在台账里写"conftest 自记数漂了 3 处"。是文件内那条反向断言
`test_functionLevelEnvWriteIsNotCounted` 把它抓回来的——**只有顶层那条才会在
import 时执行**，函数体内改 env 不是本判据要防的形态。）

正确形态已在仓内：走 `tests.manual._liveVerifyIsolation` 的
`isolatedDataRoot()` / `useDataRoot()` 单点，脚本不再自己拼数据根。
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANUAL_DIR = REPO_ROOT / "tests" / "manual"

#: 冻结基线（本轮 AST 实测 20 文件 / 25 处，逐文件计数）。只准降不准升；新文件出现即红。
#: `_liveVerifyIsolation.py` **不在**名单里——它是唯一注入口本身，改 env 是它的职责；
#: 但也刻意不写豁免清单，它就是普通的一条基线条目（现在它顶层不再直接写 env，
#: 单点逻辑收在函数里，所以计数为 0）。豁免清单一开口，后面每个"看着像单点"的
#: 落点都会来要一条。
BASELINE: dict[str, int] = {
    "audit_context_chain_repair_90.py": 1,
    "channel_credential_sealing_290.py": 3,
    "context_archive_moment_and_budget_90.py": 2,
    "context_budget_face_retirement_90.py": 2,
    "context_pool_settings_face_retirement_90.py": 2,
    "context_scale_b5_90.py": 1,
    "context_vector_batch_90.py": 1,
    "fold_layer_index_t11b_90.py": 1,
    "fold_resolution_latency_t11c_90.py": 1,
    "fold_resolution_t11c_90.py": 1,
    "fold_rollup_t11e_90.py": 1,
    "fold_span_drilldown_t11d_90.py": 1,
    "pool_registry_retire_and_p10_90.py": 1,
    "provider_cache_truth_wiring_90.py": 1,
    "reflection_view_accounting_b6_11.py": 1,
    "source_priority_single_source_90.py": 1,
    "tool_call_pairing_t10a_90.py": 1,
    "tool_call_record_identity_t10a_90.py": 1,
    "turn_identity_wiring_90.py": 1,
    "turn_session_identity_t03b_90.py": 1,
}


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _walkTopLevel(node: ast.AST):
    """走模块顶层语句树，但**不进**函数/类/lambda 体。

    第一版写成 `for stmt in tree.body: for sub in ast.walk(stmt)` —— `ast.walk` 会
    一路下钻进 `FunctionDef` 体内，于是"函数里改 env"被算成"顶层改 env"，
    而只有顶层那条才会在 import 时执行。这个错是被本文件自己的反向断言抓出来的
    （`test_functionLevelEnvWriteIsNotCounted`），不是靠肉眼看出来的。
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        for child in ast.iter_child_nodes(cur):
            if isinstance(child, _SCOPES):
                continue
            stack.append(child)


def _topLevelEnvWrites(source: str) -> int:
    """数**模块顶层**（不在函数/类/lambda 体内）改写 `os.environ` 的语句。

    只看顶层：函数体内改 env 是脚本自己的局部行为，不会被收集期执行；
    顶层那一条才是"import 即污染进程"的形态。
    判据取 AST 代码形态而不是搜文本——脚本里提一句 `os.environ` 的注释不该被判红。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in _walkTopLevel(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute)
                        and t.value.attr == "environ"
                        and isinstance(t.value.value, ast.Name)
                        and t.value.value.id == "os"):
                    count += 1
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and node.func.attr in ("setdefault", "update")):
            count += 1
    return count


def scanManualEnvWrites(directory: pathlib.Path = MANUAL_DIR) -> dict[str, int]:
    perFile: dict[str, int] = {}
    for path in sorted(directory.glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = _topLevelEnvWrites(source)
        if n:
            perFile[path.name] = n
    return perFile


def test_manualDirIsReallyThereAndScanned():
    """覆盖性前置：目录不存在或空得离谱时，"零违规"是假的绿。

    这条不是装饰——同批的编码棘轮首跑就因为仓库根写成 `parents[2]`（应为 `[3]`）
    把扫描面指成了空集，若无这条断言，那把棘轮会永远绿着。
    """
    assert MANUAL_DIR.is_dir(), f"扫描根不存在：{MANUAL_DIR}"
    total = len(list(MANUAL_DIR.glob("*.py")))
    assert total > 50, f"tests/manual 的脚本数异常低（{total}），扫描根或目录结构被动过"


def test_ratchetDoesNotRise():
    """每个文件只能持平或下降；新文件带顶层 env 改写一律拦。"""
    now = scanManualEnvWrites()
    grew = {f: (now[f], BASELINE.get(f, 0)) for f in now if now[f] > BASELINE.get(f, 0)}
    assert not grew, (
        "tests/manual 又新增了在模块顶层改写 os.environ 的脚本。这类脚本被 pytest 收集即"
        "导入、导入即把变量带进整个跑测进程，会无声掩盖所有依赖数据根/落点的判据"
        "（`4ef87e3d` 把拦截挡在 `pytest_configure` 就是因为这个）。\n"
        + "\n".join(f"  {f} 现 {n} 处 / 基线 {b} 处" for f, (n, b) in sorted(grew.items()))
        + "\n修法：改用 `tests.manual._liveVerifyIsolation` 的 isolatedDataRoot() / "
          "useDataRoot() 单点，别在脚本里手拼数据根（同一件事手抄二十份正是被收口的形态）。"
    )


def test_ratchetRecordsImprovementLoudly():
    """降了要**红着**提醒收基线——只降不升要真降，就得让降可见。"""
    now = scanManualEnvWrites()
    dropped = {f: (BASELINE[f], now.get(f, 0)) for f in BASELINE if now.get(f, 0) < BASELINE[f]}
    assert not dropped, (
        "以下脚本的顶层 env 改写比基线少了——把基线收下去再提交，别让它悬着：\n"
        + "\n".join(f"  {f} 基线 {b} 处 / 现 {n} 处" for f, (b, n) in sorted(dropped.items()))
    )


def test_baselineMatchesMeasuredCount():
    """基线自身可核：条目数与总站点数必须等于本轮实测的 20 / 25。

    钉这一条而不是只信那张字典，是因为基线一旦被手抄或被"顺手调一下"，
    棘轮就会从第一天起对不上账——而对不上账的方向永远是放行。
    """
    now = scanManualEnvWrites()
    assert len(BASELINE) == 20 and sum(BASELINE.values()) == 25, (
        f"基线常量自身与记录不符：{len(BASELINE)} 文件 / {sum(BASELINE.values())} 处"
    )
    assert len(now) == 20 and sum(now.values()) == 25, (
        f"现测与基线不符（{len(now)} 文件 / {sum(now.values())} 处）——"
        "要么真有人动了脚本，要么扫描根/谓词被改坏，两种都要当场看见"
    )


def test_ratchetBitesOnAnInjectedScript(tmp_path):
    """探针：真往扫描目录种一个顶层改 env 的脚本，必须被数到。"""
    probe = MANUAL_DIR / "zzEnvRatchetProbe_tmp.py"
    assert not probe.exists(), "上一次探针残留会污染基线"
    try:
        probe.write_text(
            'import os\n\nos.environ.setdefault("NEUROVA_DATA_DIR", "/tmp/zz")\nprint("probe")\n',
            encoding="utf-8",
        )
        assert scanManualEnvWrites().get(probe.name) == 1, "注入的违规未被扫到（棘轮空转）"
    finally:
        probe.unlink(missing_ok=True)


def test_functionLevelEnvWriteIsNotCounted():
    """反向钉：函数体内改 env 不算——被收集期执行的是顶层，不是它。

    少了这条，谓词宽窄无人知道，基线会被误伤项稀释。
    """
    src = 'import os\n\n\ndef main():\n    os.environ["X"] = "1"\n'
    assert _topLevelEnvWrites(src) == 0, "函数体内的 env 改写被误算成顶层"
