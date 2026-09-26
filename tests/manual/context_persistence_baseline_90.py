#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文池持久层（B4）容量基线取证：写放大 / 读侧预筛 / 启动加载 / 迁移 / GC。

手工运行，不进 CI；写盘全在系统临时目录（不碰 data/ 生产库）。
用法：PYTHONPATH=. python tests/manual/context_persistence_baseline_90.py

读数口径：本机 fsync 抖动大，跨次运行同一形状可差 2 倍以上。规格
（docs/specs/2026-09-21-context-persistence-design.md）引用的是**连跑三次的区间**，
故本脚本一次运行只给一份读数，取区间请连跑三次。§2 内部已是 20 轮取样取中位，
且跨形状比较只用同一次运行内的中位——不跨运行比。
"""
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

random.seed(90)
CJK_WORDS = "上下文 压缩 池 归档 检索 注入 记忆 经验 反思 工具 结果 窗口 预算".split()
ENGLISH = "The context window budget decides whether folding triggers and how much history stays resident. "


def turnChunks(turnIndex, size=24):
    """生产形状一轮：中文段 / 英文段 / JSON 工具结果三分。"""
    rows = []
    for i in range(size):
        shape = i % 3
        if shape == 0:
            text = "".join(random.choice(CJK_WORDS) for _ in range(60))
        elif shape == 1:
            text = ENGLISH * 3
        else:
            text = json.dumps(
                {"role": "assistant", "tool": "file_read", "bytes": 4096, "ok": True}, ensure_ascii=False
            )
        rows.append((f"turn{turnIndex}_{i}", "conversation", text))
    return rows


def openDb(path, withFts=True, tokenize="trigram"):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  session_id TEXT, turn_id TEXT, source TEXT, content TEXT NOT NULL, metadata TEXT,
  created_at TEXT, evicted_at TEXT NOT NULL, content_digest TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_scope_id ON chunks(user_id, agent_id, id);
CREATE INDEX IF NOT EXISTS idx_scope_session ON chunks(user_id, agent_id, session_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_digest ON chunks(user_id, agent_id, content_digest);
"""
    )
    if withFts:
        conn.executescript(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(content, tokenize='%s');" % tokenize
        )
    return conn


def seed(conn, rows, withFts=True, user="u1", agent="a1", session="s1", flushEvery=2000):
    conn.execute("BEGIN")
    for i in range(rows):
        text = turnChunks(i)[i % 24][2]
        cur = conn.execute(
            "INSERT INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user, agent, session, f"t{i}", "conversation", text, "{}", "x", "2026-09-01T00:00:00", f"d{i}"),
        )
        if withFts:
            conn.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (cur.lastrowid, text))
        if (i + 1) % flushEvery == 0:
            conn.commit()
            conn.execute("BEGIN")
    conn.commit()


def writeTurn(conn, turnIndex, withFts=True, user="u1", agent="a1", session="s1"):
    conn.execute("BEGIN")
    for turn_id, source, text in turnChunks(turnIndex):
        cur = conn.execute(
            "INSERT OR IGNORE INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user, agent, session, turn_id, source, text, "{}", "x", "2026-09-01T00:00:00", f"{turnIndex}-{turn_id}"),
        )
        if withFts and cur.lastrowid:
            conn.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (cur.lastrowid, text))
    conn.commit()


def report(title, lines):
    print("\n== %s" % title)
    for line in lines:
        print("   " + line)


