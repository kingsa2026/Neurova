"""agent 记忆落点 `<root>/memory/memory.db` 只许有一处拼法（§6-210 登记的老账①，本批收掉）。

现量形状（两处逐字同形，仅 root 来源不同）：
- `neurova/agent_core.py:285-288` 从**注入的** `self.workspace_path` 拼；
- `neurova/cognitive_layers/memory_layer/manager.py:_default_db_path_for` 从
  `get_agent_workspace_dir(agent_id)` **推导的** root 拼。

今天两边算出的字符串相同，所以没人疼；但"改一处即分叉"是台账记下的原话——落点一分叉就是
数据搬迁事故（正文库与情绪/附件表从此各归各家）。两个 root 来源都得留着（注入的那个是权威），
所以收口的形态不是"删掉一处"，而是把**布局那一段**收成一份函数，两边各自喂自己的 root。

判据一头钉形状（AST 里那条 divide 链只许出现在单源函数体内），一头钉行为
（`_default_db_path_for` 给出的路径逐字不变——收口不许顺手改落点）。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import neurova
from neurova.core import agent_workspaces

NEUROVA_DIR = Path(neurova.__file__).resolve().parent
REPO = Path(neurova.__file__).resolve().parents[1]
LEAF = "memory.db"
SEGMENT = "memory"


def _divideChains(tree: ast.AST):
    """产出每个「除法链」的顶层节点与其全部字符串常量（`a / "b" / "c"` 是一条链，不是两条）。"""
    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if isinstance(node.left, ast.BinOp):
                nested.add(id(node.left))
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and id(node) not in nested:
            consts = {n.value for n in ast.walk(node)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            yield node, consts


def _spellingsInCode(code: str) -> list:
    """返回该源码里"拼出这条落点"的行号；没拼就回空。

    判据按**文件级常量并集**取，不按单条链取：`agent_core.py` 是 `dir = root / "memory"` 先落
    一个变量、下一行再 `dir / "memory.db"`——单条链里两个字面量从不齐，按链数会把它漏成"干净"
    （本档第一版就是这么假干净的：只数到 manager 那一处）。文件级取 `and`、行号级取 `or`，
    两种写法都认，同时不牵连那些只出现 `"memory"` 一段的别的目录。
    """
    tree = ast.parse(code)
    chains = list(_divideChains(tree))
    allConsts: set = set()
    for _node, consts in chains:
        allConsts |= consts
    if SEGMENT not in allConsts or LEAF not in allConsts:
        return []
    return sorted({node.lineno for node, consts in chains
                   if SEGMENT in consts or LEAF in consts})


def _offenders() -> dict:
    """仍在这条落点上拼字面量的文件清单。

    取数走 `tests/ast_scan.sourceRefsUnder` 的共享预算＋文本预筛，不私有 `rglob + ast.parse`
    ——扫描预算守卫 `test_ci_ast_scan_budget_guard` 判红的正是那形，而本格登记进受保护子集的
    **当天**就被它点名（判据成本绑在代码总量上，30s 默认墙钟下整目录跑会偶发）。
    预筛词取 `memory.db`：无论拆成几条除法链，真拼这条落点的文件必然出现这三个字 ⇒
    这是判据的**充分条件**，不是放宽。
    """
    out = {}
    for ref in ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", (LEAF,)):
        lines = _spellingsInCode(ref.code)
        if lines:
            out[ref.path.relative_to(REPO).as_posix()] = lines
    return out


def testTheMemoryLandingIsSpelledInExactlyOneFile():
    """全仓有几个文件在这条落点上拼过字面量——只许单源那一个。"""
    hits = _offenders()
    assert list(hits) == ["neurova/core/agent_workspaces.py"], (
        "落点拼法散在 %d 个文件：%s ⇒ 改一处即分叉（§6-210 老账①）" % (len(hits), hits)
    )


def testAgentCoreTakesTheSharedDerivation():
    """`agent_core` 那处必须改成调用单源函数——只删掉本地拼法而没接线，就是又造一条瞎腿。"""
    src = NEUROVA_DIR / "agent_core.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "get_agent_memory_db_path" in called, (
        "agent_core 没走单源推导（现有调用名=%s）" % sorted(c for c in called if "emory" in c)
    )


def testDefaultDbPathStillPointsWhereItDid():
    """反向钉：收口只许改"谁来拼"，不许改"拼出什么"。

    落点变了就是数据搬迁事故——情绪表与附件目录都还按这条路径认地方。
    """
    from neurova.cognitive_layers.memory_layer.manager import _default_db_path_for

    derived = _default_db_path_for("probe-agent")
    expected = agent_workspaces.get_agent_memory_db_path("probe-agent")
    assert Path(derived) == expected, (
        "默认落点与单源推导不一致（实得 %s ↔ 期望 %s）" % (derived, expected)
    )
    assert derived.replace("\\", "/").endswith("/probe-agent/memory/memory.db"), (
        "默认落点的形状变了（实得 %s）⇒ 本批动了数据位置，不只是动了拼法" % derived
    )
