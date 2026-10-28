# -*- coding: utf-8 -*-
"""§6-177 活体自证：非法转义修净之后，真导入不再炸，而文档文本一字未改。

判据（`tests/unit/core/test_sourceEscapeSequenceHygiene.py`）量的是"编译时警告"，本支量的是
**真进程真导入**——因为这条缺陷的害处正好在导入期：语言侧把未知转义从警告升级为错误的那天，
断的是全仓 import，而断点在别人的文档注释上。

四段读数：
① 正证：六个被改文件各起一个新进程真 import，`-W error::SyntaxWarning` 把警告抬成错误 ⇒ 全部 exit=0；
② 反证：同一形状下换成本笔修改**之前**（HEAD blob）的那份源码 ⇒ 必须非零退出，且报错点名
   `invalid escape sequence`——没有这一段，①只是"恒 0"，什么也没证；
③ 文本一字未改：每个文件取 HEAD 版与工作树版的**全部文档字符串值**逐位比对；四处被改的文档字符串
   再从**真导入后的运行时对象**取 `__doc__`，与 HEAD 源码里的对应读数逐字比（运行时读数，不是静态推断）；
④ 噪声清零：真跑一次 pytest（本批三档判据 + 那档一直替别人报转义警告的 `test_voiceEngineBridgeRetired`），
   断言 warnings 摘要里 "invalid escape sequence" 出现 0 次。

边界：全程起临时数据根（`_liveVerifyIsolation.isolatedDataRoot()`，父子进程同一个根），
不开外网、不调模型；导入副本放在仓外临时目录里，确保编译真的发生（不吃仓库里的 `.pyc`）。
"""

import ast
import pathlib
import subprocess
import sys
import tempfile
from tests.ast_scan import parseSource

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: 被本笔改动的六个文件（相对仓库根）
TARGETS = [
    "neurova/context/eviction_ledger_db.py",
    "neurova/cognitive_layers/memory_layer/muscle_memory.py",
    "scripts/desktop/package_installer_zip.py",
    "tests/unit/test_ci_npc_config_guard.py",
    "tests/unit/llm/test_ledgerTerminalVocabularySingleSource.py",
    "tests/unit/ci/test_npc_pipeline_time_budget.py",
]

failures: list[str] = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def _importInto(moduleName: str, sourcePath: pathlib.Path, env: dict):
    """在新进程里真导入那份源码：`-W error::SyntaxWarning` 抬级，`-B` 不写字节码。"""
    code = (
        "import sys, importlib\n"
        f"sys.path.insert(0, {str(sourcePath.parent)!r})\n"
        f"m = importlib.import_module({moduleName!r})\n"
        "print('imported', getattr(m, '__name__', '?'))\n"
    )
    return subprocess.run(
        [sys.executable, "-B", "-W", "error::SyntaxWarning", "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(sourcePath.parent), timeout=300,
    )


def _gitBlob(rel: str, rev: str) -> str:
    proc = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=str(REPO),
                          capture_output=True, timeout=120)
    assert proc.returncode == 0, f"取 {rev}:{rel} 失败"
    return proc.stdout.decode("utf-8", errors="replace")