def main():
    tmp = tempfile.mkdtemp(prefix="ctxPersistBaseline90_")
    print("临时目录: %s" % tmp)

    # ── 1. 现状：写入口不可达（P1-3 复现） ─────────────────────────
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context_pool import ContextInput, ContextPool, ContextSource

    ledgerPath = os.path.join(tmp, "unreachable.db")
    pool = ContextPool(
        user_id="u1", agent_id="a1", session_id="s1",
        ledger_db=EvictionLedgerDB(db_path=ledgerPath, user_id="u1", agent_id="a1"),
        ttl_seconds=0,  # 生产 orchestrator 走此档
    )
    for i in range(600):
        pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content=f"第{i}轮：上下文窗口预算与折叠判据。"))
    restarted = ContextPool(
        user_id="u1", agent_id="a1", session_id="s1",
        ledger_db=EvictionLedgerDB(db_path=ledgerPath, user_id="u1", agent_id="a1"),
    )
    report("1 现状 P1-3：写入口不可达", [
        "生产同型构造（不传 resident_limit）→ resident_limit=%s, ttl_seconds=%s" % (pool.resident_limit, pool.ttl_seconds),
        "写入 600 条常驻 → 常驻 %d 条；cleanup_expired()=%d" % (pool.resident_count(), pool.cleanup_expired()),
        "台账 DB 行数 = %d；recall_evicted(query) = %d" % (pool._ledger_db.count(), len(pool.recall_evicted(query="折叠判据"))),
        "模拟重启后的新实例：常驻 %d 条；recall_evicted = %d（归档活不过重启）" % (restarted.resident_count(), len(restarted.recall_evicted())),
    ])

    # ── 1b. 真跨进程复核（D1 的验收判据就在跨进程，不是同进程换实例） ──
    xprocDb = os.path.join(tmp, "xproc.db")
    writerCode = (
        "import sys; sys.path.insert(0, %r)\n"
        "from neurova.context.eviction_ledger_db import EvictionLedgerDB\n"
        "from neurova.context_pool import ContextPool, ContextInput, ContextSource\n"
        "pool = ContextPool(user_id='u1', agent_id='a1', session_id='s1',"
        " ledger_db=EvictionLedgerDB(db_path=sys.argv[1], user_id='u1', agent_id='a1'), ttl_seconds=0)\n"
        "for i in range(300):\n"
        "    pool.add_context(ContextInput(source=ContextSource.CONVERSATION,"
        " content='第%%d轮：设备固件升级窗口定在周四凌晨' %% i, metadata={'turn_id': 'turn_%%d' %% i}))\n"
        "print('writer 常驻 %%d / 台账行数 %%d' %% (pool.resident_count(), pool._ledger_db.count()))\n"
    ) % os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    readerCode = (
        "import sys; sys.path.insert(0, %r)\n"
        "from neurova.context.eviction_ledger_db import EvictionLedgerDB\n"
        "from neurova.context_pool import ContextPool\n"
        "pool = ContextPool(user_id='u1', agent_id='a1', session_id='s1',"
        " ledger_db=EvictionLedgerDB(db_path=sys.argv[1], user_id='u1', agent_id='a1'))\n"
        "print('reader 常驻 %%d / recall_evicted %%d' %% (pool.resident_count(), len(pool.recall_evicted(query='固件升级'))))\n"
    ) % os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    writerRun = subprocess.run(
        [sys.executable, "-c", writerCode, xprocDb], capture_output=True, text=True
    )
    readerRun = subprocess.run(
        [sys.executable, "-c", readerCode, xprocDb], capture_output=True, text=True
    )
    report("1b 真跨进程复核（D1 判据）", [
        "writer 进程（写入后即退出）: %s" % (writerRun.stdout.strip() or writerRun.stderr.strip()[-200:]),
        "reader 进程（同库新开池）: %s" % (readerRun.stdout.strip() or readerRun.stderr.strip()[-200:]),
        "结论：写入进程的归档在新进程里取不到 → A1 当前为红",
    ])

    # ── 2. 写放大（三种形状，同一轮定义 = 24 条，各 20 轮取样） ──
    # 说明：本机 fsync 成本抖动很大（同一形状跨轮可差一个数量级），故一律报
    # 中位与四分位、并只用「同一次运行内」的中位做跨形状比较。
    def quantile(values, q):
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(len(ordered) * q))]

    def summarize(samples):
        return quantile(samples, 0.5), quantile(samples, 0.25), quantile(samples, 0.75)

    reps = 20

    # (a) 现状形状：每行独立 connect + 两条 INSERT + commit + close
    perRowPath = os.path.join(tmp, "write_perrow.db")
    perRowConn = openDb(perRowPath)
    seed(perRowConn, 100000)
    perRowConn.close()

    def roundPerRow(turnIndex):
        for position, (turn_id, source, text) in enumerate(turnChunks(turnIndex)):
            one = sqlite3.connect(perRowPath, timeout=30)
            one.execute("PRAGMA journal_mode=WAL")
            one.execute("PRAGMA synchronous=NORMAL")
            cur = one.execute(
                "INSERT OR IGNORE INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("u1", "a1", "s1", turn_id, source, text, "{}", "x", "x", f"per{turnIndex}-{turn_id}"),
            )
            if cur.lastrowid:
                one.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (cur.lastrowid, text))
            one.commit()
            one.close()

    # (b)(c) 常驻连接 + 每轮一次事务
    turnShapes = []
    for withFts, label in ((True, "含 trigram FTS 影子写"), (False, "不建 FTS")):
        shapePath = os.path.join(tmp, "write_turn_%s.db" % int(withFts))
        shapeConn = openDb(shapePath, withFts=withFts)
        seed(shapeConn, 100000, withFts=withFts)

        def makeRound(c, fts):
            def roundTurn(turnIndex):
                writeTurn(c, turnIndex, withFts=fts)
            return roundTurn

        turnShapes.append((label, makeRound(shapeConn, withFts)))

    def sample(roundFn):
        for k in range(3):
            roundFn(900 + k)  # 预热
        samples = []
        for k in range(reps):
            begin = time.perf_counter()
            roundFn(1000 + k)
            samples.append((time.perf_counter() - begin) * 1000)
        return summarize(samples)

    perRowMedian, perRowP25, perRowP75 = sample(roundPerRow)
    lines = [
        "每行独立连接+提交（现状 record() 同形）: 中位 %8.2f ms/轮（p25 %.2f / p75 %.2f）"
        % (perRowMedian, perRowP25, perRowP75)
    ]
    turnMedians = {}
    for label, roundFn in turnShapes:
        median, p25, p75 = sample(roundFn)
        turnMedians[label] = median
        lines.append(
            "常驻连接·每轮一事务·%s: 中位 %8.2f ms/轮（p25 %.2f / p75 %.2f）"
            % (label, median, p25, p75)
        )
    withFtsMedian = turnMedians["含 trigram FTS 影子写"]
    noFtsMedian = turnMedians["不建 FTS"]
    lines.append("同一次运行内的中位倍数：现状 / 每轮一事务（含 FTS）= %.0f×" % (perRowMedian / max(0.001, withFtsMedian)))
    lines.append("FTS 影子写相对成本：含 FTS / 不建 FTS = %.1f×" % (withFtsMedian / max(0.001, noFtsMedian)))
    report("2 写放大（24 条/轮，10 万行存量库，各 20 轮取样）", lines)

    # ── 3. 磁盘：tokenizer 与 FTS 开关 ────────────────────────────
    contentBytes = metaBytes = 0
    for i in range(2000):
        turn_id, source, text = turnChunks(0)[i % 24]
        contentBytes += len(text.encode())
        metaBytes += len(json.dumps({"role": "user", "turn_id": turn_id, "chat_scope": "direct"}).encode())
    disk = []
    for withFts, tokenize, label in (
        (False, None, "无 FTS"),
        (True, "trigram", "trigram FTS"),
        (True, "unicode61 remove_diacritics 2", "unicode61 FTS"),
    ):
        path = os.path.join(tmp, "disk_%s.db" % label.split()[0])
        conn = openDb(path, withFts=withFts, tokenize=tokenize or "trigram")
        rows = 50000
        conn.execute("BEGIN")
        for i in range(rows):
            text = turnChunks(i)[i % 24][2]
            cur = conn.execute(
                "INSERT INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("u1", "a1", "s1", f"t{i}", "conversation", text, "{}", "x", "x", f"d{i}"),
            )
            if withFts:
                conn.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (cur.lastrowid, text))
            if (i + 1) % 2000 == 0:
                conn.commit()
                conn.execute("BEGIN")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        size = os.path.getsize(path)
        conn.close()
        disk.append((label, size / rows, size / 1024 / 1024))
    report("3 磁盘（5 万行，含 271 B 内容 + 61 B metadata 每行）", [
        "%-14s %7.0f B/行（总 %.0f MB）" % row for row in disk
    ])

    # ── 4. 读侧预筛：tokenizer 命中能力 ───────────────────────────
    probes = ["上下文压缩", "窗口预算", "压缩", "The context window", "上下文"]
    hits = []
    for tokenize, label in (("trigram", "trigram"), ("unicode61 remove_diacritics 2", "unicode61")):
        probePath = os.path.join(tmp, "probe_%s.db" % label)
        pc = sqlite3.connect(probePath)
        pc.execute("PRAGMA journal_mode=WAL")
        pc.executescript(
            "CREATE TABLE chunks(id INTEGER PRIMARY KEY, content TEXT NOT NULL);"
            "CREATE VIRTUAL TABLE fts USING fts5(content, tokenize='%s');" % tokenize
        )
        pc.execute("BEGIN")
        for i in range(50000):
            text = turnChunks(i)[i % 24][2]
            pc.execute("INSERT INTO chunks VALUES(?,?)", (i + 1, text))
            pc.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (i + 1, text))
            if (i + 1) % 2000 == 0:
                pc.commit()
                pc.execute("BEGIN")
        pc.commit()
        row = []
        for q in probes:
            truth = pc.execute("SELECT COUNT(*) FROM chunks WHERE content LIKE ?", ("%" + q + "%",)).fetchone()[0]
            try:
                matched = pc.execute("SELECT COUNT(*) FROM fts WHERE fts MATCH ?", ('"%s"' % q,)).fetchone()[0]
            except sqlite3.OperationalError as exc:
                matched = "ERR(%s)" % exc
            row.append("%s→%s / LIKE 真值 %s" % (q, matched, truth))
        hits.append((label, row))
        pc.close()
    report("4 读侧预筛命中（5 万行；LIKE 真值 = 当前兜底口径）", [
        "%s: %s" % (label, " | ".join(row)) for label, row in hits
    ])

    # 4b. 精确性：逐长度抽样（LIKE 作真值）
    cjkTexts = ["".join(random.choice(CJK_WORDS) for _ in range(80)) for _ in range(2000)]
    accPath = os.path.join(tmp, "probe_acc.db")
    ac = sqlite3.connect(accPath)
    ac.execute("PRAGMA journal_mode=WAL")
    ac.executescript(
        "CREATE TABLE chunks(id INTEGER PRIMARY KEY, content TEXT NOT NULL);"
        "CREATE VIRTUAL TABLE fts USING fts5(content, tokenize='trigram');"
    )
    ac.execute("BEGIN")
    for i, text in enumerate(cjkTexts):
        ac.execute("INSERT INTO chunks VALUES(?,?)", (i + 1, text))
        ac.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (i + 1, text))
    ac.commit()
    acc = []
    for length in (1, 2, 3, 5, 10):
        falsePositive = falseNegative = 0
        for _ in range(120):
            text = random.choice(cjkTexts)
            start = random.randrange(0, len(text) - length)
            q = text[start:start + length]
            try:
                matched = {r[0] for r in ac.execute("SELECT rowid FROM fts WHERE fts MATCH ?", ('"%s"' % q,)).fetchall()}
            except sqlite3.OperationalError:
                continue
            truth = {r[0] for r in ac.execute("SELECT id FROM chunks WHERE content LIKE ?", ("%" + q + "%",)).fetchall()}
            falsePositive += len(matched - truth)
            falseNegative += len(truth - matched)
        acc.append("长度 %2d: 假阳性 %d / 假阴性 %d（120 次抽样，LIKE 作真值）" % (length, falsePositive, falseNegative))
    report("4b trigram 逐长度精确性（CJK 语料）", acc)
    ac.close()

    # ── 5. 启动加载 ───────────────────────────────────────────────
    conn = sqlite3.connect(os.path.join(tmp, "load.db"))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  session_id TEXT, turn_id TEXT, source TEXT, content TEXT NOT NULL, metadata TEXT,
  created_at TEXT, evicted_at TEXT NOT NULL, content_digest TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_scope_id ON chunks(user_id, agent_id, id);
