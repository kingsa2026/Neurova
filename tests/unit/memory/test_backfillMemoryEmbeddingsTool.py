"""一次性嵌入回填工具（§6-215 那张票的乙案）的目标契约。

乙的动机是实测出来的：`embedding` 出得了正文出口（§6-215）之后，路通了但没有车——
现网 16 行该列全空，睡眠聚类因两侧无嵌入而恒单例。本工具把既有行填上，
**唯一的正当来源是引擎真算出来的向量**：引擎不可用时必须点名失败、一行都不写，
绝不许拿随机数或占位向量冒充（那是教义第 2 条禁止的表面抹除）。

写侧也不许另起一路：必须走 `MemoryManager.persist_memory_batch` 那唯一写口——
裸 SQL 会绕开作用域 upsert、内容门索引与 FTS 影子行，等于给同一件事造第二个落点。
"""
from __future__ import annotations

import ast
import zlib
from pathlib import Path

STUB_DIM = 16
# 甲3（§6-219）之后"聚成一簇"要求内容**近等价**：短者的归一化键是长者的子串，
# 且由本文件假引擎算出的余弦达得到近等价下限（实测 0.992）。
SIMILAR_A = "登录页验证码在弱网下加载超时，用户已提交投诉并要求尽快给出修复排期"
SIMILAR_B = SIMILAR_A + "，已复核"
UNRELATED = "本周会议纪要讨论了排期与预算分配"


class _StubEngine:
    """确定性的假引擎：按字符 crc32 散列出一个归一化向量。

    不是 MagicMock——它真的有数值行为：近等价文本算出近等价向量（实测 SIMILAR_A/B 的
    cos=0.9922，达得到甲3 的合并下限），无关文本方向不同（cos=0.5574 < 阈值）。
    被测对象是工具的写侧与失败形态，不是模型质量。

    为什么用 `zlib.crc32` 而不是内置 `hash()`：**字符串哈希按进程加盐**（PYTHONHASHSEED），
    第一版用 `hash(ch)` 时长得不同的两条文本余弦会在 0.74~0.84 之间跳——**无关文本偶尔越过
    聚类阈值**，于是"能否聚成簇"那格变成间歇红（同一档连跑三次，第二次就红）。判据自己不稳，
    读出来的红就没法归因。
    """

    def __init__(self, failToInitialize: bool = False):
        self.dimension = STUB_DIM
        self.calls = []
        self._fail = failToInitialize

    def initialize_sync(self) -> bool:
        return not self._fail

    def encode(self, text: str):
        self.calls.append(text)
        vec = [0.0] * STUB_DIM
        for ch in (text or ""):
            vec[zlib.crc32(ch.encode("utf-8")) % STUB_DIM] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


def _tool():
    from scripts import backfill_memory_embeddings as tool

    return tool


def _dbPathOf(tmp_path: Path) -> str:
    return str(tmp_path / "memory.db")


def _seed(tmp_path: Path, *contents: str):
    from tests.cognitive_body_store import bodyManager

    manager = bodyManager(tmp_path, agentId="backfill")
    for c in contents:
        manager.remember(content=c)
    return manager


def _embeddingsInBody(dbPath: str):
    import json
    import sqlite3

    persist = Path(dbPath).parent / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % persist.as_posix(), uri=True)
    try:
        rows = con.execute("select id, content, embedding from memories order by id").fetchall()
    finally:
        con.close()
    return {rid: (json.loads(raw) if raw else []) for rid, _c, raw in rows}


def test_onlyFillsMissingEmbeddings(tmp_path: Path):
    """主格：只补 NULL 的那些，已有向量的行一律不动。"""
    tool = _tool()
    manager = _seed(tmp_path, SIMILAR_A, UNRELATED)
    sentinel = [0.111] * STUB_DIM
    existingId = next(m.id for m in manager._memories.values() if UNRELATED in m.content)
    with manager._lock:
        manager._memories[existingId].embedding = list(sentinel)
        manager.persist_memory_batch([manager._memories[existingId]])

    result = tool.backfillAgent("backfill", _StubEngine(), dbPath=_dbPathOf(tmp_path))

    after = _embeddingsInBody(_dbPathOf(tmp_path))
    assert result["filled"] == 1, "只该补那一行 NULL（实得 %s）" % result
    assert len(after[existingId]) == STUB_DIM and abs(after[existingId][0] - 0.111) < 1e-9, (
        "已有嵌入被覆盖了——回填工具不许改写既有向量"
    )
    filledId = next(rid for rid, vec in after.items() if rid != existingId)
    assert len(after[filledId]) == STUB_DIM


