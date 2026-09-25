"""杂项 · `scripts/diagnostics/` 下的脚本必须在 INDEX 里登记。

`scripts/diagnostics/INDEX.md` 自称「本索引随脚本增删维护；新增临时脚本时请同步更新本文件」，
而两个诊断脚本（`skill_name_collisions.py`、`muscle_memory_rearchive.py`）连同本批新增的
两个（`_tool_experience_loop_probe.py`、`muscle_memory_threshold_attainability.py`）
在索引里**零命中**——自助发现入口断了，等于这些脚本只有作者知道。

同时钉住两处容易反复退化的地方：
- 受保护测试清单不得有重复行（曾把 `test_rsi_rollback_evidence.py` 登记两次）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSTICS = REPO_ROOT / "scripts" / "diagnostics"
INDEX = DIAGNOSTICS / "INDEX.md"
PROTECTED = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"

# INDEX 的说明性文件与包初始化文件不是"脚本"，不要求登记。
_NON_SCRIPT = {"INDEX.md", "__init__.py"}


def test_every_diagnostic_script_is_indexed():
    text = INDEX.read_text(encoding="utf-8")
    missing = sorted(
        path.name for path in DIAGNOSTICS.glob("*.py")
        if path.name not in _NON_SCRIPT and path.name not in text
    )
    assert missing == [], f"诊断脚本没登记进 INDEX.md（自助发现入口断了）：{missing}"


def test_index_does_not_list_removed_scripts():
    """本目录章节里登记的脚本必须真的还在。

    第四节刻意列举**根目录**脚本（运维/入口类，非临时诊断），它们不属于本目录，
    且不同检出里未必都在，故只检查本目录章节。
    """
    text = INDEX.read_text(encoding="utf-8")
    in_directory_sections = text.split("## 四")[0]
    existing = {path.name for path in DIAGNOSTICS.glob("*.py")}
    stale = [
        name for name in _indexed_script_names(in_directory_sections)
        if name not in existing and name != "__init__.py"
    ]
    assert stale == [], f"INDEX 里登记了已不存在的脚本：{stale}"


def _indexed_script_names(text: str):
    import re

    return set(re.findall(r"`([A-Za-z0-9_]+\.py)`", text))


def test_protected_tests_has_no_duplicate_rows():
    entries = [
        line.strip() for line in PROTECTED.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    duplicates = sorted({entry for entry in entries if entries.count(entry) > 1})
    assert duplicates == [], f"受保护测试清单里有重复登记行：{duplicates}"
