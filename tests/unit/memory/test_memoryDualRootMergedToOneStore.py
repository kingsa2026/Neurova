# -*- coding: utf-8 -*-
"""记忆正文只准有一个落点：主库同目录的 `neurova_memories_persist.db`（下称 A1）。

本批契约（裁定见 `audit-reports/memory-dual-root-comparison-2026-10-14.md` §6 Q1，
用户 2026-10-14 裁「三层能力（FTS5/向量/LSM）要保」）：

- FTS5(trigram) 影子表与三条触发器长在 A1 的 `memories` 表上；全文检索查询归
  `MemoryManager`——作用域三元组（agent/neuser/user）只有它那一处出处。
- `CognitiveStorageEngine` 不再持有正文库与 schema，只保留 L0 缓冲、wal 崩溃恢复、
  内存向量索引；写经 `MemoryManager` 的唯一写入口落 A1，读经 `MemoryManager` 的作用域口径。
- `data/<agent>/memory.db` 这个第二落点退役。

红形态两类，提交正文里分开列：
`TestBodyTableGainsTheMergedCapabilities` 走既有 API，今日实测红在形状/行为断言上；
`TestEngineReadsAndWritesTheOneBodyTable` 走新构造签名，今日为 TypeError（新符号红）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    MemoryType,
    UnifiedMemoryNode,
)
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.persist_landing import persistCompanionPath
from neurova.core.data_root import DATA_ROOT_ENV

AGENT = "dualroot-agent"
CJK_SENTENCE = "我始终会把你的记忆保护好，哪怕每次重启之后"
# 取 5 字连续子串：trigram 分词（≥3 字）能命中，默认 unicode61 在整串中文 token 下必不命中——
# 这一维是本批「FTS5 存在 ≠ FTS5 能用」的变异对照锚点。
CJK_TERM = "记忆保护好"

_NEUROVA = Path(__file__).resolve().parents[3] / "neurova"
_MEMORIES_DDL = "CREATE TABLE IF NOT EXISTS memories ("
# 扫描面 = 记忆正文的装配面（memory_layer 包 + mem_core）。
# `neurova/memory/scripts/*.py` 那三处建的是 legacy 种子库 `yi_ling_memory.db`
# （列集是另一套：type/weight/content_hash），属另一功能面、无生产与 CI 入口，
# 已按教义第 5 条登记进档案 §7，不在本批退役。
_BODY_SCHEMA_DIR = _NEUROVA / "cognitive_layers" / "memory_layer"


def _bodySchemaProducers() -> list:
    producers = []
    for py in [_NEUROVA / "mem_core.py", *_BODY_SCHEMA_DIR.rglob("*.py")]:
        if _MEMORIES_DDL in py.read_text(encoding="utf-8", errors="replace"):
            producers.append(py)
    return producers


def _columns(dbPath: Path, table: str = "memories") -> set:
    con = sqlite3.connect(str(dbPath))
    try:
        return {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
    finally:
        con.close()


def _ftsHits(dbPath: Path, term: str):
    """按 A1 的 FTS 影子表取命中 id；影子表不在则回 None（让判据红在断言，不是红在 OperationalError）。"""
    con = sqlite3.connect(str(dbPath))
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        ).fetchone() is None:
            return None
        return [
            row[0]
            for row in con.execute(
                "SELECT m.id FROM memories m JOIN memories_fts f ON m.rowid = f.rowid"
                " WHERE memories_fts MATCH ? ORDER BY rank",
                (term,),
            )
        ]
    finally:
        con.close()


@pytest.fixture()
def body(tmp_path):
    """真 MemoryManager + 它的 A1 正文库路径（落点取生产单点，不手抄文件名）。"""
    mainDb = tmp_path / "memory.db"
    manager = MemoryManager(
        db_path=str(mainDb),
        agent_id=AGENT,
        neuser_id="neuser-a",
        user_id="user-a",
        enable_buffer=False,
    )
    return manager, persistCompanionPath(mainDb)


def _engine(manager):
    return CognitiveStorageEngine(agent_id=AGENT, memory_manager=manager)


class TestBodyTableGainsTheMergedCapabilities:
    """取长补短落点：A1 是唯一 memories 表，且它自己长出全文索引与向量列。"""

    def test_memoriesDdlExistsInProductionExactlyOnce(self):
        producers = _bodySchemaProducers()
        # 地板断言：扫描面必须至少扫到一处，否则「== 1」会被空扫描假绿
        assert producers, "扫描面一个建表定义都没扫到——扫描面失效，不是收口完成"
        assert len(producers) == 1, (
            "memories 正文表还有第二处建表定义：%s——两处 schema 各自漂移，"
            "就是本轮要收的双根本身（预期唯一出处是 MemoryManager）"
            % [str(p.relative_to(_NEUROVA)) for p in producers]
        )
        assert producers[0].name == "manager.py", (
            "正文表建表定义不在 MemoryManager 里：%s——选定那份写错了"
            % producers[0].name
        )

    def test_bodyTableCarriesTrigramShadowAndThreeTriggers(self, body):
        _, bodyPath = body
        assert bodyPath.exists(), "A1 正文库没建出来，本轮前提不成立"
        con = sqlite3.connect(str(bodyPath))
        try:
            names = {
                row[0] for row in con.execute("SELECT name FROM sqlite_master")
            }
        finally:
            con.close()
        assert "memories_fts" in names, "A1 上没有全文影子表——FTS5 能力还长在第二个库上"
        assert {"memories_ai", "memories_ad", "memories_au"} <= names, (
            "A1 的 memories 表上触发器不齐：%s——正文写入不会被索引，检索永远是空的"
            % sorted(n for n in names if str(n).startswith("memories_"))
        )

    def test_embeddingColumnIsPartOfTheBodyContract(self, body):
        _, bodyPath = body
        assert "embedding" in _columns(bodyPath), (
            "A1 没有 embedding 列——向量能力仍只存在于第二个库里，落盘即丢"
        )

    def test_cjkSubstringInsertedThroughManagerIsMatchable(self, body):
        manager, bodyPath = body
        memoryId = manager.add_memory(CJK_SENTENCE)
        hits = _ftsHits(bodyPath, CJK_TERM)
        assert hits is not None, "A1 上没有 memories_fts，中文子串检索无处可查"
        assert memoryId in hits, (
            "经真写入口落的中文记忆，按文本里就存在的 5 字子串检索不到——"
            "分词器不是 trigram 就是触发器没生效（本轮实测默认 unicode61 恒 0 命中）"
        )

    def test_deleteThroughBodyTablePrunesTheShadow(self, body):
        manager, bodyPath = body
        memoryId = manager.add_memory(CJK_SENTENCE)
        hits = _ftsHits(bodyPath, CJK_TERM)
        assert hits is not None and memoryId in hits, "前提未成立：写入侧还没进影子表"
        con = sqlite3.connect(str(bodyPath))
        con.execute("DELETE FROM memories WHERE id = ?", (memoryId,))
        con.commit()
        shadowRows = con.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        con.close()
        assert _ftsHits(bodyPath, CJK_TERM) == [], "删了正文，影子表仍能命中"
        assert shadowRows == 0, "影子表残留行——只删主表会让两表脱节"


class TestEngineReadsAndWritesTheOneBodyTable:
    """引擎退为 A1 之上的 L0/索引层：不再自建正文库，读写都经唯一写入口与作用域口径。"""

    def test_engineConstructionCreatesNoSecondStore(self, tmp_path, body, monkeypatch):
        manager, bodyPath = body
        otherRoot = tmp_path / "injected-data-root"
        monkeypatch.setenv(DATA_ROOT_ENV, str(otherRoot))
        _engine(manager)
        assert not (otherRoot / AGENT).exists(), (
            "构造引擎仍在数据根下按 agent 开第二个落点 %s——正文落点必须只有一处"
            % (otherRoot / AGENT)
        )

    def test_rowWrittenByManagerIsRecalledThroughEngine(self, body):
        manager, _ = body
        manager.add_memory(CJK_SENTENCE)
        nodes = _engine(manager).retrieve(CJK_TERM, limit=5)
        assert any(CJK_TERM in n.content for n in nodes), (
            "引擎召回不到正文库里的真行——方案A 那一路仍在读它自己的空库"
        )

    def test_engineStoreLandsInBodyTableUnderItsAgent(self, body):
        manager, bodyPath = body
        node = UnifiedMemoryNode(
            content=CJK_SENTENCE,
            memory_type=MemoryType.PATTERN,
            embedding=[0.25, 0.5],
        )
        engine = _engine(manager)
        engine.store(node)
        engine.close()  # 触发 L0 → 正文落盘
        con = sqlite3.connect(str(bodyPath))
        try:
            row = con.execute(
                "SELECT agent_id, embedding FROM memories WHERE id = ?", (node.id,)
            ).fetchone()
        finally:
            con.close()
        assert row is not None, "引擎 flush 的行没进正文库——第二个 memories 表还在被写"
        assert row[0] == AGENT, "行落进了正文库却没带 agent_id，隔离会退化成恒 default"
        assert row[1], "向量没随正文落盘"

    def test_recallHonorsTheEffectiveScope(self, body):
        manager, _ = body
        manager.add_memory(CJK_SENTENCE)
        engine = _engine(manager)
        with manager.request_scope("neuser-a", "user-a"):
            own = engine.retrieve(CJK_TERM, limit=10)
        assert any(CJK_TERM in n.content for n in own), "正例未成立：本作用域都召不回来"
        with manager.request_scope("neuser-b", "user-b"):
            other = engine.retrieve(CJK_TERM, limit=10)
        assert not any(CJK_TERM in n.content for n in other), (
            "另一用户作用域内召回到了别人的记忆——合并正文库后引擎读侧必须走生效三元组，"
            "否则收口本身就成了跨用户泄漏"
        )

    def test_walSidecarRecoversTheUnflushedRowAfterRestart(self, tmp_path, body):
        manager, bodyPath = body
        node = UnifiedMemoryNode(content=CJK_SENTENCE, memory_type=MemoryType.EPISODIC)
        _engine(manager).store(node)
        restarted = MemoryManager(
            db_path=str(bodyPath.parent / "memory.db"),
            agent_id=AGENT,
            neuser_id="neuser-a",
            user_id="user-a",
            enable_buffer=False,
        )
        nodes = _engine(restarted).retrieve(CJK_TERM, limit=10)
        assert any(n.id == node.id for n in nodes), (
            "未 flush 的 L0 节点在重建后召不回——LSM 的崩溃恢复层没落到正文库同目录，"
            "等于跟着第二个落点一起被删掉了"
        )
