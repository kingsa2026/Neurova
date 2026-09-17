# -*- coding: utf-8 -*-
"""CI 薄环境防回归守卫（2026-09-17 cnb/GitHub 双侧 CI 红灯的根因加固）。

锁定三件事，防同源事故复发：

1. **注解地雷零命中** —— "try-import 降级为 None + 模块级注解引用该别名 +
   无 future annotations" 的文件在无包环境下导入即 AttributeError
   （moss_nano.py 实锤：CI 薄环境 numpy 缺席 → 6 个 tts 模块全灭）。
   注意 KNOWN_OPTIONAL_DEPS 登记只让巡检跳过该模块，治不了注解崩溃——
   唯一根修是注解惰性化（future import）或去掉模块级注解。
2. **静态门禁 ImportError 族捕获** —— check_imports 只捕
   ModuleNotFoundError 会漏掉 `from X import Y` 形态的可选包缺失
   （exc.name 指向 X），误报为失败。
3. **硬依赖声明完整** —— feedparser/apscheduler/segno 为裸 import 无降级，
   必须同时在 requirements-ci.txt 与 requirements-ci.lock 中声明；
   也不得被误登记进 KNOWN_OPTIONAL_DEPS（该表仅收"缺失可优雅降级"项）。
"""

import ast
import io
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------- 共享解析 ----------


def _read(*parts: str) -> str:
    return io.open(PROJECT_ROOT.joinpath(*parts), encoding="utf-8").read()


def _ci_top_packages() -> set[str]:
    """requirements-ci.txt 声明的顶层包名（规范化：小写、连字符→下划线、去 extras/版本）。"""
    pkgs = set()
    for line in _read("requirements-ci.txt").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pkgs.add(re.split(r"[>=<!\[]", line)[0].strip().lower().replace("-", "_"))
    return pkgs


def _find_annotation_mines(src: str, tree: ast.AST, exempt_tops: set[str]) -> list[str]:
    """返回 src 中命中"注解地雷"的顶层包名列表。

    地雷 = 降级导入（except ImportError 后赋 None）产生的别名，其顶层包
    不在 CI 依赖中，且该别名出现在模块级/类级注解里（导入期求值），
    且文件没有 future annotations 兜底。
    """
    if "from __future__ import annotations" in src:
        return []
    aliases: dict[str, str] = {}  # 代码别名 -> 顶层包名
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Try) and len(node.handlers) == 1):
            continue
        handler = node.handlers[0]
        if not (isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"):
            continue
        sets_none = any(
            isinstance(s, ast.Assign) and getattr(s.value, "value", 1) is None
            for s in handler.body
        )
        if not sets_none:
            continue
        for n in node.body:
            if isinstance(n, ast.Import):
                full = n.names[0].name
                aliases[n.names[0].asname or full.split(".")[0]] = full.split(".")[0]
            elif isinstance(n, ast.ImportFrom) and n.module:
                aliases[n.names[0].asname or n.names[0].name] = n.module.split(".")[0]

    def uses(alias: str, annotation: ast.expr | None) -> bool:
        return annotation is not None and alias in ast.dump(annotation)

    mines = []
    for alias, top in aliases.items():
        if top in exempt_tops:
            continue
        hit = False
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and uses(alias, node.annotation):
                hit = True
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = list(node.args.args) + list(node.args.kwonlyargs)
                if node.args.vararg:
                    args.append(node.args.vararg)
                if node.args.kwarg:
                    args.append(node.args.kwarg)
                if any(uses(alias, a.annotation) for a in args) or uses(alias, node.returns):
                    hit = True
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.AnnAssign) and uses(alias, sub.annotation):
                        hit = True
        if hit:
            mines.append(top)
    return mines


# ---------- 1. 注解地雷 ----------


