#!/usr/bin/env python3
"""Neurova CI 静态门禁（Static Gate）。

目标：把本次代码审计发现的三类"低级但高危"缺陷挡在 CI 里，成本极低：
  1. 语法错误（SyntaxError）          -> compileall
  2. 未定义名称（NameError 隐患）     -> pyflakes "undefined name"
  3. 模块导入即崩（import 失败）      -> 全模块导入巡检

设计原则：
  - 只拦截"代码缺陷"，不拦截"环境缺依赖"。
    对已知可选重依赖（numpy/torch/onnxruntime 等）缺失导致的 ModuleNotFoundError
    记为 OPTIONAL-SKIP（优雅降级），不计为失败。
  - 排除 run-on-import 的独立脚本子包（neurova.memory.scripts），
    避免导入巡检触发写库等副作用。
  - 任一硬性检查失败 -> 退出码非 0，供 CI 判定。

用法：
    python scripts/ci_static_gate.py            # 运行全部检查
    python scripts/ci_static_gate.py --skip-import   # 跳过导入巡检（更快）
"""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pyflakes.api
import pyflakes.reporter

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Windows 控制台/重定向默认 GBK：本脚本面向人读、汇报含 emoji，直接打印会
# UnicodeEncodeError 崩在第一行（门禁完全跑不起来）。把标准输出重配为 UTF-8，
# 不可编码字符替换而非抛错——报告可读性与跨平台可跑性都要。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 语法 / 未定义名称检查覆盖的目录
CHECK_DIRS = ["neurova", "scripts"]

# 已知"可选重依赖"：缺失时代码会优雅降级，不算代码缺陷。
# 与 neurova/cognitive_layers/memory_layer/__init__.py 的 try/except 降级保持一致。
# 这些依赖在代码中均为"函数内/try 包裹"的惰性导入，或用 try/except 降级，
# 因此在精简 CI 环境（requirements-ci.txt）中缺席时，导入巡检记为 OPTIONAL-SKIP。
KNOWN_OPTIONAL_DEPS = {
    # 科学计算 / 向量 / NeRF
    "numpy",
    "torch",
    "onnxruntime",
    "faiss",
    "chromadb",
    # ASR / TTS / 音频
    "funasr",
    "whisper",
    "soundfile",
    "librosa",
    "sentencepiece",
    "edge_tts",
    "huggingface_hub",
    # Embedding / NLP（会连带 torch，体积大）
    "sentence_transformers",
    "transformers",
    "tokenizers",
    # Computer Use（视觉 / 桌面控制 / 浏览器自动化）
    "PIL",
    "cv2",
    "pyautogui",
    "playwright",
}

# 导入巡检时排除的模块路径片段（run-on-import 独立脚本，导入会触发副作用）
IMPORT_EXCLUDE_SUBSTRINGS = (
    ".scripts.",  # neurova.memory.scripts.* 为一次性脚本，导入即执行
)


def _utf8ChildEnv():
    """子进程写侧钉 utf-8——父端按 utf-8 解、子端按 cp936 写就是半修（§6-225 那族）。

    本仓根路径含中文，子件把带路径的日志写到 stderr 时按 `locale.getpreferredencoding()`
    （开发机 cp936）编码，父端再按 utf-8 解就成了 U+FFFD 替换字符：读数为真、内容为假。
    """
    import os

    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _hr(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def check_syntax() -> bool:
    """检查 1：语法错误（compileall）。返回 True 表示通过。"""
    _hr("✅ 检查 1/3：语法检查（compileall）")
    targets = [str(PROJECT_ROOT / d) for d in CHECK_DIRS if (PROJECT_ROOT / d).exists()]
    cmd = [sys.executable, "-m", "compileall", "-q", *targets]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   env=_utf8ChildEnv())
    if result.returncode == 0:
        print(f"通过：{', '.join(CHECK_DIRS)} 无语法错误")
        return True
    print("❌ 发现语法错误：")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return False