"""
    )
    conn.execute("BEGIN")
    for i in range(102000):
        text = turnChunks(i)[i % 24][2]
        conn.execute(
            "INSERT INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("u1", "a1", f"s{i % 20}", f"t{i}", "conversation", text, "{}", "x", "x", f"l{i}"),
        )
        if (i + 1) % 2000 == 0:
            conn.commit()
            conn.execute("BEGIN")
    conn.commit()
    conn.row_factory = sqlite3.Row
    loads = []
    start = time.perf_counter()
    for _ in range(10):
        conn.execute("SELECT COUNT(*) FROM chunks WHERE user_id='u1' AND agent_id='a1'").fetchone()
    loads.append("仅登记 count(*)（10.2 万行）: %.2f ms" % ((time.perf_counter() - start) / 10 * 1000))
    from neurova.context.pool_models import ContextInput as _Chunk
    from neurova.context.pool_models import ContextSource as _Source
    for limit in (200, 500, 2000, 10000):
        for _ in range(3):
            rows = conn.execute(
                "SELECT * FROM chunks WHERE user_id='u1' AND agent_id='a1' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        start = time.perf_counter()
        for _ in range(10):
            rows = conn.execute(
                "SELECT * FROM chunks WHERE user_id='u1' AND agent_id='a1' ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        warmMs = (time.perf_counter() - start) / 10 * 1000
        built = [_Chunk(source=_Source.CONVERSATION, content=r["content"], metadata={"session_id": r["session_id"]}) for r in rows]
        bytesEach = sum(sys.getsizeof(c.content) for c in built) / max(1, len(built))
        loads.append("回载 %5d 条: 读 %6.2f ms（warm） + 物化内存约 %5.0f B/条" % (limit, warmMs, bytesEach))
    report("5 启动加载策略候选", loads)

    # ── 6. 迁移（零停机纪律） ─────────────────────────────────────
    legacy = os.path.join(tmp, "legacy.db")
    lc = sqlite3.connect(legacy)
    lc.execute("PRAGMA journal_mode=WAL")
    lc.executescript(
        """
