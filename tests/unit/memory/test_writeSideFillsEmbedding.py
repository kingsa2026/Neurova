"""写侧必须给新行算出嵌入——§6-215 那张三态票的甲案（本仓实测：路通了两年，车一直没来）。

现网量到的形状（2026-10-15）：正文库 14 行里 12 行有向量，全是 `scripts/backfill_memory_embeddings.py`
**一次性**补的；`remember()` 到 `Memory(...)`（`manager.py:1522`）这条写链没有任何一处给
`embedding` 赋值，全仓唯一的生产者就是那个回填脚本。后果是可核的：那 2 行固化产物
`embedding IS NULL`，按甲3「任一侧无嵌入不合」（`sleep.py:_mergeAdmission`）永远进不了下一轮簇
——所以"这条腿开着"并不等于"这条腿会持续收拢记忆"，它对之后写入的每一行都是瞎的。

成本这一栏先前是凭想象反对的（"每轮多一次 provider 调用"）。实测把这条划掉：引擎是本地 ONNX
（`BAAI/bge-small-zh-v1.5`，512 维），暖调用 3.2ms／次（20 次均值），冷加载 0.41s 每进程一次；
且召回路的 `semantic_search.py:291` 早就在用同一个单例，写入时它通常已被暖好。

判据一律从**生产写入口**走（真 `MemoryManager` + 真正文库），引擎只在生产单例那一处替换
（`neurova.embedding.get_embedding_engine`）；不许把向量手工塞进对象再持久——那测得到形状、
测不到路通不通。最后一格是真闭环：产物行落进库、`reload_memories()` 装回来、下一轮固化和它
聚成簇。零向量与引擎缺席两格钉的是教义第 2 条：不许拿占位向量冒充"回填完成"。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from neurova.memory_ingest.bundle.records import MemoryRecord
from tests.cognitive_body_store import bodyManager

AGENT = "embedwrite"
VECTOR = [0.5] * 6


class StubEngine:
    """真引擎的替身：只回答"算得出/算不出"，向量取值由本格指定。

    `encodeOrNone` 与真引擎同一个契约（算不出回 None）：写侧问的是"算出向量了吗"，
    不是一个恒有返回值的 `encode`——替身少了这一半，替的就不是那个接口。
    """

    def __init__(self, vector: Optional[List[float]]):
        self._vector = vector
        self.calls: List[str] = []

    def initialize_sync(self) -> bool:
        return self._vector is not None

    def encode(self, text: str) -> List[float]:
        self.calls.append(text)
        if self._vector is None:
            raise RuntimeError("模型加载失败")
        return list(self._vector)

    def encodeOrNone(self, text: str) -> Optional[List[float]]:
        """算不出（未装模型 / 回全零）一律回 None —— 与真引擎同一契约。"""
        if self._vector is None:
            self.calls.append(text)
            return None
        vec = self.encode(text)
        return vec if any(vec) else None


def _patchEngine(monkeypatch, vector: Optional[List[float]]) -> StubEngine:
    """在生产单例那一处替换引擎——写侧不许另开第二条获取路（单一事实源）。"""
    stub = StubEngine(vector)
    monkeypatch.setattr("neurova.embedding.get_embedding_engine", lambda: stub)
    return stub


def _persistedRows(manager) -> List[dict]:
    persist = Path(manager._persist_db_path).parent / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % persist.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "select id, content, lifecycle_stage, embedding from memories order by id"
        ).fetchall()]
    finally:
        con.close()


def _rowOf(manager, businessId: str) -> dict:
    hits = [r for r in _persistedRows(manager) if r["id"].split("\x1f")[-1] == businessId]
    assert len(hits) == 1, "行 %s 在盘上数到 %d 份" % (businessId, len(hits))
    return hits[0]


def _vectorOf(row: dict) -> Optional[list]:
    raw = row.get("embedding")
    return json.loads(raw) if raw else None


def test_rememberFillsEmbeddingFromTheSingleSourceEngine(tmp_path: Path, monkeypatch):
    """主格：走真 `remember()` 的新行，内存对象与正文库两头都要有引擎算出的那份向量。

    只钉"对象上有值"不够——`_persist_row_params` 取的是 `mem.embedding`，写链断在对象→列
    这一段时就变成"进程内看着有、重启即空"（§6-215 那一族的现网形状）。
    """
    stub = _patchEngine(monkeypatch, VECTOR)
    manager = bodyManager(tmp_path, agentId=AGENT)
    mid = manager.remember(content="今天定下发布推迟到周四", id="w1")

    assert stub.calls, "写侧一次都没调用引擎 ⇒ 甲案仍未接线"
    assert manager._memories[mid].embedding == VECTOR, (
        "内存对象没带上引擎的向量（实得 %s）" % (manager._memories[mid].embedding,)
    )
    assert _vectorOf(_rowOf(manager, "w1")) == VECTOR, "正文库的 embedding 列仍是空 ⇒ 写链没通到盘"


def test_zeroVectorFromEngineIsNotStoredAsAnEmbedding(tmp_path: Path, monkeypatch):
    """教义第 2 条：引擎回全零＝没算出来。不许把它当"有向量"写进列里。

    写进占位向量的后果比留空更坏——`_mergeAdmission` 会拿它算出恒 0 的余弦，看起来
    "这条记忆有向量、只是不相似"，缺陷从此不可见（同仓先例：回填工具也拒绝写占位向量）。
    """
    stub = _patchEngine(monkeypatch, [0.0] * 6)
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="全零向量不该被当成嵌入", id="z1")

    row = _rowOf(manager, "z1")
    assert row["content"], "行本身没落库 ⇒ 不是判占位向量，是写链断了"
    assert stub.calls, "写侧一次都没调用引擎 ⇒ 本格会因'压根没算'而假绿"
    assert _vectorOf(row) is None, (
        "占位向量被写进了 embedding 列（实得 %s）" % (_vectorOf(row),)
    )


def test_unavailableEngineStillWritesTheRow(tmp_path: Path, monkeypatch):
    """引擎缺席（模型未装/初始化抛异常）⇒ 行照写、列留空、不把写入方炸掉。

    这一格钉的是"降级诚实"：不许因为补嵌入失败就丢用户内容，也不许吞掉异常不吭声。
    """
    stub = _patchEngine(monkeypatch, None)
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="没有引擎也要存下来的那件事", id="n1")

    assert _rowOf(manager, "n1")["content"] == "没有引擎也要存下来的那件事"
    assert _vectorOf(_rowOf(manager, "n1")) is None
    assert stub.calls, "引擎不可用时仍该试过（否则连降级读数都拿不到）"


def test_ingestWriterCarriesTheSameEmbedding(tmp_path: Path, monkeypatch):
    """同根因第二命中点（教义第 5 条）：`import_memories()` 的 `_record_to_memory`
    （`manager.py:1922`）是另一处建行，它同样不填嵌入——只修 `remember()` 就留下
    "导入的历史永远进不了固化"这第二条瞎腿。
    """
    _patchEngine(monkeypatch, VECTOR)
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.import_memories(
        [MemoryRecord(identity_key="ik-embed-1", content="导入的一段历史",
                      memory_type="semantic", category="general", origin="owner",
                      importance=60.0, ts="2026-05-01T10:00:00+00:00")],
        ingest_run_id="nvimp-embed-1",
    )

    rows = [r for r in _persistedRows(manager) if r["id"].split("\x1f")[-1].startswith("ing-")]
    assert len(rows) == 1, "导入行没落库（实得 %s）" % [r["id"] for r in _persistedRows(manager)]
    assert _vectorOf(rows[0]) == VECTOR, (
        "导入的新行 embedding 为空 ⇒ 建行的那两处只补了一处"
    )


def test_consolidationProductIsVisibleToTheNextRound(tmp_path: Path, monkeypatch):
    """闭环格：产物行必须带着嵌入回到下一轮的可比面，否则"写入→读取→反馈→再写入"断在最后一环。

    现网证据（§6-229 记录）：连跑三轮 `盘上 14→14→14`、`new_rows=[]`，看着像幂等，
    真相是产物没有嵌入所以永不进簇——幂等读数把这个断点掩护成了"已经收拢完了"。

    两轮都用真 `SleepConsolidation.start_sleep()`/`wake()` 与真写回：
    第一轮把两句近等价合成产物；`reload_memories()` 装回来（跨进程可见性的生产通道）；
    第二轮再写一句与产物近等价的话，**必须**与产物聚成一簇——这只有产物带嵌入才做得到。
    """
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    _patchEngine(monkeypatch, VECTOR)  # 恒等向量 ⇒ 余弦 1.0，准入只由内容门（normalized containment）决定
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="发布推迟到周四", id="s1")
    manager.remember(content="发布推迟到周四，已复核", id="s2")

    sleep = SleepConsolidation(similarity_threshold=0.7, memory_manager=manager)
    first = sleep.start_sleep()
    sleep.wake()
    # `merged_count` 是簇数（单例簇也算），真合并的读数是写回的 `added`——只有 ≥2 来源才 remember()
    assert first["write_back"]["added"] == 1, "前置不成立：第一轮没把产物落库（读数 %s）" % first

    manager.reload_memories()
    products = [m for m in manager._memories.values() if (m.id or "").startswith("merged_")]
    assert products, "产物行没被装回来"
    product = products[0]
    assert product.embedding == VECTOR, (
        "固化产物行的 embedding 为空 ⇒ 按甲3「任一侧无嵌入不合」，它下一轮谁也合不上"
    )

    manager.remember(content="发布推迟到周四，已复核并同步给测试", id="s3")
    second = sleep.start_sleep()
    sleep.wake()
    assert second["write_back"]["added"] == 1, (
        "产物没被下一轮吸收（读数 %s）⇒ 固化只收拢「回填过的老行」，对新写入永久失明"
        % (second,)
    )
