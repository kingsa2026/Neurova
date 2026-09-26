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
    isolatedDataRoot()                       # 一次性：全新临时根

按规模/形状分目录时用显式落点：

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
    """把数据根指到一个全新临时目录并返回它。

    幂等：调用方（或父进程）已注入过就沿用，不覆盖 —— 跨进程断言
    （如「重启后同库能否召回」）依赖父子进程指向**同一个**根。
    """
    injected = (os.environ.get(DATA_ROOT_ENV) or "").strip()
    if injected:
        return Path(injected)
    return useDataRoot(tempfile.mkdtemp(prefix=f"{prefix}-"))


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
