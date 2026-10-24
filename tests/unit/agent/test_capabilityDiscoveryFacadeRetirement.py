# -*- coding: utf-8 -*-
"""批 109·第④刀（改判后的可执行半）：`protocols` 门面不再把能力发现那座死岛挂在启动路径上。

取证口径（本会话现量，全部按路径与符号取数，不抄台账旧行号）：

- `neurova/agent/protocols/capability_discovery.py`（449）与其唯一消费者
  `neurova/agent/matrix/agent_matrix.py`（561）**在生产侧零消费者**：共享取数口
  `importersOfModule` 对前者只报出 `agent_matrix.py` 与门面自身两处，对后者只报出它自己包的门面；
  `neurova.agent.matrix` 这个名字在全仓没有任何外部 import。
- 这条岛**曾被接进活链路后被摘**（不是引入即未接线）：`2482c042`(06-03) 那份 970 行的
  `collaboration_api.py` 里有 19 条路由，其中 8 条是 `/capabilities*`／`/recommend`／`/matrix*`／
  `/templates/preset`，`POST /capabilities/register` 就是注册表的唯一生产者；次日 `7835c367`
  把该文件重写成 154 行／6 条路由，端点整批消失，生产侧再无人喂、再无人读。
  ⇒ 本体删不删归台账 B3 那张需人裁票（它与 matrix 必须同批裁），**本刀一律不碰**。
- 本刀只解决门面这一条（与 §6-312 的 D19 同根因）：`protocols/__init__.py` 在模块级无条件
  `from .capability_discovery import ...` 并把三个名字写进 `__all__`，而 `agent/team.py:23` 与
  `acp_api.py` 都是 `from neurova.agent.protocols.<子模块> import ...`——Python 导入子包必先执行
  父包 `__init__`，于是**只取活的消息协议也会执行这 449 行死码的模块体**，还向下一个人暗示
  "能力发现在这里有现役实现"。

本格钉四件事：
① 正控——活的那条链（消息协议／死信队列）仍能从门面取到，收口不许关掉活面；
② 行为——干净子进程里只 import 活的 `acp_runtime` 时，`capability_discovery` 不得进 `sys.modules`；
③ 边界——两档岛本体仍须在树里（它们等的是 B3 那次裁，不是本刀顺手删）；
④ 面自证——探针与扫描器这两条腿都能产生非零读数，否则"零"分不开"没跑成"（形态集 283）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import ast_scan  # 导入通道判据的共享取数口（四形都认，含相对形与父包取名形）

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 门面不再声明的三个名＝那座岛的唯一导出面（按名判 safe：全仓只有这一处定义）。
DEAD_FACADE_NAMES = ("CapabilityDiscovery", "AgentCapability", "CapabilityMatch")

#: 岛本体＝本刀的边界对象。按**模块路径**判，不按符号名。
ISLAND_MODULES = (
    "neurova.agent.protocols.capability_discovery",
    "neurova.agent.matrix.agent_matrix",
)

#: 活面＝现役消费方真从门面/子模块取的那些名字（`team.py`、`acp_api.py`）。
LIVE_FACADE_SYMBOLS = (
    "AgentMessage",
    "MessagePriority",
    "MessageType",
    "DeadLetterQueue",
    "DLQConfig",
)

_PROBE = (
    "import sys, json\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import neurova.agent.protocols.acp_runtime\n"
    "print(json.dumps(sorted(m for m in sys.modules\n"
    "      if m.startswith('neurova.agent.protocols') or m.startswith('neurova.agent.matrix'))))\n"
)

#: 子进程预算唯一出处（§6-402 批 K 口径：父墙由它 ＋余量导出，两处不许各写一个数）。
#: 120s 是给**失败那一路**留的：判据要防的正是"门面把整座岛重新拖上启动路径"，那种时候
#: 子进程真会去 import 协议族＋矩阵一大片模块；而 120s 子墙配缺省 30s 父墙时，先到点的
#: 是父墙——Windows 侧 thread 法终止整个进程，得到的是一条"整场跑测没了"而不是这条断言。
ISLAND_PROBE_WALL_S = 120
pytestmark = pytest.mark.timeout(ISLAND_PROBE_WALL_S + 60)


def _loadedProtocolModules():
    """在**干净子进程**里只 import 活的 `acp_runtime`，交出落进 `sys.modules` 的协议族模块名。

    必须起子进程：本跑测进程早已 import 过整座岛，在进程内量 `sys.modules` 恒真。
    两侧编码一起钉（形态集 248：只钉父端会读到 mojibake）。
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(PROJECT_ROOT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(PROJECT_ROOT), timeout=ISLAND_PROBE_WALL_S,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    tail = (proc.stdout or "").strip().splitlines()
    assert tail, (
        "探针没交出读数（退码 %s，stderr 前 200 字：%s）——「死岛不在 sys.modules」这个零"
        "必须由一趟真跑起来的扫描给出，不能由一次没跑成冒充" % (proc.returncode, (proc.stderr or "")[:200])
    )
    loaded = json.loads(tail[-1])
    assert isinstance(loaded, list) and loaded, (
        "探针读数解析成空集，说明那条 import 腿没产生任何模块——本格就成了恒真空守卫"
    )
    return loaded


class TestCapabilityDiscoveryFacadeRetirement:
    def test_liveFacadeSymbolsStillReachable(self):
        """正控：门面收口后，活的那条链必须照样从门面取得到（收口不许把活面一起关掉）。"""
        import neurova.agent.protocols as protocols

        missing = [name for name in LIVE_FACADE_SYMBOLS if not hasattr(protocols, name)]
        assert not missing, (
            "门面不再导出现役符号：%s（`team.py`／`acp_api.py` 就从这条路取消息协议与死信队列）"
            % ", ".join(missing))

    def test_probeFaceIsNotVacuous(self):
        """面自证：探针这一趟至少要把**活的**协议族模块报进读数——否则它没跑到那一步。"""
        loaded = _loadedProtocolModules()
        for leg in ("neurova.agent.protocols.acp_runtime", "neurova.agent.protocols.dead_letter_queue"):
            assert leg in loaded, (
                "探针没量到 %s（读数=%s）＝这条腿不产生非零，后面那句「死岛缺席」不作数" % (leg, loaded))

    def test_deadIslandNotDraggedOntoStartupPath(self):
        """只 import 活的 acp_runtime 时，能力发现那座岛不得进 `sys.modules`。"""
        loaded = set(_loadedProtocolModules())
        dragged = sorted(mod for mod in ISLAND_MODULES if mod in loaded)
        assert not dragged, (
            "包门面把死岛挂在每次进程启动路径上（§6-312 D19 同根因）：只取活的消息协议却执行了 "
            "%s 的模块体。门面只该再导出现役符号。" % ", ".join(dragged))

    def test_facadeDoesNotDeclareTheDeadIsland(self):
        """行为面：三个名字既不在 `__all__`，也不再挂在门面属性上（"声明了却没人取"同样算谎）。"""
        import neurova.agent.protocols as protocols

        declared = [name for name in DEAD_FACADE_NAMES if name in set(protocols.__all__)]
        assert not declared, "门面仍把零消费者的死岛声明成公共面：%s" % ", ".join(declared)
        attached = [name for name in DEAD_FACADE_NAMES if hasattr(protocols, name)]
        assert not attached, (
            "门面仍能取到 %s——`__all__` 摘了却没摘 module-level import，启动成本一分没省"
            % ", ".join(attached))

    def test_islandBodiesAreNotDeletedByThisKnife(self):
        """边界反证：本刀只动门面，两档岛本体必须仍在树里。

        这条不是形式主义。那座岛**曾被接进活链路后被摘**（`7835c367` 一刀砍掉 8 条路由），
        按死码溯源的口径它只能"恢复接线"或"显式承认放弃该能力"，二者都归台账 B3 那次人裁；
        把它当"实现还在、只是没人调"顺手删掉，就是替产品关掉一项能力。这一格钉住本刀的边界。
        """
        missing = []
        for rel in ("neurova/agent/protocols/capability_discovery.py", "neurova/agent/matrix/agent_matrix.py"):
            if not (PROJECT_ROOT / rel).is_file():
                missing.append(rel)
        assert not missing, (
            "以下岛本体已不在树里，但 B3 那张需人裁票还没拍：%s——门面收口不等于批准退役本体"
            % ", ".join(missing))

    def test_noConsumerOutsideTheIsland(self):
        """死岛的外部引用面必须收在岛内：除 matrix 自己那条腿，生产侧不得再有人 import 它。

        下限同时钉住：`agent_matrix.py` 这一处必须还在（它就是 B3 要裁的那个唯一消费者），
        读数掉成 0 意味着扫描面被改窄，而不是引用被清干净。
        """
        offenders = []
        for mod in ISLAND_MODULES:
            for path, lineno, kind in ast_scan.importersOfModule(PROJECT_ROOT / "neurova", mod):
                if "neurova/agent/matrix/" in path or "neurova/agent/protocols/" in path:
                    continue
                offenders.append("%s ← %s:%s（取法 %s）" % (mod, path, lineno, kind))
        assert not offenders, (
            "岛外还有人 import 这座死岛（本刀收口的门面漏了腿，或有人新接了一条）：\n  "
            + "\n  ".join(offenders))

    def test_importScannerFaceIsNotNarrowed(self):
        """面自证：同一个取数口对**岛内那条活腿**必须报出引用——否则上一格的"岛外零命中"是假绿。

        根被改窄、路径写错、`importersOfModule` 被换实现，三种坏法都只让 offender 读数变 0。
        """
        live = ast_scan.importersOfModule(PROJECT_ROOT / "neurova",
                                          "neurova.agent.protocols.capability_discovery")
        assert len(live) >= 1, (
            "取数口对 capability_discovery 只报 %d 处（应至少含 agent_matrix.py 那条相对导入腿）——"
            "扫描面自己坏了，此时『岛外零引用』不作数" % len(live))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
