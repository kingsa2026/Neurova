"""`conflict_detector_v2.py` 退役守卫（§6-370）。

裁定乙：v2 的「同属性异值」判据并进 `conflict.judgeClauseConflict` 后再退役。
四格：
1. 文件不在场且不在跟踪态；
2. 全仓没有导入通道（相对形/父包取名形，走共享取数口）；
3. 包门面与聚合门面不再导出 `ConflictDetector`；
4. 正控：合并后的判据仍在单源里报 `attribute_conflict`——防"删对了文件、删错了能力"。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests import ast_scan  # noqa: E402

RETIRED = "neurova/cognitive_layers/memory_layer/conflict_detector_v2.py"
MODULE = "neurova.cognitive_layers.memory_layer.conflict_detector_v2"


def test_moduleFileIsGone():
    assert not (REPO_ROOT / RETIRED).is_file(), (
        f"{RETIRED} 仍在磁盘上——退役没有落地")
    assert RETIRED not in ast_scan.trackedPaths("neurova/cognitive_layers"), (
        f"{RETIRED} 仍在 git 跟踪态里")


def test_noImporterRemains():
    hits = ast_scan.importersOfModule(REPO_ROOT, MODULE)
    assert not hits, f"退役后仍有人导入它：{hits[:5]}"


def test_facadesNoLongerExportConflictDetector():
    import neurova.cognitive_layers.memory_layer as memory_layer
    import neurova.memory as memory_namespace

    assert not hasattr(memory_layer, "ConflictDetector"), (
        "包门面仍在导出 ConflictDetector——再导出处必须与实现同批退役")
    assert not hasattr(memory_namespace, "ConflictDetector"), (
        "聚合门面仍在导出 ConflictDetector——它此前只指向 v2")


def test_liveCriterionStillCoversTheMergedCapability():
    """正控：删的是 v2 那份实装，不是能力。"""
    from neurova.cognitive_layers.memory_layer.conflict import judgeClauseConflict

    hit = judgeClauseConflict("项目使用 PostgreSQL 数据库", "项目使用 MySQL 数据库")
    assert hit is not None, "同属性异值判据消失了——先确认是删错了能力"
    assert hit[0] == "attribute_conflict"
