"""认知引擎用例的共用装配点——正文库只有一处落点，构造必须连着 `MemoryManager` 一起给。

各档原先各自写 `CognitiveStorageEngine(agent_id=..., data_dir=str(tmp_path))`；那个
`data_dir` 正是第二个 `memories` 落点的入口，收口后引擎不再持有自己的库，构造它就得
先有正文库。逐档手抄这两行等于留下几十份可各自漂移的装配，故收在此处
（同仓先例：`tests/auth_headers.py`）。

用法：
    from tests.cognitive_body_store import bodyManager, cognitiveEngine

    manager = bodyManager(tmp_path)                 # 需要断言正文行时用这一份
    engine = cognitiveEngine(tmp_path, manager=manager)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
from neurova.cognitive_layers.memory_layer.manager import MemoryManager


def bodyManager(
    tmpPath: Path,
    agentId: str = "test",
    neuserId: str = "default",
    userId: str = "default",
) -> MemoryManager:
    """在 `tmpPath` 下建一份真 `MemoryManager`（正文库落它同目录的配对文件）。"""
    return MemoryManager(
        db_path=str(Path(tmpPath) / "memory.db"),
        agent_id=agentId,
        neuser_id=neuserId,
        user_id=userId,
        enable_buffer=False,
    )


def cognitiveEngine(
    tmpPath: Path,
    agentId: str = "test",
    manager: Optional[MemoryManager] = None,
) -> CognitiveStorageEngine:
    """按正文库装配认知引擎；不传 manager 就现建一份（断言行落点时必须传）。"""
    return CognitiveStorageEngine(
        agent_id=agentId, memory_manager=manager or bodyManager(tmpPath, agentId)
    )
