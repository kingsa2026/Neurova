# -*- coding: utf-8 -*-
"""手工 live-verify 脚本的数据根隔离单点（Issue #90 环境实测收尾）。

## 为什么收这一处

生产侧的数据根自 2026-09-22 起由 `neurova/core/data_root.py` **单点推导**且
**绝对锚定**：`NEUROVA_DATA_DIR` 是唯一注入口（`DATA_ROOT_ENV`），注入相对路径
当场失败，未注入才落仓库 `data/`。

在那之前，`tests/manual/` 下的脚本靠 `os.chdir(临时目录)` 做隔离。绝对锚定之后
`chdir` **不再改变落点** —— 于是它们全部泄进仓库根 `data/`。环境实测（2026-09-26）
读数：36 份脚本里 **18 份** 把生产库写进了仓库 `data/`，而每份的 docstring 都写着
「写盘全在系统临时目录（不碰 data 生产库）」。**文档承诺与实测行为相反，CI 看不见**
（这些脚本手工跑、不进 CI）。

剩下的 12 份各写了一份 `os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(...))`
—— 同一件事被手抄十余份，正是本仓反复收口的形态（教义第 6 条）。本模块是那份
隔离动作的**唯一落点**：脚本不再自己拼数据根，也就不可能再拼错。

## 用法

在**导入任何 `neurova.*` 生产模块之前**调用（`get_data_root()` 是调用时解析，
但编排器/池的构造期会立刻取它，故必须在构造之前）：

    from tests.manual._liveVerifyIsolation import isolatedDataRoot
    isolatedDataRoot()                       # 一次性：数据根 + agent 工作区根 一起隔到临时根

按规模/形状分目录时用显式落点（**只**动数据根；那种场合还要隔工作区根就显式调
`isolatedAgentWorkspaces()`，它本身也是幂等的）：

    root = useDataRoot(os.path.join(workdir, f"scale_{rows}"))

需要与生产**同一份**落点推导演算时，取 `dataPath()`（生产模块自身），
不要在脚本里另拼一层：

    from neurova.core.data_root import dataPath
    dbPath = useDataPath("context_ledger", f"{agentId}.db")
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: 唯一注入口名（与 `neurova.core.data_root.DATA_ROOT_ENV` 同值）。
#: 这里**不 import 生产模块**：本模块要在生产模块被导入之前生效，提前
#: import `neurova.core.data_root` 会把数据根解析链拉起来（虽为调用时解析，
#: 但保持"零生产依赖"让本模块可以被任何脚本无副作用地最先导入）。
DATA_ROOT_ENV = "NEUROVA_DATA_DIR"


def isolatedDataRoot(prefix: str = "neurovaLive") -> Path:
    """把**数据根与 agent 工作区根一起**指到临时目录，返回数据根。

    为什么是"两根一起"：记忆正文落在工作区那一根下（`<workspace>/<agent>/memory/`），
    它**不在数据根管辖内**。此前只隔数据根的活体会把记忆写进仓内真 `agent_workspaces/`
    （实测：`POST /api/v1/agents` 那一路在仓根新建了两个 workspace 目录，台账 §6-308 的 D8）。
    同一件事散在 145 个调用点上"各人记得调第二个函数"就是第二个事实源的形态（教义 第 6 条），
    所以这条保证收进单点：调用方一行不改就两根都隔。
    只想要显式数据根落点（跨进程按规模分目录）时用 `useDataRoot()`——它**只**动数据根，
    那种场合若还要隔工作区根，显式调 `isolatedAgentWorkspaces()`。

    幂等：任一env 已注入过就沿用，不覆盖 —— 跨进程断言
    （如「重启后同库能否召回」）依赖父子进程指向**同一个**落点（env 由父进程传给子进程）。
    """
    isolatedAgentWorkspaces(prefix=prefix)
    injected = (os.environ.get(DATA_ROOT_ENV) or "").strip()
    if injected:
        return Path(injected)
    return useDataRoot(tempfile.mkdtemp(prefix=f"{prefix}-"))


#: agent 工作区根的注入口（与 `neurova/core/agent_workspaces.py` 的 `AGENT_WORKSPACES_ENV` 同值）。
#: 记忆正文落在这**另一根**下（`<workspace>/<agent>/memory/`），不在数据根管辖内——
#: 所以 `isolatedDataRoot()` 把它一起隔掉（此前"只隔数据根就把记忆写进仓内真 `agent_workspaces/`"
#: 是本仓实测踩过的坑，台账 §6-308 的 D8）。
AGENT_WORKSPACES_ENV = "NEUROVA_AGENT_WORKSPACES_DIR"


def isolatedAgentWorkspaces(prefix: str = "neurovaLive") -> Path:
    """把 agent 工作区根指到临时目录并返回它。

    走 `isolatedDataRoot()` 的活体**不必再调这一条**——那里已把两根一起隔了（D8 收口）。
    这一条留给两种场合：只显式钉数据根落点（`useDataRoot()`）却仍要隔工作区根的活体，
    以及单独复核这一根的判据（`tests/unit/ci/test_liveIsolationSinglePointCoversBothRoots.py`）。
    幂等同 `isolatedDataRoot`：已注入就沿用，父子进程共读同一份落点
    才断言得动（如「重启后同库能否召回」）。
    """
    injected = (os.environ.get(AGENT_WORKSPACES_ENV) or "").strip()
    if injected:
        return Path(injected)
    target = Path(tempfile.mkdtemp(prefix=f"{prefix}-ws-"))
    os.environ[AGENT_WORKSPACES_ENV] = str(target)
    return target


def useDataRoot(path: str | os.PathLike[str]) -> Path:
    """把数据根**显式**指到 `path`（保证绝对路径，目录建好）。"""
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ[DATA_ROOT_ENV] = str(root)
    return root


def dataPathUnder(*parts: str) -> str:
    """当前数据根下的路径 —— 直接转发生产单点，脚本不另拼一份。

    未注入时按生产口径落仓库 `data/`，与 `core/data_root.dataPath` 逐字同源。
    """
    from neurova.core.data_root import dataPath

    return dataPath(*parts)
