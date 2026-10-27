# -*- coding: utf-8 -*-
r"""活体隔离单点必须一次隔干净两根（D8＝台账 §6-308 顺带抓到、§6-309 登记的待办）。

实状（本轮现读，不抄旧票）：`tests/manual/` 里**起了真 app 的脚本 84 档**，其中调单点
`isolatedDataRoot()` 的 **80 档**，而同时把 agent 工作区根也隔了的只有 **10 档**
⇒ **70 档在"数据根已隔离、工作区根仍指仓内真 `agent_workspaces/`"的状态下起真 app**。
记忆正文落在**另一根**下（`<workspace>/<agent>/memory/`），`isolatedDataRoot()` 管不到它——
`_liveVerifyIsolation.py:64-67` 那段注释写的正是这个坑，§6-308 的 D8 就是它当场咬出来的实测
（`POST /api/v1/agents` 那一路在仓根新建了两个 workspace 目录）。

为什么"靠写探针的人记得调第二个函数"是坏形态：同一件事被 145 档调用点各自决定要不要做，
就是本仓反复收口的"手抄一份"形状（教义第 6 条）。该由**单点保证**的，不该散在调用方。

判据五格，缺一格就是没咬住：

① 行为主格：干净进程里只调 `isolatedDataRoot()` ⇒ `get_agent_workspaces_root()` 不得落在仓内。
   **必须在子进程测**：`tests/conftest.py:58/:228` 已把两个 env 注进跑测进程，而在进程内调单点，
   幂等分支会"沿用已注入值"直接返回——判据就恒绿（夹具自造，形态集 242/252 同族）。
② 正控格：同一取法但**不调**单点 ⇒ 必须正是仓内默认 `agent_workspaces`。
   没有这一格，①那条"不等于仓内"的断言可能只是取数坏了（形态集 283：每个零都要先证能产生非零）。
③ 形状格：单点函数体里对工作区根的那次隔离，必须经**它自己的注入口**
   （AST 判 `isolatedDataRoot` 体内有一次对 `isolatedAgentWorkspaces` 的调用）——
   防止有人改成"在这儿再拼一份 `Path(tempfile.mkdtemp())/...`"，那就又是第二份表示。
④ 手抄棘轮：`tests/manual/` 里把 `"NEUROVA_AGENT_WORKSPACES_DIR"` **写进 env** 的档
   （`os.environ[KEY]=…` / `setdefault(KEY, …)` 两种形态，按 AST 判；常量定义、`get`、`pop` 都不算），
   只准是单点自己（按文件名→期望写入次数钉死，双向咬：新增即红，收干净了不摘表也红，同形态集 268）。
   第一版按"字面量出现次数"数，被自家探针的 `pop`/`get` 与单点的常量定义一起自咬——
   按词扫源码的守卫会被正常用法填满，这是本仓第六枚同族命中点。
⑤ 幂等格：两个 env 都已注入时调单点 ⇒ 两根都不许被覆盖。
   这一格钉的是本单点存在的另一个理由：跨进程断言（父子共读同一落点）依赖"已注入就沿用"。
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: 子进程预算唯一出处。探针子进程只 import `neurova.core.agent_workspaces` 取一个路径，
#: 实测单格 0.11s——此前挂着的 300s 是"给足安全感"而非实测需求，而 300s 子墙配全局 30s
#: 父墙时，先到点的是后者＝整场跑测被打死（§6-402 批 K 口径）。收成低于全局墙的 20s，
#: 既留住诚实的 TimeoutExpired，也不用给整档抬父墙。
PROBE_WALL_S = 20
MANUAL_DIR = REPO_ROOT / "tests" / "manual"
SINGLE_POINT = MANUAL_DIR / "_liveVerifyIsolation.py"

DATA_ROOT_ENV = "NEUROVA_DATA_DIR"
AGENT_WORKSPACES_ENV = "NEUROVA_AGENT_WORKSPACES_DIR"

#: ④ 手抄面的唯一合法持有者：v2 单根后不再有任何脚本需要写工作区 env。
WORKSPACE_ENV_HANDCOPY_ALLOWED: dict = {}


def _runInCleanProcess(source: str) -> dict:
    """在**剥掉两个注入口**的子进程里跑一段脚本，取回它打印的 JSON 读数。

    编码两侧都钉：父端 `encoding/errors`，子端 `PYTHONIOENCODING`
    （`test_subprocessTextEncodingRatchet` 那一族的形态要求；只钉一侧是它实测过的两种坏法）。
    """
    env = dict(os.environ)
    for key in (DATA_ROOT_ENV, AGENT_WORKSPACES_ENV):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", source],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PROBE_WALL_S,
    )
    assert proc.returncode == 0, f"子进程没跑成（rc={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}"
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return json.loads(last)


def test_isolatedDataRootAloneMovesAgentWorkspaceOutOfRepo():
    """①主格：只调 `isolatedDataRoot()`，工作区根也必须离开仓内。"""
    reading = _runInCleanProcess(
        "import json, os\n"
        "from tests.manual._liveVerifyIsolation import isolatedDataRoot\n"
        "isolatedDataRoot()\n"
        "from neurova.core.agent_workspaces import get_agent_workspaces_root\n"
        "print(json.dumps({'ws': str(get_agent_workspaces_root()),\n"
        "                  'data': os.environ.get('NEUROVA_DATA_DIR', '')}))"
    )
    repoDefault = REPO_ROOT / "agent_workspaces"
    ws = pathlib.Path(reading["ws"])
    assert reading["data"], "连数据根都没注入——子进程没走到单点，读数不可用"
    assert ws != repoDefault, (
        f"只调 isolatedDataRoot() 时工作区根仍指仓内真目录：{ws}\n"
        "⇒ 70 档起真 app 的 manual 探针会往仓内 agent_workspaces/ 写记忆/附件——"
        "该由单点保证的第二根没人保证（D8）。"
    )
    # 「临时目录」的判据用**生成它的那个入口**：单点是 `tempfile.mkdtemp(prefix="neurovaLive")`
    # ⇒ 系统临时根就是 `tempfile.gettempdir()`。早先这里读的是 `os.environ.get("TEMP", "")`
    # 加 `"Temp" in str(ws)`：POSIX 上没有 TEMP（只有 TMPDIR），取到空串后
    # `Path("").resolve()` 就是**当前工作目录**，仓内落点也过判；后半句更只是大小写巧合。
    # 两层都不咬——所以按"落点在不在系统临时根下"判，并且只认一个根。
    tempRoot = pathlib.Path(tempfile.gettempdir()).resolve()
    assert ws.resolve().is_relative_to(tempRoot), (
        f"工作区根没有落在临时目录：{ws}（临时根＝{tempRoot}）——"
        "与上面那条不同源：上面只要求不在仓内，这条要求它真的落在系统临时根下"
    )


def test_positiveControlWithoutSinglePointLandsInsideRepo():
    """②正控：不调单点时，工作区根**正是**仓内默认——主格那条腿能产生非仓内读数才有效。"""
    reading = _runInCleanProcess(
        "import json\n"
        "from neurova.core.agent_workspaces import get_agent_workspaces_root\n"
        "print(json.dumps({'ws': str(get_agent_workspaces_root())}))"
    )
    assert pathlib.Path(reading["ws"]).resolve() == (REPO_ROOT / "data").resolve(), (
        f"正控落点不是仓内默认：{reading['ws']}——探测器取数口径坏了，①那条红/绿都不可信"
    )


def test_singlePointGuardsWorkspaceRootThroughItsOwnEntry():
    """③形状格：v2 单根后 `isolatedDataRoot()` 不得再隔第二根。"""
    tree = ast.parse(SINGLE_POINT.read_text(encoding="utf-8"))
    fn = next(
        (n for n in tree.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "isolatedDataRoot"),
        None,
    )
    assert fn is not None, "单点里没有 isolatedDataRoot()——取法改了，本档要跟着改判而不是静默绿"
    taken = {
        (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
    }
    assert "isolatedAgentWorkspaces" not in taken, (
        f"isolatedDataRoot() 仍在隔第二根（体内调用={sorted(t for t in taken if t)}）——"
        "v2 布局下工作区已随数据根走，再写工作区 env 会把 agent 数据引到数据根之外"
    )
    assert "useDataRoot" in taken, "isolatedDataRoot() 没经 useDataRoot() 这一唯一注入口"


def _isEnvironValue(node: ast.AST) -> bool:
    """`os.environ`（含 `from os import environ` 后的裸名）。"""
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return isinstance(node.value, ast.Name) and node.value.id == "os"
    return isinstance(node, ast.Name) and node.id == "environ"


def _isTheWorkspaceKey(node: ast.AST) -> bool:
    """这个表达式是不是"那把键"——字面量或单点里那个同名常量。"""
    if isinstance(node, ast.Constant) and node.value == AGENT_WORKSPACES_ENV:
        return True
    return isinstance(node, ast.Name) and node.id == "AGENT_WORKSPACES_ENV"


def _workspaceEnvWriteCount(node: ast.AST) -> int:
    """这个节点是不是"把那把键**写进** env"，返回它贡献的写入次数。

    按**写入形态**判，不按"这个字面量出现过几次"判。第一版就是按词数的，结果被三样东西自咬：
    单点里那句常量定义、探针为了取干净现场而 `pop` 掉这两个键、以及读回包时的 `os.environ.get(KEY)`
    ——它们都不是手抄注入（形态集 268／241 同族：按词扫源码的守卫会被自家正常用法填满）。
    """
    if isinstance(node, ast.Assign):
        return sum(1 for t in node.targets
                   if isinstance(t, ast.Subscript) and _isEnvironValue(t.value)
                   and _isTheWorkspaceKey(t.slice))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"setdefault", "__setitem__"}
            and _isEnvironValue(node.func.value) and node.args
            and _isTheWorkspaceKey(node.args[0])):
        return 1
    return 0


def _workspaceEnvHandCopies() -> dict:
    """`tests/manual/**.py` 里对工作区根 env 的**写入**落点（文件名 → 写入次数）。

    扫描面取工作树（本仓口径：'不许新增'型守卫要当场咬住新写的档，含还没提交的）；
    这正是要的效果——本批我自己新写的那支探针一旦开始手抄这个键，也会被这里点名。

    取数走 `tests/ast_scan` 的**一次性**入口 `transientNodes`（本档只扫一遍 ⇒ 不留常驻语法树），
    不私有 `glob + ast.parse`——§6-313 的 D22 记的就是这类落点（受保护子集里已积到 10 档），
    本批先把自己那两格收干净。
    """
    hits: dict[str, int] = {}
    surface = len(ast_scan.filesUnder(MANUAL_DIR))
    assert surface > 100, f"扫描面现读 {surface} 个 .py（根＝tests/manual/）——根被改窄时「零命中」不代表干净"
    for path, node in ast_scan.transientNodes(
            MANUAL_DIR, ".py", ast_scan.textHints("environ")):
        count = _workspaceEnvWriteCount(node)
        if count:
            hits[path.name] = hits.get(path.name, 0) + count
    return hits


def test_manualScriptsDoNotHandCopyTheWorkspaceEnvKey():
    """④棘轮：手抄面只准留在单点自己那一处，且它真写了才算在册（双向咬合）。"""
    found = _workspaceEnvHandCopies()
    offenders = {k: v for k, v in found.items() if k not in WORKSPACE_ENV_HANDCOPY_ALLOWED}
    assert not offenders, (
        f"这些 manual 脚本还在自己拼工作区根的 env（该由 isolatedDataRoot() 一起保证）：{offenders}"
    )
    for name, expected in WORKSPACE_ENV_HANDCOPY_ALLOWED.items():
        assert found.get(name, 0) == expected, (
            f"{name} 的工作区 env 字面量命中数应为 {expected}，实为 {found.get(name, 0)}"
            "——单点自己不再写这个键，说明注入通道搬家了，本档的口径要跟着重定"
        )


def test_isolatedDataRootIsIdempotentForBothRoots():
    """⑤幂等格：两根都已注入时调单点，一根都不许被覆盖（父子进程共读同一落点靠它）。"""
    reading = _runInCleanProcess(
        "import json, os, tempfile\n"
        "data = tempfile.mkdtemp(prefix='b82-data-')\n"
        "ws = tempfile.mkdtemp(prefix='b82-ws-')\n"
        "os.environ['NEUROVA_DATA_DIR'] = data\n"
        "os.environ['NEUROVA_AGENT_WORKSPACES_DIR'] = ws\n"
        "from tests.manual._liveVerifyIsolation import isolatedDataRoot\n"
        "isolatedDataRoot()\n"
        "print(json.dumps({'data': os.environ['NEUROVA_DATA_DIR'],\n"
        "                  'ws': os.environ['NEUROVA_AGENT_WORKSPACES_DIR']}))"
    )
    assert reading["data"].startswith("b82-data-") or os.sep + "b82-data-" in reading["data"], (
        f"已注入的数据根被单点换掉了：{reading['data']}"
    )
    assert "b82-ws-" in reading["ws"], (
        f"已注入的工作区根被单点换掉了：{reading['ws']}——跨进程断言会拿到两个不同落点"
    )
