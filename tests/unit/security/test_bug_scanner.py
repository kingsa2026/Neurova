"""
测试：bug_scanner — 静态代码 BUG 扫描器

测试 BugScanner 的 AST 分析和内容模式匹配功能。
所有测试在临时目录中创建临时 Python 文件进行扫描。
"""

import pytest

try:
    from neurova.bug_scanner import BugScanner, generate_markdown_report
    _HAS_BUG_SCANNER = True
except (ImportError, ModuleNotFoundError):
    _HAS_BUG_SCANNER = False

pytestmark = pytest.mark.skipif(not _HAS_BUG_SCANNER, reason="neurova.bug_scanner module not found")