def _importedNamesIn(tree) -> set:
    """本文件里以任何方式被 import 过的名字（含函数体内的局部导入）。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names.add(alias.asname)
                else:
                    names.add(alias.name.split(".")[0])
    return names


def collectUndefinedNames(source: str, filename: str) -> list:
    """pyflakes 的 `undefined name` 读数，剔除「注解专用」形状，返回 `[(行, 列, 名字)]`。

    判据仍是 pyflakes 自己的：本函数不另写 AST 名解析，只做**复核**（教义第 6 条）。
    被剔除的只有一种：该名字在**本文件**里被 import 过（模块级、`TYPE_CHECKING` 块内、
    或函数体内的局部导入），因而「按解析器可读、按求值未绑定」。

    为什么这是修在闸门侧而不是修在被报的代码：`from __future__ import annotations`
    下注解不求值（PEP 563）；而局部导入的存在理由就是断循环导入（AGENTS.md §3）。
    把这类导入提到模块级会改坏生产，删掉注解会丢掉解析器能读的事实——两条都是把报错
    挪走（教义第 1、2 条）。闸门问错的问句，改闸门。真·未定义（拼错的名字、写错的形参）
    不在此列：那些名字在本文件里从来没有被 import 过，一条都跑不掉。
    """
    reporter_out, reporter_err = io.StringIO(), io.StringIO()
    pyflakes.api.check(source, filename, pyflakes.reporter.Reporter(reporter_out, reporter_err))
    text = (reporter_out.getvalue() or "") + (reporter_err.getvalue() or "")
    if not text.strip():
        return []

    try:
        imported = _importedNamesIn(ast.parse(source, filename=filename))
    except SyntaxError:
        imported = set()

    readings = []
    for line in text.splitlines():
        match = _PYFLAKES_LINE.match(line)
        if not match:
            continue
        name = match.group("detail").split(" ", 2)[2].strip("'\"")
        if name in imported:
            continue
        readings.append((int(match.group("row")), int(match.group("col")), name))
    return readings


#: pyflakes Reporter 输出的一行：`<file>:<行>:<列>: <消息>`。只取 `undefined name 'x'`
#: 那一族——语法错、重复定义等不归本闸门管（`reject_duplicate*` 那几类没有这个前缀）。
_PYFLAKES_LINE = re.compile(
    r"^(?P<file>.+?):(?P<row>\d+):(?P<col>\d+): (?P<detail>undefined name '.+'|undefined name \".+\")$"
)


def scanUndefinedNamesUnder(path: str) -> list:
    """遍历目录取未定义名读数，返回便于人读的行（`文件:行:列: undefined name 'x'`）。"""
    readings = []
    for py_file in sorted(Path(path).rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for row, col, name in collectUndefinedNames(source, str(py_file)):
            readings.append(f"{py_file}:{row}:{col}: undefined name '{name}'")
    return readings


def check_pyflakes() -> bool:
    """检查 2：未定义名称（pyflakes 'undefined name'）。返回 True 表示通过。"""
    _hr("✅ 检查 2/3：未定义名称检查（pyflakes）")
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        print("❌ 未安装 pyflakes，请先执行：pip install pyflakes")
        return False

    undefined = scanUndefinedNamesUnder(str(PROJECT_ROOT / "neurova"))
    if not undefined:
        print("通过：neurova/ 无 'undefined name'")
        return True
    print(f"❌ 发现 {len(undefined)} 处未定义名称：")
    for line in undefined:
        print("  " + line)
    return False


def _iter_module_names():
    """遍历 neurova 包，产出所有可导入的模块点分名（含包本身）。"""
    pkg_root = PROJECT_ROOT / "neurova"
    seen = set()
    for py_file in pkg_root.rglob("*.py"):
        rel = py_file.relative_to(PROJECT_ROOT)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        name = ".".join(parts)
        if any(sub in ("." + name + ".") or ("." + name).endswith(sub.rstrip(".")) for sub in IMPORT_EXCLUDE_SUBSTRINGS):
            continue
        if any(sub.strip(".") in parts for sub in IMPORT_EXCLUDE_SUBSTRINGS):
            continue
        if name not in seen:
            seen.add(name)
            yield name


def check_imports() -> tuple[bool, int, int, list[str]]:
    """检查 3：全模块导入巡检。

    返回 (是否通过, 巡检模块数, 可选跳过数, 失败模块列表)。
    """
    _hr("✅ 检查 3/3：全模块导入巡检")
    # 确保项目根在 sys.path，便于以顶层包方式导入 neurova
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    modules = sorted(_iter_module_names())
    failed: list[str] = []
    optional_skipped = 0
    sink = io.StringIO()

    for mod in modules:
        try:
            with redirect_stdout(sink), redirect_stderr(sink):
                importlib.import_module(mod)
        except ImportError as exc:
            # ImportError 族含 from-import 形态（"from X import Y" 失败时 exc.name 指向 X），
            # 仅捕获 ModuleNotFoundError 会漏掉可选包的该形态，误报为失败
            missing = (exc.name or "").split(".")[0]
            if missing in KNOWN_OPTIONAL_DEPS:
                optional_skipped += 1
            else:
                failed.append(f"{mod}  (ImportError: {exc.name})")
        except BaseException as exc:  # noqa: BLE001 - 巡检需捕获一切导入期异常
            failed.append(f"{mod}  ({type(exc).__name__}: {exc})")

    print(f"巡检模块数：{len(modules)}")
    print(f"可选依赖跳过（优雅降级）：{optional_skipped}")
    if failed:
        print(f"❌ 导入失败 {len(failed)} 个：")
        for item in failed:
            print("  " + item)
        return False, len(modules), optional_skipped, failed
    print("通过：无代码缺陷导致的导入失败")
    return True, len(modules), optional_skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Neurova CI 静态门禁")
    parser.add_argument("--skip-import", action="store_true", help="跳过全模块导入巡检")
    args = parser.parse_args()

    print("🚀 Neurova CI 静态门禁")
    print(f"📁 项目根目录：{PROJECT_ROOT}")
    print(f"🐍 Python：{sys.version.split()[0]}")

    results = {}
    results["syntax"] = check_syntax()
    results["pyflakes"] = check_pyflakes()

    if args.skip_import:
        print("\n⏭️  已跳过全模块导入巡检（--skip-import）")
        results["imports"] = True
    else:
        ok, total, skipped, failed = check_imports()
        results["imports"] = ok

    _hr("📊 静态门禁汇总")
    labels = {"syntax": "语法检查", "pyflakes": "未定义名称", "imports": "模块导入巡检"}
    all_pass = True
    for key, ok in results.items():
        mark = "✅" if ok else "❌"
        print(f"{mark} {labels.get(key, key)}：{'通过' if ok else '失败'}")
        all_pass = all_pass and ok

    if all_pass:
        print("\n🎉 静态门禁全部通过")
        return 0
    print("\n💥 静态门禁未通过，请修复上述问题")
    return 1


if __name__ == "__main__":
    sys.exit(main())
