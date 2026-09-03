"""
test_no_bare_except.py — P0-11: 回归测试，确保 neurova/ 内无裸 except:

裸 except: 会捕获 KeyboardInterrupt/SystemExit/GeneratorExit，导致 Ctrl+C 失效。
此测试用 ast 扫描所有 .py 文件，验证 except handler 类型不为空。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

NEUROVA_ROOT = pathlib.Path(__file__).resolve().parents[3] / "neurova"


def _find_bare_except(filepath: pathlib.Path) -> list[int]:
    """返回文件中裸 except: 所在行号列表"""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    bare_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            bare_lines.append(node.lineno)
    return bare_lines


def _collect_bare_except_files() -> list[tuple[str, int]]:
    """收集 neurova/ 下所有裸 except: 的 (文件名, 行号)"""
    results = []
    for py_file in NEUROVA_ROOT.rglob("*.py"):
        for line_no in _find_bare_except(py_file):
            results.append((str(py_file.relative_to(NEUROVA_ROOT)), line_no))
    return results


class TestNoBareExcept:
    """P0-11 回归: neurova/ 内不应存在裸 except:"""

    def test_no_bare_except_in_neurova(self):
        bare_locations = _collect_bare_except_files()
        if bare_locations:
            formatted = "\n".join(f"  {f}:{l}" for f, l in bare_locations)
            pytest.fail(f"发现 {len(bare_locations)} 处裸 except::\n{formatted}")
