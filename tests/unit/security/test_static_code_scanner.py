"""
static_code_scanner.py 单元测试
覆盖: Severity/IssueType枚举, Issue数据类, CodeScanner(AST分析),
SecurityPatterns(安全模式扫描), DeadCodeScanner(死代码检测),
以及 scan_file/should_exclude/collect_python_files/format_report/generate_json_report
"""
import pytest

try:
    from neurova.static_code_scanner import (
        Severity,
        IssueType,
        Issue,
        CodeScanner,
        SecurityPatterns,
        DeadCodeScanner,
        scan_file,
        should_exclude,
        collect_python_files,
        format_report,
        generate_json_report,
    )
    _HAS_STATIC_SCANNER = True
except (ImportError, ModuleNotFoundError):
    _HAS_STATIC_SCANNER = False

pytestmark = pytest.mark.skipif(not _HAS_STATIC_SCANNER, reason="neurova.static_code_scanner module not found")