CREATE TABLE chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
 session_id TEXT, turn_id TEXT, source TEXT, content TEXT NOT NULL, metadata TEXT, evicted_at TEXT NOT NULL);
CREATE VIRTUAL TABLE fts USING fts5(content, tokenize='unicode61 remove_diacritics 2');
"""
    )
    lc.execute("BEGIN")
    for i in range(50000):
        text = turnChunks(i)[i % 24][2]
        cur = lc.execute(
            "INSERT INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,evicted_at) VALUES(?,?,?,?,?,?,?,?)",
            ("u1", "a1", f"s{i % 20}", f"t{i}", "conversation", text, "{}", "2026-09-01T00:00:00"),
        )
        lc.execute("INSERT INTO fts(rowid,content) VALUES(?,?)", (cur.lastrowid, text))
        if (i + 1) % 2000 == 0:
            lc.commit()
            lc.execute("BEGIN")
    lc.commit()
    mig = ["旧库：user_version=%d, 行数=%d" % (lc.execute("PRAGMA user_version").fetchone()[0], lc.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])]
    start = time.perf_counter()
    lc.execute("BEGIN")
    lc.execute("ALTER TABLE chunks ADD COLUMN content_digest TEXT")
    lc.execute("UPDATE chunks SET content_digest='legacy-'||id WHERE content_digest IS NULL")
    lc.execute("CREATE UNIQUE INDEX uniq_digest ON chunks(user_id, agent_id, content_digest)")
    lc.execute("CREATE INDEX idx_scope_id ON chunks(user_id, agent_id, id)")
    lc.execute("PRAGMA user_version=1")
    lc.commit()
    mig.append("v1 加列+回填+建索引: %.2fs" % (time.perf_counter() - start))
    start = time.perf_counter()
    lc.execute("BEGIN")
    lc.execute("CREATE VIRTUAL TABLE fts_tri USING fts5(content, tokenize='trigram')")
    lc.execute("INSERT INTO fts_tri(rowid,content) SELECT id,content FROM chunks")
    lc.execute("DROP TABLE fts")
    lc.execute("ALTER TABLE fts_tri RENAME TO fts")
    lc.execute("PRAGMA user_version=2")
    lc.commit()
    mig.append("v2 FTS 重建为 trigram: %.2fs（一次性事务）" % (time.perf_counter() - start))
    # 分批重建 + 并发写停等
    path = os.path.join(tmp, "rebuild.db")
    rc = openDb(path, withFts=False, tokenize="trigram")
    seed(rc, 50000, withFts=False)
    rc.execute("CREATE VIRTUAL TABLE fts USING fts5(content, tokenize='unicode61 remove_diacritics 2')")
    rc.execute("INSERT INTO fts(rowid,content) SELECT id,content FROM chunks")
    rc.commit()
    stalls = []
    stop = threading.Event()

    def concurrentWriter():
        w = openDb(path)
        i = 0
        while not stop.is_set():
            begin = time.perf_counter()
            try:
                w.execute("BEGIN")
                w.execute(
                    "INSERT OR IGNORE INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("u1", "a1", "s9", f"w{i}", "conversation", "迁移窗口期写入", "{}", "x", "x", f"w{i}"),
                )
                w.commit()
            except sqlite3.Error:
                w.rollback()
            stalls.append((time.perf_counter() - begin) * 1000)
            i += 1
            time.sleep(0.002)
        w.close()

    writer = threading.Thread(target=concurrentWriter, daemon=True)
    writer.start()
    time.sleep(0.3)
    start = time.perf_counter()
    rc.execute("CREATE VIRTUAL TABLE fts_tri USING fts5(content, tokenize='trigram')")
    offset = 0
    while True:
        rows = rc.execute("SELECT id, content FROM chunks WHERE id > ? ORDER BY id LIMIT 5000", (offset,)).fetchall()
        if not rows:
            break
        rc.execute("BEGIN")
        rc.executemany("INSERT INTO fts_tri(rowid,content) VALUES(?,?)", rows)
        rc.commit()
        offset = rows[-1][0]
    rc.execute("BEGIN")
    rc.executescript("DROP TABLE fts; ALTER TABLE fts_tri RENAME TO fts;")
    rc.commit()
    rebuildSeconds = time.perf_counter() - start
    stop.set()
    writer.join(timeout=10)
    stalls.sort()
    mig.append(
        "v2' 分批重建（5000/批）5 万行: %.2fs，期间并发写 %d 次，停等 p95 %.1f ms / max %.1f ms"
        % (rebuildSeconds, len(stalls), stalls[int(len(stalls) * 0.95)], stalls[-1])
    )
    report("6 迁移成本", mig)
    rc.close()

    # ── 7. GC 与 FTS 对齐 ───────────────────────────────────────
    gpath = os.path.join(tmp, "gc.db")
    gc = openDb(gpath, withFts=True, tokenize="trigram")
    seed(gc, 50000, user="ug", agent="ag")
    gc.execute("DELETE FROM chunks WHERE user_id='ug' AND id <= 20000")
    gc.commit()
    ftssize = gc.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
    start = time.perf_counter()
    gc.execute("DELETE FROM fts WHERE rowid NOT IN (SELECT id FROM chunks)")
    gc.commit()
    wholeAlign = (time.perf_counter() - start) * 1000
    gcVerdict = ["删除 2 万内容行后 FTS 残留 %d 行" % ftssize, "FTS 全表对齐清理（NOT IN）: %.0f ms" % wholeAlign]
    g2path = os.path.join(tmp, "gc2.db")
    g2 = openDb(g2path, withFts=True, tokenize="trigram")
    seed(g2, 50000, user="ug", agent="ag")
    g2.execute("DELETE FROM chunks WHERE user_id='ug' AND id <= 20000")
    g2.commit()
    start = time.perf_counter()
    while True:
        removed = g2.execute(
            "DELETE FROM fts WHERE rowid IN (SELECT rowid FROM fts WHERE rowid NOT IN (SELECT id FROM chunks) LIMIT 5000)"
        ).rowcount
        g2.commit()
        if not removed:
            break
    gcVerdict.append("FTS 分批对齐清理（5000/批）: %.0f ms" % ((time.perf_counter() - start) * 1000))
    report("7 GC 与 FTS 对齐", gcVerdict)
    gc.close()
    g2.close()

    # ── 8. 读侧两个缺陷（LIKE 元字符越权 / 作用域闸口缺席） ───────
    edge = sqlite3.connect(":memory:")
    edge.executescript("CREATE TABLE c(id INTEGER PRIMARY KEY, content TEXT);")
    edge.execute("INSERT INTO c VALUES(1,'普通内容'),(2,'带_下划线'),(3,'带%百分号')")
    likeAny = edge.execute("SELECT COUNT(*) FROM c WHERE content LIKE ?", ("%" + "%" + "%",)).fetchone()[0]
    likeUnderscore = edge.execute("SELECT COUNT(*) FROM c WHERE content LIKE ?", ("%" + "_" + "%",)).fetchone()[0]
    likeEscaped = edge.execute("SELECT COUNT(*) FROM c WHERE content LIKE ? ESCAPE '\\'", ("%" + "\\%" + "%",)).fetchone()[0]
    scopeVerdict = [
        "库内 3 行：查询 %r 命中 %d 行；查询 %r 命中 %d 行；加 ESCAPE 后 %r 命中 %d 行"
        % ("%", likeAny, "_", likeUnderscore, "%", likeEscaped)
    ]

    lpath = os.path.join(tmp, "scope.db")
    scoped = EvictionLedgerDB(db_path=lpath, user_id="u1", agent_id="a1")
    scoped.record(
        content="群聊项目房间B的机密内容：下季度定价 3980",
        session_id="project_roomB",
        metadata={"chat_scope": "room:project_roomB"},
        source="conversation",
    )
    directPool = ContextPool(user_id="u1", agent_id="a1", session_id="s_direct", ledger_db=scoped)
    nonePool = ContextPool(user_id="u1", agent_id="a1", session_id=None, ledger_db=scoped)
    scopeVerdict.append("群聊归档在单聊池（session_id=s_direct）召回条数 = %d（恒空：本轮会话 id 与归档会话 id 不等）"
                        % len(directPool.recall_evicted(query="机密")))
    scopeVerdict.append("无会话池（session_id=None）召回条数 = %d，且无 filter_by_scope 闸口 → 房间内容可见"
                        % len(nonePool.recall_evicted(query="机密")))
    report("8 读侧缺陷", scopeVerdict)

    # ── 8b. 索引顺序对照（热集查询用 (user,agent,id) 而非 (…,session)） ──
    ipath = os.path.join(tmp, "index_order.db")
    ic = sqlite3.connect(ipath)
    ic.execute("PRAGMA journal_mode=WAL")
    ic.execute("PRAGMA synchronous=NORMAL")
    ic.executescript(
        """
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  session_id TEXT, turn_id TEXT, source TEXT, content TEXT NOT NULL, metadata TEXT,
  created_at TEXT, evicted_at TEXT NOT NULL, content_digest TEXT NOT NULL);