class TestAnnotationMineSweep:
    def test_whole_neurova_zero_mines(self):
        """neurova/ 全目录无注解地雷（新增降级导入模块时须先惰性化注解）。"""
        exempt = _ci_top_packages() | {"neurova"}
        mines = []
        for path in sorted((PROJECT_ROOT / "neurova").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
            mines += [
                f"{path.relative_to(PROJECT_ROOT).as_posix()} -> {top}"
                for top in _find_annotation_mines(src, tree, exempt)
            ]
        assert not mines, (
            "发现注解地雷（无包环境导入即 AttributeError，CI 薄环境实锤形态）：\n"
            + "\n".join(mines)
            + "\n修复：文件头加 from __future__ import annotations（注解惰性化）"
        )

    def test_moss_nano_imports_without_numpy(self):
        """运行时契约：numpy 毒化（缺席）时 moss_nano 仍可导入。"""
        import importlib

        saved = sys.modules.get("numpy")
        sys.modules["numpy"] = None  # 强制后续 import numpy 走 ImportError 降级
        try:
            sys.modules.pop("neurova.tts.moss_nano", None)
            mod = importlib.import_module("neurova.tts.moss_nano")
            assert mod.np is None
        finally:
            if saved is None:
                sys.modules.pop("numpy", None)
            else:
                sys.modules["numpy"] = saved
            sys.modules.pop("neurova.tts.moss_nano", None)


# ---------- 2. 静态门禁捕获面 ----------


class TestStaticGateCapture:
    def test_import_sweep_catches_importerror_family(self):
        """check_imports 必须捕 ImportError 族（ModuleNotFoundError 的父类）。"""
        tree = ast.parse(_read("scripts", "ci_static_gate.py"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "check_imports"
        )
        caught = [
            h.type.id
            for h in ast.walk(fn)
            if isinstance(h, ast.ExceptHandler) and isinstance(h.type, ast.Name)
        ]
        assert "ImportError" in caught, (
            "check_imports 退化为只捕 ModuleNotFoundError 会漏掉 from-import "
            "形态的可选包缺失，误报为失败"
        )
        assert "ModuleNotFoundError" not in caught, "应捕父类 ImportError，勿再写窄类型"


# ---------- 3. 硬依赖声明 ----------


class TestHardDepsDeclared:
    # 裸 import 无降级的硬依赖：任何一侧缺席，CI 薄环境导入巡检必红
    HARD_DEPS = {"feedparser", "apscheduler", "segno"}

    def test_declared_in_requirements_ci_txt(self):
        declared = _ci_top_packages()
        missing = self.HARD_DEPS - declared
        assert not missing, f"requirements-ci.txt 缺硬依赖声明: {sorted(missing)}"

    def test_pinned_in_requirements_ci_lock(self):
        lock = _read("requirements-ci.lock")
        pinned = {
            m.group(1).lower().replace("-", "_")
            for m in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==", lock)
        }
        missing = self.HARD_DEPS - pinned
        assert not missing, f"requirements-ci.lock 缺 pin（CI uv 安装将缺包）: {sorted(missing)}"

    def test_not_registered_as_optional(self):
        """硬依赖不得进 KNOWN_OPTIONAL_DEPS（该表仅收缺失可优雅降级项）。"""
        gate = _read("scripts", "ci_static_gate.py")
        table = gate.split("KNOWN_OPTIONAL_DEPS = {", 1)[1].split("}", 1)[0]
        registered = set(re.findall(r'"([a-zA-Z_0-9]+)"', table))
        leaked = self.HARD_DEPS & registered
        assert not leaked, f"硬依赖被误登记为可选依赖: {sorted(leaked)}"


class TestRemovedPackagesStayRemoved:
    """已摘除包不得回归（CVE-2024-23342 根除处置，台账见 docs/05-reports/dependency-cve-ledger.md）。"""

    REMOVED = {"python-jose", "ecdsa"}
    _REQ_PATTERNS = {
        pkg: re.compile(rf"(?i)^{pkg.replace('-', '[-_]')}\s*[=><!~ ]") for pkg in ("python-jose", "ecdsa")
    }
    _IMPORT_PATTERN = re.compile(r"(?m)^\s*(?:from|import)\s+(?:python_)?jose\b|^\s*(?:from|import)\s+ecdsa\b")

    def _all_requirement_lines(self) -> list[str]:
        lines = []
        for name in ("requirements.txt", "requirements-ci.txt", "requirements-ci.lock"):
            lines += _read(name).splitlines()
        return lines

    def test_removed_packages_absent_from_all_requirement_files(self):
        hits = [
            line.strip()
            for line in self._all_requirement_lines()
            for pattern in self._REQ_PATTERNS.values()
            if pattern.match(line.strip())
        ]
        assert not hits, (
            f"已摘除包重新出现（CVE-2024-23342 处置倒退）: {hits}\n"
            "JWT 一律用 PyJWT；Ed25519 一律用 cryptography（见 qq.py）"
        )

    def test_no_source_references_to_removed_packages(self):
        offenders = []
        for path in list((PROJECT_ROOT / "neurova").rglob("*.py")) + list(
            (PROJECT_ROOT / "tests").rglob("*.py")
        ):
            if "__pycache__" in path.parts:
                continue
            if self._IMPORT_PATTERN.search(path.read_text(encoding="utf-8")):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
        assert not offenders, f"已摘除包的 import 引用复发: {offenders}"