def _docstringValues(src: str) -> list:
    """按源码顺序取模块/类/函数的全部文档字符串值（转义已按该版本语义解算）。"""
    out = []
    for node in ast.walk(parseSource(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                out.append(doc)
    return out


def _astDocByQualname(src: str, qual):
    """取 HEAD 源码里某个文档字符串的值：`qual=None` 是模块文档，否则 `类.方法`（两段）。

    找不到就直接抛——"取到 None 然后比通过"是弱保护那一形，这里宁可红在装配上。
    """
    tree = parseSource(src)
    if qual is None:
        return ast.get_docstring(tree, clean=False)
    clsName, funcName = qual.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == clsName:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == funcName:
                    return ast.get_docstring(item, clean=False)
    raise AssertionError(f"HEAD 源码里找不到 {qual}")


#: 本笔真正动过的那四处文档字符串（改前的值从这里取，改后的值从**真导入后的运行时对象**取）
DOC_TARGETS = [
    ("neurova/context/eviction_ledger_db.py", None),
    ("neurova/context/eviction_ledger_db.py", "EvictionLedgerDB._likeCandidates"),
    ("neurova/cognitive_layers/memory_layer/muscle_memory.py", None),
    ("neurova/cognitive_layers/memory_layer/muscle_memory.py", "MuscleMemory._extract_keywords"),
]


def _runtimeDocs(moduleName: str, env: dict, workdir: pathlib.Path) -> dict:
    """真导入后取运行时 `__doc__`——证明改的是"写法"而不是"值"。"""
    code = (
        "import sys, importlib, json\n"
        f"sys.path.insert(0, {str(workdir)!r})\n"
        f"m = importlib.import_module({moduleName!r})\n"
        f"cls = getattr(m, 'EvictionLedgerDB', None)\n"
        "out = {'module': m.__doc__}\n"
        "for cname, fname in (('EvictionLedgerDB', '_likeCandidates'), ('MuscleMemory', '_extract_keywords')):\n"
        "    obj = getattr(m, cname, None)\n"
        "    if obj is None:\n"
        "        continue\n"
        "    fn = getattr(obj, fname, None)\n"
        "    out[cname + '.' + fname] = getattr(fn, '__doc__', None) if fn else None\n"
        "print('@@' + json.dumps(out, ensure_ascii=True))\n"
    )
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env,
                          cwd=str(workdir), timeout=300)
    if proc.returncode != 0:
        print("     导入失败：" + proc.stderr[-300:])
        return {}
    line = next((l for l in proc.stdout.splitlines() if l.startswith("@@")), None)
    if line is None:
        return {}
    import json

    return json.loads(line[2:])


def _place(workdir: pathlib.Path, rel: str, content: str, slot: int) -> str:
    """把源码平铺成仓外临时目录里的 `esc_<slot>.py` 并返回模块名。

    平铺是刻意的：若照搬包路径，临时目录里那个残缺的 `neurova` 包会**顶掉**真包，
    被测文件里的 `from neurova.core import ...` 当场 ImportError——那是夹具的错，不是链路的错。
    平铺后绝对导入仍走真仓库（PYTHONPATH），而 `invalid escape sequence` 发生在**编译期**，
    编译期早于执行期，所以抬级后照样先炸在转义那行——反证那一段要的正是这个形状。
    """
    dest = workdir / f"esc_{slot}.py"
    dest.write_text(content, encoding="utf-8")
    return f"esc_{slot}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import os

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    env = dict(os.environ)
    env["NEUROVA_DATA_DIR"] = str(root)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    # 子进程一律 UTF-8：本机控制台是 cp936，读数里一个「↔」就能把探针自己打崩
    # （被测对象没坏而脚本先崩那一形，这次崩在 json.dumps 那行）
    env["PYTHONIOENCODING"] = "utf-8"
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="escapeImport-"))
    print(f"数据根（临时）：{root}")
    print(f"导入副本目录（仓外）：{workdir}")

    print("\n① 正证：六个被改文件，新进程真导入，警告抬成错误也不炸")
    for slot, rel in enumerate(TARGETS):
        moduleName = _place(workdir, rel, (REPO / rel).read_text(encoding="utf-8", errors="replace"), slot)
        proc = _importInto(moduleName, workdir / f"{moduleName}.py", env)
        noisy = "invalid escape sequence" in (proc.stderr + proc.stdout)
        _check(proc.returncode == 0 and not noisy,
               f"真导入 exit={proc.returncode}：{rel}"
               + ("" if proc.returncode == 0 else f" | stderr 尾部：{proc.stderr[-220:]!r}"))

    print("\n② 反证：同一形状换成修改前的 HEAD 那份源码，必须非零且点名转义")
    badRel = TARGETS[0]
    badDir = pathlib.Path(tempfile.mkdtemp(prefix="escapeImportBad-"))
    moduleName = _place(badDir, badRel, _gitBlob(badRel, "HEAD"), 900)
    proc = _importInto(moduleName, badDir / f"{moduleName}.py", env)
    _check(proc.returncode != 0, f"HEAD 版（修法前）真导入应失败：exit={proc.returncode}")
    _check("invalid escape sequence" in proc.stderr,
           f"失败原因点名转义本身而不是别的：{proc.stderr[-260:]!r}")

    print("\n③ 文本一字未改：全部文档字符串逐位相等，四处被改的另按真导入后的运行时读数核")
    for rel in TARGETS:
        headDocs = _docstringValues(_gitBlob(rel, "HEAD"))
        nowDocs = _docstringValues((REPO / rel).read_text(encoding="utf-8", errors="replace"))
        _check(headDocs == nowDocs, f"{rel}：文档字符串 {len(headDocs)} 段逐位相等")
    runtimeByKey = {}
    for slot, rel in enumerate(TARGETS[:2]):
        moduleName = _place(workdir, rel,
                            (REPO / rel).read_text(encoding="utf-8", errors="replace"), slot)
        for key, value in _runtimeDocs(moduleName, env, workdir).items():
            runtimeByKey.setdefault(rel, {})[key] = value
    for rel, qual in DOC_TARGETS:
        key = qual or "module"
        head = _astDocByQualname(_gitBlob(rel, "HEAD"), qual)
        got = runtimeByKey.get(rel, {}).get(key, "<没取到>")
        _check(isinstance(got, str) and got == head and bool(got),
               f"{rel} :: {qual or '模块文档'}：真导入后的 __doc__ 与改前逐字相等"
               f"（{len(got) if isinstance(got, str) else 0} 字，读数 {str(got)[:40]!r}）")

    print("\n④ 噪声清零：真跑 pytest，warnings 摘要里不再有转义警告")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/unit/core/test_sourceEscapeSequenceHygiene.py",
         "tests/unit/test_ci_npc_config_guard.py",
         "tests/unit/voice/test_voiceEngineBridgeRetired.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(REPO), timeout=900,
    )
    escapeLines = [l for l in proc.stdout.splitlines() if "invalid escape sequence" in l]
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "<无输出>"
    _check(not escapeLines, f"跑测输出里转义警告 0 条（实得 {len(escapeLines)} 条）")
    _check("error" not in tail.lower() and proc.returncode == 0, f"三档合跑尾部读数：{tail}")

    print()
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for f in failures:
            print("  - " + f)
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
