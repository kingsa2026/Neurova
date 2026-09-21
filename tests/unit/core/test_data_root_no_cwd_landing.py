"""数据面落点只准经数据根推导：CWD 相对与"第二份根"一律为零。

病灶（Issue #75 残余项，PR #98 §7.6 登记）：记忆与知识写入面已收口到
`core/data_root.py`，但各服务自己的 `data/<sub>` 配置/状态目录仍在上百处按 CWD 拼
（`"data/x.json"`、`Path("data")`、`os.environ.get(..., "data/x.json")`、函数默认
参数 …），另有一批按层数/项目根**另推一份根**（`PROJECT_ROOT / "data"`、
`Path(__file__).parents[N] / "data"`、`os.path.join(dirname(__file__), "..", "..", "data")`）。
前者换个工作目录就换个库；后者虽绝对，却是同一根的**第二份定义**——两者都让
"数据在哪儿"没有唯一答案，正是仓库根那份 71,831 行散落库的成因。

判据（逐条可由本文件复现，不用替身）：

1. `neurova/` 与 `scripts/`（生产代码）内不得出现 CWD 相对的数据落点；
2. 不得出现按层数/项目根另推的数据根——唯一推导点是 `neurova/core/data_root.py`；
3. `resolveDataPath` 对绝对路径原样放行（调用方与测试显式指定的落点不受影响），
   对相对名按数据根解析。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT_MODULE = PROJECT_ROOT / "neurova" / "core" / "data_root.py"
SCANNED_ROOTS = ("neurova", "scripts")

# ── 扫描规则 ────────────────────────────────────────────────────────────
# 只认"落点"形态，不认"data"这个词本身：字典键、`.get("data")` 取值、
# `filter="data"`（zipfile 形参）都不是路径，不许误伤。
_PATH_CALLS = {"Path", "PurePath", "join", "joinpath"}
_REPO_ROOT_MARKERS = ("getcwd()", "__file__", "PROJECT_ROOT", "REPO_ROOT",
                      "_REPO_ROOT", "project_root")
_CWD_PREFIXES = ("data/", "data\\", "./data/", "./data\\", ".\\data\\", "../data/")


def _sourceOf(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - 反解失败时按"不像根"处理
        return ""


def _isPathCall(node: ast.AST) -> bool:
    func = getattr(node, "func", None)
    if isinstance(func, ast.Name):
        return func.id in _PATH_CALLS
    if isinstance(func, ast.Attribute):
        return func.attr in _PATH_CALLS
    return False


def _docstringNodes(tree: ast.AST) -> set:
    """模块/类/函数首条字符串是文档，不是落点。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _defaultNodes(tree: ast.AST) -> set:
    """函数参数默认值：`db_path: str = "data/x.db"` 是典型 CWD 相对落点。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
                for sub in ast.walk(default):
                    ids.add(id(sub))
    return ids


def _cwdRelativeHits(path: Path) -> list:
    """返回该文件里 CWD 相对 / 第二份根的 data 落点（行号 + 原因）。"""
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    docstrings = _docstringNodes(tree)
    defaults = _defaultNodes(tree)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    hits = []

    def record(node, reason):
        hits.append((node.lineno, reason))

    for node in ast.walk(tree):
        # f-string：`f"data/agents/{agent_id}/skills"` 的开头常量即落点前缀
        if isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str) \
                    and head.value.startswith(("data/", "data\\")):
                record(node, "fstring 前缀按 CWD 拼")
                continue

        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        value = node.value
        if id(node) in docstrings:
            continue
        parent = parents.get(node)
        # f-string 的首段常量已在上面按整体记过，不再单独记一次
        if isinstance(parent, ast.JoinedStr) and parent.values and parent.values[0] is node:
            continue

        # 1. `"data/..."` / `"./data/..."` 相对字面量（字典键位置除外）
        if value.startswith(_CWD_PREFIXES):
            if isinstance(parent, ast.Dict) and node in parent.keys:
                continue
            if isinstance(parent, ast.keyword):
                continue
            record(node, "相对字面量 %r" % value)
            continue

        # 2. 恰好是 "data"：只在路径构造 / 二分片 / 默认参数 / 配置兜底位置才算落点
        if value != "data":
            continue
        if id(node) in defaults:
            record(node, "函数默认参数按 CWD 拼")
            continue
        if isinstance(parent, ast.Call) and _isPathCall(parent):
            record(node, "Path/join 按 CWD 拼")
            continue
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) \
                and parent.func.attr == "get" and len(parent.args) >= 2 \
                and parent.args[1] is node:
            record(node, "配置兜底按 CWD 拼")
            continue
        if isinstance(parent, ast.BinOp):
            sibling = parent.right if parent.left is node else parent.left
            text = _sourceOf(sibling)
            if any(marker in text for marker in _REPO_ROOT_MARKERS):
                record(node, "另推一份数据根（%s）" % text.strip()[:60])
            continue
        # `os.path.join(x, "data")`：与层数反推或 getcwd 同现才算第二份根
        if isinstance(parent, ast.Call) and parent.args and node in parent.args:
            argv = [_sourceOf(arg) for arg in parent.args]
            if any(".." in text or "getcwd" in text or "__file__" in text for text in argv):
                record(node, "另推一份数据根（join 反推）")

    return sorted(set(hits))


def _scannedFiles() -> list:
    files = []
    for root in SCANNED_ROOTS:
        for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts or path == DATA_ROOT_MODULE:
                continue
            files.append(path)
    return files


class TestResolveDataPath:
    """归一路径的唯一入口：绝对路径放行，相对名落数据根。"""

    def test_relativeNameLandsUnderDataRoot(self, monkeypatch, tmp_path):
        from neurova.core.data_root import resolveDataPath

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))

        assert resolveDataPath("webhooks.json") == tmp_path / "webhooks.json"
        assert resolveDataPath("storage/runs.db") == tmp_path / "storage" / "runs.db"

    def test_absolutePathIsPassedThrough(self, monkeypatch, tmp_path):
        """显式指定的绝对落点（调用方注入 / 测试隔离）不得被改写。"""
        from neurova.core.data_root import resolveDataPath

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "root"))
        explicit = tmp_path / "elsewhere" / "isolated.db"

        assert resolveDataPath(str(explicit)) == explicit
        assert resolveDataPath(explicit) == explicit

    def test_relativeResultIsAlwaysAbsolute(self, monkeypatch, tmp_path):
        from neurova.core.data_root import resolveDataPath

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "root"))

        assert Path(resolveDataPath("a/b.json")).is_absolute()


class TestNoCwdRelativeDataLandingInProduction:
    """生产代码内 CWD 相对与第二份根的 data 落点必须为零。"""

    def test_productionTreeHasNoCwdRelativeDataLanding(self):
        offenders = []
        for path in _scannedFiles():
            for lineno, reason in _cwdRelativeHits(path):
                offenders.append("%s:%d: %s" % (path.relative_to(PROJECT_ROOT), lineno, reason))
        assert offenders == [], (
            "仍有 %d 处数据落点没走数据根（换个工作目录就换个库）：\n  %s\n"
            "修复：`neurova/core/data_root.py` 的 `get_data_root()` / "
            "`resolveDataPath()`，不要在各模块自己拼 `data/`。"
            % (len(offenders), "\n  ".join(offenders))
        )

    def test_scannerHasTeethOnKnownShapes(self, tmp_path):
        """反向控制：扫描器必须真的认得出各类落点，否则上面那条是空断言。"""
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import os\n"
            "from pathlib import Path\n"
            'A = "data/a.json"\n'
            'B = Path("data")\n'
            'C = os.environ.get("X", "data/c.json")\n'
            'D = Path(__file__).resolve().parents[2] / "data"\n'
            'E = f"data/agents/{x}/skills"\n'
            "F = PROJECT_ROOT / \"data\" / \"f.db\"\n"
            'def g(db_path: str = "data/g.db"):\n'
            "    return db_path\n"
            'H = payload.get("data")\n'
            'I = cfg.get("dir", "data")\n'
        , encoding="utf-8")
        reasons = [reason for _, reason in _cwdRelativeHits(probe)]

        assert len(reasons) == 8, "扫描器漏认或误伤：%s" % reasons
        assert not any("payload" in reason for reason in reasons), \
            "取值 .get(\"data\") 被误判成落点"


class TestGuardIsProtected:
    """守卫必须真进 CI 受保护子集——"绿"要和"跑过"是同一件事。"""

    def test_listedInProtectedSubset(self):
        listed = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt").read_text(
            encoding="utf-8")
        assert "tests/unit/core/test_data_root_no_cwd_landing.py" in listed, \
            "本守卫不在受保护子集里，CI 不会跑它"
