# -*- coding: utf-8 -*-
"""live-verify（Issue #290 未闭环项④）：种子记忆库**整对**搬迁的真链路自证。

## 为什么不以单测全绿代替

单测可以在"只搬主库"的旧实现下全绿 —— 因为断言看的是**文件在不在**，
而主库搬到了、看着就是搬完了。本脚本走真装配：用真 `MemoryManager` 在旧锚点
写存量，换锚后经 `seedDbPath()` 取落点、再开真 `MemoryManager` 读，
**以用户能读到几条记忆**为判据（判据咬的是结果，不是文件数）。

## 判据

1. 旧锚点的存量（主库 + 持久库）整对搬到新落点，旧锚点不再残留这两份；
2. 经真 `MemoryManager` 读到的记忆条数 == 旧锚点写入的条数（改前是 0）；
3. 配对推导与写入端实际用的路径逐字一致（单一事实源，防第二份定义复活）。

## 隔离

数据根走唯一注入口 `NEUROVA_DATA_DIR`；旧锚点落在伪仓库根下
（`data_root.repoRoot` 换成临时目录）—— 全程不碰本机真实 `data/` 与
`neurova/memory/data/`。

跑法：`python tests/manual/seed_memory_pair_relocation_290.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaSeedPair290")

from neurova.core import data_root  # noqa: E402
from neurova.cognitive_layers.memory_layer.manager import MemoryManager  # noqa: E402
from neurova.cognitive_layers.memory_layer.persist_landing import (  # noqa: E402
    PERSIST_COMPANION_NAME,
    persistCompanionPath,
)
from neurova.memory.scripts import seed_db_landing  # noqa: E402

SEED_CONTENTS = ("种子记忆·甲", "种子记忆·乙", "种子记忆·丙")


def main() -> int:
    legacy_root = WORK_ROOT / "repo"
    legacy_dir = legacy_root / "neurova" / "memory" / "data"
    legacy_dir.mkdir(parents=True)
    target_root = WORK_ROOT / "dataRoot"

    data_root.repoRoot = lambda: legacy_root  # 伪仓库根：旧锚点落这里
    import os

    os.environ["NEUROVA_DATA_DIR"] = str(target_root)

    legacy_main = legacy_dir / seed_db_landing.SEED_DB_NAME
    writer = MemoryManager(db_path=str(legacy_main))
    for text in SEED_CONTENTS:
        writer.remember(content=text, category="profile", type="long_term")
    writer.close()

    legacy_pair = sorted(p.name for p in legacy_dir.iterdir() if p.suffix == ".db")
    print(f"[1] 旧锚点存量：{legacy_pair}")

    resolved = seed_db_landing.seedDbPath()
    companion = persistCompanionPath(resolved)
    print(f"[2] 新落点主库：{resolved.exists()} ｜ 配对持久库：{companion.exists()}")

    reader = MemoryManager(db_path=str(resolved))
    try:
        loaded = len(reader._memories)
    finally:
        reader.close()
    print(f"[3] 真 MemoryManager 读到的记忆条数：{loaded}（期望 {len(SEED_CONTENTS)}）")

    residual = sorted(p.name for p in legacy_dir.iterdir() if p.suffix == ".db")
    print(f"[4] 旧锚点残留：{residual}")

    pairing_ok = Path(writer_persist_probe(resolved)) == companion
    print(f"[5] 配对推导与写入端一致：{pairing_ok}")

    ok = (
        companion.exists()
        and loaded == len(SEED_CONTENTS)
        and not residual
        and pairing_ok
    )
    print("LIVE-VERIFY PASSED / Issue #290 未闭环项④" if ok else "LIVE-VERIFY FAILED")
    return 0 if ok else 1


def writer_persist_probe(main_db: Path) -> str:
    """用真写入端（构造 MemoryManager）问出它实际用的持久库落点。"""
    manager = MemoryManager(db_path=str(main_db))
    try:
        return str(manager._persist_db_path)
    finally:
        manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
