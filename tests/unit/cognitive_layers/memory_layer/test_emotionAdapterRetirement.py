"""`emotion_adapter.py` 退役守卫（§6-368）。

依据 `audit-reports/cognitive-layer-zero-reader-dossier-2026-10-20.md` Z5：该档是 8 个方法的
纯转发门面，目标 `memory_layer/emotion.py` 的 `EmotionAnalyzer` 活着且在 api 与 tool_executor
两侧被直连；适配器净增能力为零，唯一"独有"的是 `_analyze_legacy` 玩具分支与一个
ImportError 恒返 neutral 的假成功兜底（教义第 2 条点名的形态）。判定＝删。

四格：
1. 文件不在场（且不在跟踪态）；
2. 全仓没有任何导入通道再取它（含相对形与父包取名形，走共享取数口）；
3. **正控**：转发目标仍在、且八个方法一个不少——防"删对了文件、删错了能力"；
4. 活跃层文档不再声称它在役（历史层 04-plans／11-legacy 允许保留旧引用）。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

ADAPTER = "neurova/cognitive_layers/memory_layer/emotion_adapter.py"
MODULE = "neurova.cognitive_layers.memory_layer.emotion_adapter"

#: 活跃层里点过名的两份；历史层（04-plans／11-legacy）不动——它们是当时的事件
ACTIVE_DOCS = (
    "docs/01-architecture/15-emotion-resonance-engine.md",
    "docs/README.md",
)

#: 适配器原样转发的八个方法（名字取自退役前的公开面；少一个就说明删错了目标）
FORWARDED = (
    "analyze", "batch_analyze", "get_emotion_tags", "get_emotion_score",
    "get_detailed_scores", "get_emotion_hierarchy", "get_emotion_stats",
    "get_emotion_distribution",
)


def test_adapterFileIsGone():
    assert not (REPO_ROOT / ADAPTER).is_file(), (
        f"{ADAPTER} 仍在磁盘上——退役没有落地")
    assert ADAPTER not in ast_scan.trackedPaths("neurova/cognitive_layers"), (
        f"{ADAPTER} 仍在 git 跟踪态里")


def test_noImporterRemains():
    hits = ast_scan.importersOfModule(REPO_ROOT, MODULE)
    assert not hits, f"退役后仍有人导入它：{hits[:5]}"


def test_liveAnalyzerStillExposesTheForwardedSurface():
    """正控：删的是适配器，不是能力。转发目标必须还在、八方法齐全。"""
    from neurova.cognitive_layers.memory_layer.emotion import EmotionAnalyzer
    missing = [name for name in FORWARDED if not hasattr(EmotionAnalyzer, name)]
    assert not missing, (
        f"EmotionAnalyzer 少了方法 {missing}——刚退役的适配器曾是它们唯一的转发入口，"
        "先确认是删错了能力还是目标本身也变了")


def test_activeDocsNoLongerClaimTheAdapter():
    offenders = []
    for rel in ACTIVE_DOCS:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        #: 路径形与类名形都算"指向它"——只查路径时 README 那种写类名的段落会漏网
        if "emotion_adapter" in text or "EmotionAnalyzerAdapter" in text:
            offenders.append(rel)
    assert not offenders, (
        f"活跃层文档仍在指向已退役的适配器：{offenders}——改成 EmotionAnalyzer 的落点，"
        "历史引用留在 04-plans／11-legacy")
