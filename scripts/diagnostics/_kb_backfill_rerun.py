"""重放历史回填到生产底座库（诊断脚本，非套件件）。

咽喉口径一变（015 装配单源 / 019b-1 记录种类 / 019b-2 内容键立身），`facts.db` 就停在
旧形状上，后面每次读数都在跟它对不上——所以提供一条可重放的归正通道。

只读 knowledge.json：用 SimpleNamespace 顶替仓库，绝不构造生产 `KnowledgeRepository`
（它 `_rebuild_indexes` 会顺手 `_save` 真库）。写只落在 facts 库与 id_map；
旧件按时间戳改名留档，可回退。用法：
    python scripts/diagnostics/_kb_backfill_rerun.py
"""

import datetime
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROD = ROOT / "data" / "knowledge"
DB = PROD / "knowledge_facts.db"
IDMAP = PROD / "knowledge_backfill_id_map.json"
SOURCE = PROD / "knowledge.json"

os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ.pop("PYTEST_VERSION", None)

from neurova.knowledge.foundation.backfill import LegacyFactBackfill  # noqa: E402
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore  # noqa: E402

stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
if DB.exists():
    shutil.move(str(DB), str(DB) + ".pre-" + stamp)
    for extra in ("-wal", "-shm"):
        if Path(str(DB) + extra).exists():
            shutil.move(str(DB) + extra, str(DB) + extra + ".pre-" + stamp)
if IDMAP.exists():
    shutil.move(str(IDMAP), str(IDMAP) + ".pre-" + stamp)

raw = json.loads(SOURCE.read_text(encoding="utf-8"))
repo = SimpleNamespace(_items=raw)
store = KnowledgeFactStore(str(DB))
report = LegacyFactBackfill.run(repo, store)
readings = {
    "facts": store.factCount(),
    "subjects": store.subjectCount(),
    "pending_conflicts": store.pendingConflictCount(),
    "assertions": store._conn.execute("SELECT COUNT(*) FROM knowledge_assertions").fetchone()[0],
    "activities": store._conn.execute("SELECT COUNT(*) FROM knowledge_activities").fetchone()[0],
}
store.close()

summary = {k: v for k, v in report.items() if k != "id_map"}
IDMAP.write_text(json.dumps(report["id_map"], ensure_ascii=False, indent=2), encoding="utf-8")
print("BACKFILL %s" % summary)
print("READINGS %s" % readings)
print("id_map entries: %d" % len(report["id_map"]))
