"""D19 死岛退役守卫（§6-371）：四旋钮＋A1／A2 一次退净。

用户 2026-10-21 对三组各裁甲：
- 四旋钮（A3–A6）连同同族下游 `channels/temporal.py`、`channels/conflict.py`、
  `channels/moe_router.py`；
- A1 `causal_reasoning.py`（反向关系写侧从未建过，接线是新产品工作）；
- A2 `question_decomposer.py`（主干有活替代，独有子能力属产品口径）。

五格：
1. 九个文件不在场且不在跟踪态；
2. 全仓没有导入通道（相对形/父包取名形，走共享取数口）；
3. 两处门面不再导出退役名字；
4. **正控**：活脊柱仍在（ChannelRegistry／builtin channels／expert MoE router／单源冲突判据）；
5. 检索脊柱权威档不再把四旋钮列成"未接线"。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

RETIRED = {
    "neurova/cognitive_layers/memory_layer/causal_reasoning.py":
        "neurova.cognitive_layers.memory_layer.causal_reasoning",
    "neurova/cognitive_layers/memory_layer/question_decomposer.py":
        "neurova.cognitive_layers.memory_layer.question_decomposer",
    "neurova/cognitive_layers/memory_layer/channels/threshold.py":
        "neurova.cognitive_layers.memory_layer.channels.threshold",
    "neurova/cognitive_layers/memory_layer/channels/weight.py":
        "neurova.cognitive_layers.memory_layer.channels.weight",
    "neurova/cognitive_layers/memory_layer/channels/centroid.py":
        "neurova.cognitive_layers.memory_layer.channels.centroid",
    "neurova/cognitive_layers/memory_layer/channels/processor.py":
        "neurova.cognitive_layers.memory_layer.channels.processor",
    "neurova/cognitive_layers/memory_layer/channels/temporal.py":
        "neurova.cognitive_layers.memory_layer.channels.temporal",
    "neurova/cognitive_layers/memory_layer/channels/conflict.py":
        "neurova.cognitive_layers.memory_layer.channels.conflict",
    "neurova/cognitive_layers/memory_layer/channels/moe_router.py":
        "neurova.cognitive_layers.memory_layer.channels.moe_router",
}

RETIRED_EXPORTS = {
    "memory_layer": (
        "CausalReasoningEngine", "get_causal_reasoning_engine",
        "QuestionDecomposer", "QuestionType", "get_question_decomposer",
    ),
    "channels": (
        "CentroidInitializer", "ConflictDetector", "ConflictPair",
        "UnifiedResultProcessor", "TemporalDecay", "ThresholdConfig", "WeightAdjuster",
    ),
}

SPINE_DOC = "docs/01-architecture/memory/retrieval-spine.md"


def test_retiredFilesAreGone():
    still = [rel for rel in RETIRED if (REPO_ROOT / rel).is_file()]
    assert not still, f"退役文件仍在磁盘上：{still}"
    tracked = ast_scan.trackedPaths("neurova/cognitive_layers")
    stillTracked = [rel for rel in RETIRED if rel in tracked]
    assert not stillTracked, f"退役文件仍在 git 跟踪态里：{stillTracked}"


def test_noImporterRemains():
    hits = []
    for rel, dotted in RETIRED.items():
        for importer, lineno, form in ast_scan.importersOfModule(REPO_ROOT, dotted):
            hits.append(f"{importer}:{lineno} → {dotted}（{form}）")
    assert not hits, f"退役后仍有人导入它们：{hits[:8]}"


def test_facadesNoLongerExportTheRetiredNames():
    import neurova.cognitive_layers.memory_layer as memory_layer
    import neurova.cognitive_layers.memory_layer.channels as channels

    for owner, names in (("memory_layer", RETIRED_EXPORTS["memory_layer"]),
                         ("channels", RETIRED_EXPORTS["channels"])):
        module = memory_layer if owner == "memory_layer" else channels
        still = [name for name in names if hasattr(module, name)]
        assert not still, f"{owner} 门面仍在导出退役名字：{still}"


def test_liveSpineStillImports():
    """正控：删的是死岛，不是活脊柱。"""
    from neurova.cognitive_layers.memory_layer.channels import (
        BaseChannel, ChannelRegistry, ChannelResult, get_channel_registry,
    )
    from neurova.cognitive_layers.memory_layer.channels.builtin import BUILTIN_CHANNELS
    from neurova.cognitive_layers.memory_layer.conflict import judgeClauseConflict
    from neurova.cognitive_layers.memory_layer.moe_router import (
        MoEMemoryRouter, VectorGatingNetwork,
    )
    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

    assert BaseChannel and ChannelRegistry and ChannelResult and get_channel_registry
    assert BUILTIN_CHANNELS, "builtin 通道注册表空了——删错了活脊柱"
    assert MoEMemoryRouter and VectorGatingNetwork
    assert NeurovaRecallEngine
    hit = judgeClauseConflict("我喜欢咖啡", "我不喜欢咖啡")
    assert hit is not None and hit[0] == "negation_conflict", (
        "记忆侧单源冲突判据被本批带走了")


def test_spineDocNoLongerListsTheKnobsAsUnwired():
    text = (REPO_ROOT / SPINE_DOC).read_text(encoding="utf-8")
    still = [rel for rel in RETIRED if rel in text]
    assert not still, (
        f"[权威] 检索脊柱档仍在指向已退役文件：{still}——改写成退役记录，别留悬空路径")
    assert "已退役" in text or "退净" in text, (
        "检索脊柱档没有记录四旋钮的退役，读者会把它当未接线的待办")


def test_scanFaceIsNotVacuous():
    """面自证：退役判据的扫描面要能看到整个认知层（根被改窄会变成"零命中"）。"""
    files = ast_scan.filesUnder(REPO_ROOT / "neurova" / "cognitive_layers")
    assert len(files) > 50, f"扫描面只看到 {len(files)} 个文件，判据的根可能被改窄了"
