# -*- coding: utf-8 -*-
"""子进程文本读取必须显式声明编码——不得落回机器的 ANSI 码页（工单集 T-15）。

## 病灶（2026-09-30 本机实证）

`subprocess.run(..., text=True)` 不写 `encoding=` 时，解码用的是
`locale.getpreferredencoding()`——中文 Windows 上是 **cp936/GBK**。
git 的输出里有 173 条 UTF-8 中文路径（现场复算：
`git -c core.quotepath=false ls-files` 含非 ASCII 者 173/5064），GBK 解不动 ⇒
**读取线程直接抛 UnicodeDecodeError**，而 subprocess 把这个异常吞在线程里，
主线程只看到 `proc.stdout is None`：

```
    return [line for line in proc.stdout.split("\n") if line.strip()]
AttributeError: 'NoneType' object has no attribute 'split'
PytestUnhandledThreadExceptionWarning: Exception in thread Thread-2 (_readerthread)
UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 60785
```

后果不是"这台机器报错"这么简单：`scripts/scan_docs_refs.py` 是文档台账的事实源，
它一挂，`tests/unit/test_docs_name_collision_guard.py` 与
`tests/unit/test_legacy_ref_ledger_guard.py` 就整族红（本机实测 **13 FAILED + 6 ERROR**），
于是每次本地全量回归都要人肉解释"这 19 条不是我改的"——守卫失去意义，
比没有守卫更糟（假红会训练人去忽略红）。

## 判据取向

- **平台无关**：不靠"找一台 GBK 机器"复现，而是把 `locale.getpreferredencoding` 毒成
  `ascii` 再跑真扫描器——本机 173 条中文路径必然触发，Linux 上同样成立。
- **棘轮只降不升**：全仓按 AST 数出 **109 处 / 59 个文件**（含生产码 12 处：
  `camofox_supervisor` 3、`env_check` 2、`image_pipeline/docker_builder` 6、
  `sandbox/exec_sandbox` 1）。一次改 109 处不是本单的范围，但**新增一处必须红**。
- 正反对照都要有：注入一条能被数到（判据不是空转），声明了 encoding 的不被数到
  （判据不是把所有 text=True 一棍子打死）。
"""

from __future__ import annotations

import ast
import locale
import os
import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]

# 只降不升的基线（2026-09-30 现场数出：109 处 / 59 个文件）。
# 往下调时请在提交说明里点名修掉了哪些落点。
_BASELINE_MAX_SITES = 109

_SKIP_PREFIX = (".venv/", "NeurUI/node_modules/", "build/", "dist/")
_SKIP_PARTS = ("/__pycache__/", "src-tauri", "/target/")
# 遍历必须剪枝：整仓 rglob 会把 node_modules / .git 全走一遍，本判据在 30s 门禁下直接超时
_PRUNE_DIRS = {".git", ".venv", "node_modules", "__pycache__", "target", "build", "dist", ".mypy_cache", ".pytest_cache"}
_CHILD_CALLS = {"run", "check_output", "Popen", "communicate"}


def pythonFiles(root: pathlib.Path) -> list:
    """root 下的待判 py 文件（自顶向下遍历，命中剪枝目录就不再进去）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(pathlib.Path(dirpath) / fn)
    return out


def sitesWithoutEncoding(root: pathlib.Path) -> list:
    """数出「以文本模式读子进程输出、却没声明 encoding/errors」的落点。

    按 AST 判而非子串：注释与 docstring 里提到 `text=True` 不算落点
    （本轮在别处就栽过子串扫描的误判）。
    """
    hits = []
    for path in pythonFiles(root):
        rel = _relativeToRoot(path)
        if rel.startswith(_SKIP_PREFIX) or any(part in rel for part in _SKIP_PARTS):
            continue
        if rel == _selfPath():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if name not in _CHILD_CALLS:
                continue
            kwargs = {k.arg for k in node.keywords}
            if not ({"text", "universal_newlines"} & kwargs):
                continue
            if not ({"encoding", "errors"} & kwargs):
                hits.append((rel, node.lineno))
    return hits


def _selfPath() -> str:
    return str(pathlib.Path(__file__)).replace("\\", "/")


def _relativeToRoot(path: pathlib.Path) -> str:
    """相对仓根的 posix 路径；仓外文件（tmp_path 夹具）退化为文件名。

    不这么做的话剪枝前缀 `.venv/`、`NeurUI/node_modules/` 永远匹配不上绝对路径，
    基线数会随人在哪台机器上跑而变（本判据当场就这么错了一次：110 ≠ 109）。
    """
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


class TestScannerIsNotLocaleDependent:
    """行为判据：文档扫描器在非 UTF-8 码页的机器上必须照样出数。"""

    def test_trackedFilesSurvivesPoisonedLocale(self, monkeypatch):
        scanner = pytest.importorskip("scripts.scan_docs_refs")
        # 毒掉码页而不是换机器：ascii 解不动 173 条中文路径里的任何一条
        monkeypatch.setattr(locale, "getpreferredencoding", lambda *a, **k: "ascii")
        files = scanner.trackedFiles()
        assert files, "非 UTF-8 码页下扫描器取不到入库文件清单——台账事实源在该机器上是死的"
        assert any(any(ord(ch) > 127 for ch in f) for f in files), (
            "夹具前提不成立：本仓已入库路径里没有非 ASCII 名，本判据在该环境无判别性"
        )

    def test_docsScannerCallSitesDeclareEncoding(self):
        """具体钉桩：文档扫描器自己不得再有未声明编码的子进程读点（防回潮）。"""
        hits = [
            h for h in sitesWithoutEncoding(PROJECT_ROOT / "scripts")
            if h[0].endswith("scan_docs_refs.py")
        ]
        assert not hits, f"文档台账事实源又落回机器码页（行 {[h[1] for h in hits]}）"


class TestRatchet:
    def test_siteCountDoesNotGrow(self):
        hits = sitesWithoutEncoding(PROJECT_ROOT)
        assert len(hits) <= _BASELINE_MAX_SITES, (
            f"未声明编码的子进程文本读点从 {_BASELINE_MAX_SITES} 涨到 {len(hits)}——"
            "新增一处就多一台机器上的假红。请给 subprocess 传 encoding=\"utf-8\""
            "（外来命令再加 errors=\"replace\"）"
        )

    def test_injectedSiteIsCounted(self, tmp_path):
        """正对照：判据必须真能数到新落点，否则棘轮是空转的。"""
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import subprocess\n"
            "subprocess.run(['git', 'ls-files'], capture_output=True, text=True)\n",
            encoding="utf-8",
        )
        hits = sitesWithoutEncoding(tmp_path)
        assert len(hits) == 1, f"注入的未声明编码落点没被数到：{hits}"

    def test_declaredEncodingIsNotCounted(self, tmp_path):
        """反对照：显式声明编码的调用不得被算进基线（否则修法被逼成去掉 text=True）。"""
        probe = tmp_path / "ok.py"
        probe.write_text(
            "import subprocess\n"
            "subprocess.run(['git', 'ls-files'], capture_output=True, text=True,\n"
            "                 encoding='utf-8', errors='replace')\n",
            encoding="utf-8",
        )
        assert sitesWithoutEncoding(tmp_path) == []
