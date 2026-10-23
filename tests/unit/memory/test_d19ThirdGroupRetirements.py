"""D19 剩余组退役守卫（§6-378）：通道插件未接旋钮与同族下游。

用户 2026-10-21 指令完成余下组。这六档的生产读者只有门面与已死的 `processor`
（`channels/moe_router` 连门面都没有）：
- `threshold`/`centroid`/`weight`：per-channel 阈值、通道质心、反馈权重三件；
  反馈权重已由 `IntentAwareRecallStrategy.applyFeedback` 接管（§6-377），
  阈值覆盖/通道质心显式放弃（无消费者，活实现保留全局阈值与 expert 质心）。
- `processor`/`temporal`：去重/加权/衰减已由 live 的 `_deduplicate_results`/
  `_fusion_score`/`_recency_score` 承担；内联冲突检测判据已并入 `judgeClauseConflict`
  （§6-374），`activations` 乘子无生产者，显式放弃。
- `channels/moe_router`：按查询做通道门控；live 走“意图权重 × 全启用通道”，
  expert MoE 仍是 `memory_layer/moe_router.py`，本档显式放弃。
"""
import importlib.util

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

RETIRED = {
    "threshold": "neurova/cognitive_layers/memory_layer/channels/threshold.py",
    "centroid": "neurova/cognitive_layers/memory_layer/channels/centroid.py",
    "weight": "neurova/cognitive_layers/memory_layer/channels/weight.py",
    "processor": "neurova/cognitive_layers/memory_layer/channels/processor.py",
    "temporal": "neurova/cognitive_layers/memory_layer/channels/temporal.py",
    "moe_router": "neurova/cognitive_layers/memory_layer/channels/moe_router.py",
}

FACADE_NAMES = (
    "ThresholdConfig",
    "CentroidInitializer",
    "WeightAdjuster",
    "UnifiedResultProcessor",
    "TemporalDecay",
)


def test_retiredModulesAreGone():
    for name, rel in RETIRED.items():
        assert not (REPO_ROOT / rel).is_file(), f"{rel} 仍在磁盘上——退役没有落地"
        assert importlib.util.find_spec(
            f"neurova.cognitive_layers.memory_layer.channels.{name}") is None


def test_noImporterRemains():
    from tests import ast_scan

    # 面自证：本格断的是「零导入」，而零导入既可能是「真没人导入」也可能是「根写窄了扫了个空」。
    scanned = len(ast_scan.filesUnder(REPO_ROOT, ".py"))
    assert scanned > 2000, f"仓内 .py 扫描面现读 {scanned}，低于下限＝根写错了本格恒绿"

    offenders = {}
    scanned = len(ast_scan.filesUnder(REPO_ROOT))
    # 面自证：先证扫描面非空，再谈「零导入」（根被改窄时零命中与干净同形）。
    assert scanned > 500, f"扫描面现读 {scanned} 个文件——REPO_ROOT 指错时本判据恒绿"
    for name in RETIRED:
        hits = ast_scan.importersOfModule(
            REPO_ROOT, f"neurova.cognitive_layers.memory_layer.channels.{name}")
        if hits:
            offenders[name] = hits[:3]
    assert not offenders, f"退役后仍有人导入：{offenders}"


def test_facadeNoLongerExportsRetiredNames():
    import neurova.cognitive_layers.memory_layer.channels as channels

    leaked = [name for name in FACADE_NAMES if hasattr(channels, name)]
    assert not leaked, f"channels 门面仍在导出已退役实现：{leaked}"


def test_liveAlternativesRemain():
    """正控：删的是未接旋钮，不是能力——活实现必须还在。"""
    from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
    from neurova.cognitive_layers.memory_layer.moe_router import VectorGatingNetwork
    from neurova.cognitive_layers.memory_layer.neurova_recall import (
        IntentAwareRecallStrategy,
        NeurovaRecallEngine,
    )
    from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

    assert MemoryStorage is not None
    assert UnifiedVectorStore is not None
    assert VectorGatingNetwork is not None
    for name in ("_recency_score", "_deduplicate_results", "_fusion_score"):
        assert hasattr(NeurovaRecallEngine, name), f"live 召回缺少 {name}"
    assert hasattr(IntentAwareRecallStrategy, "applyFeedback")
