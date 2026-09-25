"""重放历史回填到生产底座库（诊断脚本，非套件件）。

咽喉口径一变（015 装配单源 / 019b-1 记录种类 / 019b-2 内容键立身），治理行就停在
旧形状上，后面每次读数都在跟它对不上——所以提供一条可重放的归正通道。

019b-4b 之后条目权威也在同一个 DB 文件里（`knowledge_narratives`），所以"整库改名
重建"会连权威一起搬走。改成就地清治理面五张表、只留叙述面三张表，旧库先复制留档。

只读条目、写只落在治理表与 id_map。用法：
    python scripts/diagnostics/_kb_backfill_rerun.py
"""

import datetime
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PROD = ROOT / "data" / "knowledge"
DB = PROD / "knowledge_facts.db"
IDMAP = PROD / "knowledge_backfill_id_map.json"

# 治理面：admit 重放会逐行重建；叙述面（knowledge_narratives / knowledge_tombstones /
# knowledge_entry_conflicts）是条目权威与用户可见台账，重放不许碰。
FACT_SIDE_TABLES = ("knowledge_facts", "knowledge_subjects", "knowledge_assertions",
                    "knowledge_activities", "knowledge_conflicts")

os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ.pop("PYTEST_VERSION", None)

from neurova.knowledge.foundation.backfill import LegacyFactBackfill  # noqa: E402
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore  # noqa: E402
from neurova.knowledge.foundation.narratives import NarrativeStore  # noqa: E402

if not DB.exists():
    raise SystemExit("底座库不存在：%s——没有可重放的权威，先让应用层建库" % DB)

stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup = Path(str(DB) + ".pre-" + stamp)
shutil.copy2(str(DB), str(backup))
if IDMAP.exists():
    shutil.copy2(str(IDMAP), str(IDMAP) + ".pre-" + stamp)

itemsByAgent = NarrativeStore(str(DB)).loadAll()
conn = sqlite3.connect(str(DB))
for table in FACT_SIDE_TABLES:
    conn.execute("DELETE FROM %s" % table)
conn.commit()
conn.close()

store = KnowledgeFactStore(str(DB))
report = LegacyFactBackfill.run(SimpleNamespace(_items=itemsByAgent), store)
readings = {
    "facts": store.factCount(),
    "subjects": store.subjectCount(),
    "pending_conflicts": store.pendingConflictCount(),
    "assertions": store._conn.execute("SELECT COUNT(*) FROM knowledge_assertions").fetchone()[0],
    "activities": store._conn.execute("SELECT COUNT(*) FROM knowledge_activities").fetchone()[0],
    "narratives": store._conn.execute("SELECT COUNT(*) FROM knowledge_narratives").fetchone()[0],
}
store.close()

summary = {k: v for k, v in report.items() if k != "id_map"}
IDMAP.write_text(json.dumps(report["id_map"], ensure_ascii=False, indent=2), encoding="utf-8")
print("BACKUP %s" % backup)
print("BACKFILL %s" % summary)
print("READINGS %s" % readings)
print("id_map entries: %d" % len(report["id_map"]))
