"""A2 `question_decomposer` 退役守卫（§6-379）。

用户 2026-10-21 指令完成余下组。主干替代已在役：
`QueryIntentDetector`（意图分类/权重）、`chat_pipeline._decompose_query`（LLM 拆解）、
`IntentAwareRecallStrategy.get_channel_weights`（加权参数）。
显式放弃：`PROCEDURAL` 分类、三段定式模板、`diversity/serendipity` 两个旋钮。
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE = "neurova.cognitive_layers.memory_layer.question_decomposer"
PATH = "neurova/cognitive_layers/memory_layer/question_decomposer.py"


def test_moduleIsGone():
    import importlib.util

    assert not (REPO_ROOT / PATH).is_file(), f"{PATH} 仍在磁盘上"
    assert importlib.util.find_spec(MODULE) is None


def test_noImporterRemains():
    from tests import ast_scan

    # 面自证（形态 404）：这条判据的"零 importer"要与"没扫到"可区分——枚举面先量一次。
    # 现算全仓 5660 个 .py；根少指一层会掉到 tests 2483／neurova 1024，都低于这条线。
    pairs = list(ast_scan.nodeScan(REPO_ROOT, ".py"))
    scanned = len(pairs)
    assert scanned >= 3000, (
        "枚举面现读 %d 个 .py——REPO_ROOT 指错时『零 importer』与『没扫到』长得一样" % scanned)
    importers = ast_scan.importersOfModule(REPO_ROOT, MODULE)
    assert not importers, f"已退役模块仍被导入：{importers}"


def test_facadeNoLongerExports():
    import neurova.cognitive_layers.memory_layer as memory_layer

    leaked = [name for name in ("QuestionDecomposer", "QuestionType",
                                "get_question_decomposer")
              if hasattr(memory_layer, name)]
    assert not leaked, f"memory_layer 门面仍在导出：{leaked}"


def test_liveAlternativesRemain():
    from neurova.cognitive_layers.memory_layer.neurova_recall import (
        IntentAwareRecallStrategy,
        QueryIntentDetector,
    )

    assert hasattr(IntentAwareRecallStrategy, "get_channel_weights")
    assert hasattr(QueryIntentDetector, "detect_intent")
