"""第二环 `agent_self` / `memory_stream` 退役守卫（§6-380）。

两档生产读者为 0：
- `AgentSelfManager` 的核心指令/心跳任务从无实例化；Agent 生命周期与主动行为另有实装。
- `MemoryStream` 的事件流/订阅从无生产读者；进程内事件面由 `core.event_bus` 承担。
显式放弃：可持久化的核心指令表/心跳任务表、独立记忆事件流与导出格式。
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RETIRED = {
    "agent_self": "neurova/cognitive_layers/memory_layer/agent_self.py",
    "memory_stream": "neurova/cognitive_layers/memory_layer/memory_stream.py",
}


def test_modulesAreGone():
    import importlib.util

    for name, rel in RETIRED.items():
        assert not (REPO_ROOT / rel).is_file(), f"{rel} 仍在磁盘上"
        assert importlib.util.find_spec(
            f"neurova.cognitive_layers.memory_layer.{name}") is None


def test_noImporterRemains():
    from tests import ast_scan

    # 面自证：下面每个"零导入"都建立在"真的扫过子树"之上。根指错或扫面被改窄时，
    # 零 offender 与干净同形（面自证棘轮点名的正是这一形）。取跟踪清单而不是遍历，
    # 与 `importersOfModule` 同一取法、且不受未跟踪件影响。
    scanned = ast_scan.trackedPyPaths()
    assert len(scanned) > 500, (
        f"扫描面现读 {len(scanned)} 个 .py——根指错时『零导入』不代表干净"
    )
    offenders = {}
    # 面自证：语料按根量一次，根被改窄时下面会读成「零导入」而不是红
    # （该形态由 `tests/unit/ci/test_scanCriterionMustProveItsOwnSurfaceRatchet.py` 点名）。
    corpus = len(ast_scan.filesUnder(REPO_ROOT, ".py"))
    assert corpus > 500, (
        f"语料现读 {corpus} 个文件（根＝{REPO_ROOT}）——面量级不对＝根指错，"
        "「零导入」不来自代码")
    for name in RETIRED:
        hits = ast_scan.importersOfModule(
            REPO_ROOT, f"neurova.cognitive_layers.memory_layer.{name}")
        # 只认跟踪源（neurova/ 与 tests/）；NeurUI 下的 Tauri 打包副本被 .gitignore 忽略，
        # 是构建产物，不是可导入的本仓源码。
        hits = [hit for hit in hits if hit[0].startswith(("neurova/", "tests/"))]
        if hits:
            offenders[name] = hits[:3]
    # 面自证：退役名清单被清空时下面那句"零导入"与真干净同形
    assert len(RETIRED) >= 1, f"退役名清单现读 {len(RETIRED)} 条——面被清空时零导入不代表干净"
    assert not offenders, f"退役后仍有人导入：{offenders}"


def test_facadeNoLongerExports():
    import neurova.memory as memory_facade

    leaked = [name for name in ("AgentSelfManager", "MemoryStream")
              if hasattr(memory_facade, name)]
    assert not leaked, f"neurova.memory 仍在导出：{leaked}"


def test_liveEventAndAgentSurfacesRemain():
    from neurova.core.event_bus import EventBus
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    assert EventBus is not None
    assert hasattr(MemoryManager, "remember")
