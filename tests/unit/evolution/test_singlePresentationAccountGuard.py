"""呈现账单源守卫（§8 前置 3 · Task 5）。

钉的是**代码形态**，不是文档措辞：呈现这一格在仓内只允许有一处定义与一条
写入路。排除自身按**路径相等**，不按文件名片段过滤——按片段过滤会连带吞掉
同词干的其他测试文件，制造伪"零命中"（本仓实测踩过的取证坑）。
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRODUCTION_ROOT = _REPO_ROOT / "neurova"
_SELF = Path(__file__).resolve()


def _hitsFor(root: Path, needle: str):
    """root 树下所有 .py 里含 needle 的路径（相对 root）。"""
    return [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if needle in path.read_text(encoding="utf-8", errors="replace")
    ]


def testTimesPresentedRetiredFromProductionCode():
    assert _hitsFor(_PRODUCTION_ROOT, "times_presented") == [], (
        "呈现账出现第二份定义或退役不净"
    )


def testFunnelLedgerIsTheOnlyPresentationSource():
    """呈现的唯一写入口是 recordTurnSkillPresentation，唯一生产调用方是目录渲染挂接。"""
    injection = (_PRODUCTION_ROOT / "skills" / "skill_injection.py").read_text(
        encoding="utf-8", errors="replace"
    )
    orchestrator = (_PRODUCTION_ROOT / "context" / "orchestrator.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "on_present" in injection
    assert "recordTurnSkillPresentation" in orchestrator


def testPresentationWriterHasExactlyOneProductionCaller():
    """生产面写入点数死为 1（context/orchestrator），账本载体自身除外。

    第二处写入点即双源复发——呈现计数只能有一个来源，否则一轮记两遍。
    """
    callers = [
        rel for rel in _hitsFor(_PRODUCTION_ROOT, "recordTurnSkillPresentation(")
        if rel != str(Path("core") / "turn_context.py")
    ]
    assert callers == [str(Path("context") / "orchestrator.py")], callers


def testRetirementScanBites(tmp_path):
    """反证守卫自证咬得住：造一个坑状态让它红，再演一遍还原即绿。

    坑落在 tmp，不写进 neurova/——并发会话的全仓 AST/尺寸扫描会看见仓库内
    临时件，把"证明守卫有效"变成给别人造一条假红。
    """
    fakeRoot = tmp_path / "neurova"
    (fakeRoot / "pkg").mkdir(parents=True)
    pit = fakeRoot / "pkg" / "revived.py"
    pit.write_text('PROBE = {"times_presented": 0}\n', encoding="utf-8")
    assert _hitsFor(fakeRoot, "times_presented") == [
        str(Path("pkg") / "revived.py")
    ]
    pit.unlink()
    assert _hitsFor(fakeRoot, "times_presented") == []