def test_secondRunIsIdempotent(tmp_path: Path):
    """幂等：第二次跑一行也不填（可反复执行才是运维可用的工具）。"""
    tool = _tool()
    _seed(tmp_path, SIMILAR_A, UNRELATED)
    engine = _StubEngine()

    first = tool.backfillAgent("backfill", engine, dbPath=_dbPathOf(tmp_path))
    callsAfterFirst = len(engine.calls)
    second = tool.backfillAgent("backfill", engine, dbPath=_dbPathOf(tmp_path))

    assert first["filled"] == 2
    assert second["filled"] == 0, "第二次又填了一遍 ⇒ 幂等性没了，运维每次都得赌"
    assert second["skippedExisting"] == 2
    assert len(engine.calls) == callsAfterFirst, "第二次仍在算嵌入 ⇒ 白烧一遍推理"


def test_engineUnavailableWritesNothingAndFailsLoudly(tmp_path: Path, monkeypatch):
    """引擎不可用 ⇒ 一行不写、退出码非零、点名原因；绝不用占位向量冒充成功。"""
    tool = _tool()
    _seed(tmp_path, SIMILAR_A)

    monkeypatch.setattr(tool, "defaultEngine", lambda: None)
    outcome = tool.main(["--agent", "backfill", "--db-path", _dbPathOf(tmp_path)])

    assert outcome != 0, "引擎不可用却回 0 ⇒ 报表上写着'回填完成'，库里照旧全空"
    assert all(len(v) == 0 for v in _embeddingsInBody(_dbPathOf(tmp_path)).values()), (
        "引擎缺席时仍写入了东西——写的必然是假向量"
    )


def test_engineFailingToInitializeIsReportedNotSwallowed(tmp_path: Path):
    """引擎对象在但初始化失败：同样不得写入，且失败要上抛到退出码。"""
    tool = _tool()
    _seed(tmp_path, SIMILAR_A)

    outcome = tool.backfillAgent("backfill", _StubEngine(failToInitialize=True),
                                 dbPath=_dbPathOf(tmp_path))
    assert outcome["filled"] == 0
    assert outcome.get("error"), "初始化失败却没带原因 ⇒ 调用方无从区分'没得填'与'填不了'"


def test_blankContentRowIsSkippedNotCrashing(tmp_path: Path):
    """空内容行跳过并计数，整批不炸。"""
    tool = _tool()
    manager = _seed(tmp_path, SIMILAR_A)
    with manager._lock:
        blank = next(iter(manager._memories.values()))
        blank.content = ""
        manager.persist_memory_batch([blank])

    result = tool.backfillAgent("backfill", _StubEngine(), dbPath=_dbPathOf(tmp_path))
    assert result["skippedBlank"] >= 1, "空内容没被计数——它会伪装成'填了但算了个空向量'"
    assert result["filled"] == 0


def test_dryRunLeavesStoreUntouched(tmp_path: Path):
    """dry-run：只报数不写盘（回填前先看清影响面才有得谈）。"""
    tool = _tool()
    _seed(tmp_path, SIMILAR_A, UNRELATED)

    result = tool.backfillAgent("backfill", _StubEngine(),
                                dbPath=_dbPathOf(tmp_path), dryRun=True)
    assert result["filled"] == 0
    assert result["wouldFill"] == 2
    assert all(len(v) == 0 for v in _embeddingsInBody(_dbPathOf(tmp_path)).values())


def test_backfilledVectorsActuallyFeedTheClusteringFace(tmp_path: Path):
    """本工具的存在理由：填完之后经正文出口取数，相近的两条真能聚成一簇。"""
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from tests.cognitive_body_store import bodyManager

    tool = _tool()
    _seed(tmp_path, SIMILAR_A, SIMILAR_B, UNRELATED)
    result = tool.backfillAgent("backfill", _StubEngine(), dbPath=_dbPathOf(tmp_path))
    assert result["filled"] == 3

    manager = bodyManager(tmp_path, agentId="backfill")
    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    assert all(len(r.embedding) == STUB_DIM for r in records), (
        "回填完再取仍是空的 ⇒ 写侧没落到那份读面看得见的地方"
    )
    clusters = SleepConsolidation(memory_manager=manager).cluster_by_similarity(records)
    sizes = sorted(len(c) for c in clusters)
    assert 2 in sizes, (
        "三条真向量聚不出一个 ≥2 的簇（尺寸=%s）⇒ 工具达成了写入却没达成目的" % sizes
    )


def test_toolDoesNotBypassTheManagerWriteThroat():
    """形状锁：工具不许自己开 SQL 写正文表——那是给同一件事造第二个落点。"""
    here = Path(__file__).resolve()
    candidate = here.parents[3] / "scripts" / "backfill_memory_embeddings.py"
    assert candidate.exists(), "工具档不在 expected 处（%s）⇒ 这格会空转" % candidate
    tree = ast.parse(candidate.read_text(encoding="utf-8"))

    banned_imports = set()
    banned_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ("sqlite3",):
                    banned_imports.add(alias.name)
        if isinstance(node, ast.Call):
            name = node.func
            if isinstance(name, ast.Attribute) and name.attr in ("execute", "executescript",
                                                                 "executemany"):
                banned_calls.append(name.attr)
    assert not banned_imports, "工具直连 sqlite3 了：%s" % banned_imports
    assert not banned_calls, "工具里有裸 SQL 调用：%s" % banned_calls
