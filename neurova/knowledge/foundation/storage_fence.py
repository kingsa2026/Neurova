"""生产知识库目录的测试会话围栏，以及"生产目录是谁"的唯一答案（工单 001 立，019b-4b 收全）。

三件事必须长在同一个地方，所以放在同一个模块里：

1. **唯一路径**：`data/knowledge/` 这个字符串此前抄了四份（条目仓库、事实底座、评测台架、
   向量索引），抄一份就漏一个入口。现在只有 `PRODUCTION_STORAGE_DIR` 一处。
2. **围栏判据**：pytest 会话内，任何存储对象都不许在真实生产目录下建文件或写文件。
   本批真实踩过两类：围栏只守 `KnowledgeRepository` 时，`get_knowledge_fact_store()`
   的默认路径照样把底座库建了出来；摘掉标记的用例指向真目录，当场把生产的
   `knowledge.json` 搬进库并改了名（设计文档 §11.7）。
3. **比较口径**：resolve 之后再比，且**目录本身和目录里的任何文件**都算命中——
   底座库、评测库、向量缓存、条目主文件是同一条链上的四个写入面，漏一个就等于没围栏。

围栏是 pytest-only 的：它挡不住"自己把标记摘了"的用法，所以配套铁律写在
`tests/unit/knowledge/test_default_storage_write_fence.py` 抬头——清标记的用例只准
指向 `tmp_path` 下的假生产目录。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union
from neurova.core.data_root import dataPath

PRODUCTION_STORAGE_DIR = dataPath("knowledge")


def productionStorageDir() -> Path:
    """生产知识库目录（resolve 形态，比较口径用）。"""
    return Path(PRODUCTION_STORAGE_DIR).resolve()


def underProductionStorage(path: Union[str, Path]) -> bool:
    target = Path(str(path)).resolve()
    prod = productionStorageDir()
    return target == prod or prod in target.parents


def assertNotUnderProductionStorage(path: Union[str, Path], what: str) -> None:
    """测试会话内碰到生产目录就当场失败，不给"静默改掉唯一权威"留第二次机会。"""
    if not _inPytestSession():
        return
    if not underProductionStorage(path):
        return
    raise RuntimeError(
        "测试会话禁止读写生产知识库 %s（本次是 %s）；用 tmp_path 建自己的库，"
        "或 monkeypatch 门面 get_repository / get_knowledge_fact_store 注入隔离实例。"
        % (productionStorageDir(), what)
    )


# ── 记忆侧（同一纪律的第二处落地）────────────────────────────────
#
# 知识侧有围栏、记忆侧没有，代价是仓库根那份 71,831 行的
# `neurova_memories_persist.db`（审计 2026-09-21 §7）。判据与知识侧逐字同构：
# 目录本身或目录里的任何文件都算命中，比较前两侧 resolve。


def productionMemoryDir() -> Path:
    """生产记忆目录：**仓库自带的** `agent_workspaces/`。

    刻意不走 `get_agent_workspaces_root()`：那个函数读 `NEUROVA_AGENT_WORKSPACES_DIR`，
    而测试期注入的就是它——拿注入值当生产定义，围栏在测试里会拦下全部隔离目录
    （等于把每条用例都判红），而在真正的生产上又拦不住任何东西。
    生产目录是磁盘上那个事实，不是当前进程的配置。
    """
    return Path(__file__).resolve().parents[3] / "agent_workspaces"


def underProductionMemory(path: Union[str, Path]) -> bool:
    target = Path(str(path)).resolve()
    prod = productionMemoryDir()
    return target == prod or prod in target.parents


def assertNotUnderProductionMemory(path: Union[str, Path], what: str) -> None:
    """与知识侧同纪律、同触发条件：pytest 会话内碰生产记忆目录即当场失败。"""
    if not _inPytestSession():
        return
    if not underProductionMemory(path):
        return
    raise RuntimeError(
        "测试会话禁止读写生产记忆库 %s（本次是 %s）；用 tmp_path 建自己的库，"
        "或经 NEUROVA_AGENT_WORKSPACES_DIR 指到隔离工作区。"
        % (productionMemoryDir(), what)
    )


def _inPytestSession() -> bool:
    """围栏只对测试会话生效——生产与脚本的正常写入不该被它拦住。"""
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION"))