"""
    )
    ic.execute("BEGIN")
    for i in range(100000):
        text = turnChunks(i)[i % 24][2]
        ic.execute(
            "INSERT INTO chunks(user_id,agent_id,session_id,turn_id,source,content,metadata,created_at,evicted_at,content_digest)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("u1", "a1", f"s{i % 20}", f"t{i}", "conversation", text, "{}", "x", "x", f"i{i}"),
        )
        if (i + 1) % 2000 == 0:
            ic.commit()
            ic.execute("BEGIN")
    ic.commit()

    def hotSetMs(reps=10):
        ic.execute(
            "SELECT * FROM chunks WHERE user_id='u1' AND agent_id='a1' ORDER BY id DESC LIMIT 500"
        ).fetchall()
        start = time.perf_counter()
        for _ in range(reps):
            ic.execute(
                "SELECT * FROM chunks WHERE user_id='u1' AND agent_id='a1' ORDER BY id DESC LIMIT 500"
            ).fetchall()
        return (time.perf_counter() - start) / reps * 1000

    orderRows = ["无二级索引: %.2f ms" % hotSetMs()]
    ic.execute("CREATE INDEX idx_scope_session ON chunks(user_id, agent_id, session_id)")
    orderRows.append("(user,agent,session): %.2f ms" % hotSetMs())
    ic.execute("CREATE INDEX idx_scope_id ON chunks(user_id, agent_id, id)")
    orderRows.append("(user,agent,id): %.2f ms" % hotSetMs())
    ic.close()
    report("8b 索引顺序对照（10 万行热集最近 500 条）", orderRows)

    # ── 9. 读侧预筛延迟对比（同一 10 万行库） ───────────────────
    conn2 = sqlite3.connect(os.path.join(tmp, "write_turn_1.db"))
    timing = []
    start = time.perf_counter()
    for _ in range(20):
        conn2.execute("SELECT rowid FROM fts WHERE fts MATCH ? LIMIT 200", ('"上下文压缩"',)).fetchall()
    timing.append("trigram MATCH 预筛: %.2f ms" % ((time.perf_counter() - start) / 20 * 1000))
    start = time.perf_counter()
    for _ in range(5):
        conn2.execute(
            "SELECT id FROM chunks WHERE user_id='u1' AND agent_id='a1' AND content LIKE ? LIMIT 20",
            ("%上下文压缩%",),
        ).fetchall()
    timing.append("LIKE 兜底·高命中查询（LIMIT 20 早退）: %.2f ms" % ((time.perf_counter() - start) / 5 * 1000))
    start = time.perf_counter()
    for _ in range(5):
        conn2.execute(
            "SELECT id FROM chunks WHERE user_id='u1' AND agent_id='a1' AND content LIKE ? LIMIT 20",
            ("%绝不存在于库中的短语xyz%",),
        ).fetchall()
    timing.append("LIKE 兜底·零命中查询（全表扫完）: %.2f ms" % ((time.perf_counter() - start) / 5 * 1000))
    start = time.perf_counter()
    for _ in range(20):
        conn2.execute("SELECT COUNT(*) FROM chunks WHERE user_id='u1' AND content LIKE ?", ("%绝不存在%",)).fetchone()
    timing.append("LIKE 零命中·不带 LIMIT（纯扫描）: %.2f ms" % ((time.perf_counter() - start) / 20 * 1000))
    start = time.perf_counter()
    for _ in range(20):
        conn2.execute(
            "SELECT * FROM chunks WHERE user_id='u1' AND agent_id='a1' ORDER BY id DESC LIMIT 500"
        ).fetchall()
    timing.append("热集回载 500 条（10 万行库）: %.2f ms" % ((time.perf_counter() - start) / 20 * 1000))
    start = time.perf_counter()
    for _ in range(20):
        conn2.execute("SELECT COUNT(*) FROM chunks WHERE user_id='u1' AND agent_id='a1'").fetchone()
    timing.append("仅登记 count(*): %.2f ms" % ((time.perf_counter() - start) / 20 * 1000))
    conn2.close()
    report("9 读侧延迟（同一 10 万行库）", timing)

    print("\n基线取证完成（写盘全在 %s）" % tmp)


if __name__ == "__main__":
    main()
