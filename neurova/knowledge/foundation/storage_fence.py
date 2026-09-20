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

PRODUCTION_STORAGE_DIR = "./data/knowledge"


def productionStorageDir() -> Path:
    """按当前工作目录解析——与 `PRODUCTION_STORAGE_DIR` 的相对语义一致。"""
    return Path(PRODUCTION_STORAGE_DIR).resolve()


def underProductionStorage(path: Union[str, Path]) -> bool:
    target = Path(str(path)).resolve()
    prod = productionStorageDir()
    return target == prod or prod in target.parents


def assertNotUnderProductionStorage(path: Union[str, Path], what: str) -> None:
    """测试会话内碰到生产目录就当场失败，不给"静默改掉唯一权威"留第二次机会。"""
    if not (os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("PYTEST_VERSION")):
        return
    if not underProductionStorage(path):
        return
    raise RuntimeError(
        "测试会话禁止读写生产知识库 %s（本次是 %s）；用 tmp_path 建自己的库，"
        "或 monkeypatch 门面 get_repository / get_knowledge_fact_store 注入隔离实例。"
        % (productionStorageDir(), what)
    )
