# -*- coding: utf-8 -*-
"""原创性措辞守卫（AGENTS.md §2 红线；审计 3.2-14，2026-11-17）：

生产代码注释/文档字符串不得引用、对齐任何第三方项目（"对照/对齐/参考 XX
项目"类措辞）。全部产出基于本项目独立设计与实现；外部依赖只作为功能依赖
登记，不引入其设计标准。

白名单＝已登记的移交项（域外文件，R3 会话文件域不含）：
- models/computer.py：`ZCODE` 是集成后端的功能性枚举值（ACP bridge 接入
  标识，如同 openai/anthropic），不是设计对齐引用；其行内注释措辞随移交批裁定；
- security/command_syntax.py、telemetry/__init__.py、workflow/scripted/__init__.py：
  同款"对照 ZCode"注释，文件域外，移交下一批清偿。白名单只许缩小不许扩大。
"""

from __future__ import annotations

from pathlib import Path

import pytest

NEUROVA_ROOT = Path(__file__).resolve().parents[3] / "neurova"

# 第三方项目名（大小写不敏感；命中即违规，白名单文件除外）
_THIRD_PARTY_NAMES = ("zcode",)

# 已登记移交项：白名单只许缩小（清偿后从名单删除），不许新增
_HANDOVER_ALLOWLIST = {
    "models/computer.py",
    "security/command_syntax.py",
    "telemetry/__init__.py",
    "workflow/scripted/__init__.py",
}


def _violations() -> list[str]:
    out = []
    for py in sorted(NEUROVA_ROOT.rglob("*.py")):
        rel = py.relative_to(NEUROVA_ROOT).as_posix()
        if rel in _HANDOVER_ALLOWLIST:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        for name in _THIRD_PARTY_NAMES:
            if name in lowered:
                out.append(f"{rel}: 含第三方项目引用 {name!r}（AGENTS.md §2 原创性红线）")
                break
    return out


def test_production_code_has_no_third_party_references():
    violations = _violations()
    assert not violations, "生产代码含第三方项目引用：\n  " + "\n  ".join(violations)


def test_handover_allowlist_only_shrinks():
    """白名单条目必须仍存在且仍含命中——清偿后要从名单删除，不许留空座。"""
    stale = []
    for rel in sorted(_HANDOVER_ALLOWLIST):
        py = NEUROVA_ROOT / rel
        if not py.is_file():
            stale.append(f"{rel}: 文件已不存在，白名单条目未跟（应删除）")
            continue
        text = py.read_text(encoding="utf-8", errors="ignore").lower()
        if not any(name in text for name in _THIRD_PARTY_NAMES):
            stale.append(f"{rel}: 命中已清偿，白名单条目未删（应缩小名单）")
    assert not stale, "移交白名单未收口：\n  " + "\n  ".join(stale)


def test_guard_detects_a_planted_reference():
    """反向对照：守卫对植入的引用必须报警（守卫自身在位性）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        planted = Path(td) / "sample.py"
        planted.write_text("# 对照 ZCode 的做法\n", encoding="utf-8")
        saved_root = _violations.__globals__["NEUROVA_ROOT"]
        try:
            _violations.__globals__["NEUROVA_ROOT"] = Path(td)
            assert _violations(), "守卫对植入引用不报警——它已经坏了"
        finally:
            _violations.__globals__["NEUROVA_ROOT"] = saved_root


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
