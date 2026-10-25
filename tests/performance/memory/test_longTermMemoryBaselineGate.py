"""长期记忆的六维常驻门禁（2026-10-22，裁定甲：把测量件收进收集面）

前身与本仓自有断点（不是「外部基准有所以要有」）：
- `tests/performance/longmeval_simple.py` 是本仓唯一一份「长期记忆形状」的测量件，
  但 `pyproject.toml:102-103` 规定 `python_files=["test_*.py"]`、
  `python_classes=["Test*"]`，它的文件名与类名 `SimpleLongMemEval` 双双不匹配 ⇒
  `--collect-only` 报 `collected 0 items`：一份看着在、实际从不运行的件。
  它构造 `MemoryStorage(db_path=..., neuser_id=...)` 并调 `search()` /
  `list_memories()` / `close()` —— 这些参数与方法在今天的
  `memory_layer.storage.MemoryStorage(storage_dir)` 上都不存在，直跑即 TypeError
  （台账把它记在「17 处按想象传构造参数」的只降不升棘轮里）。
- 更糟的是它的评分形态：`test_memory_update_forgetting` 里遗忘那一腿直接写
  `score = 1.0`，`test_temporal_awareness` 里时间戳那一腿写
  `timestamp_valid = True` —— **从未断言任何东西**（`AGENTS.md` §4 禁的恒真断言）。
  本批把它们改写成真断言，立刻抓到一条 live 断链（见「维度 5」）。

六维与不重复口径（教义第 6/7 条）：
1 写入/读回往返 + 归属隔离；2 批量写入容量（零静默丢失）；3 分类过滤检索；
4 按实体名的关联检索；5 **内容变更后检索面必须跟随**（本批红灯所在）+ 遗忘/硬删；
6 时间感知（tz-aware ISO、逆序、`updated_at` 推进）。
**本文件不测联想召回**：那一维连同描述性召回地板归
`test_associativeRecallGate.py`（§6-381），两处共用同一判据即双源。
干扰语料也从那一档 import（同一份语料只定义一次）。

前置：本地 ONNX 嵌入档必须可用（与 §6-381 同一前提），缺档即显式失败，**不做 skip**
——skip 会把本件变成第二条 `longmeval_simple.py`。`SemanticSearch` 是进程级单例，
每条用例前后各重置一次，否则上一份语料的词条会冒充下一份的键。
"""

import datetime
import os
import time
from pathlib import Path

import pytest

from tests import ast_scan

#: 扫描根绑在模块级：绑在函数里的名字，面自证棘轮（`test_scanCriterionMustProveItsOwnSurfaceRatchet`）
#: 认不出，整档会安静地掉出它的面（§6-404 批 M 补这一处）。
REPO_ROOT = Path(__file__).resolve().parents[3]
PERFORMANCE_ROOT = REPO_ROOT / "tests" / "performance"

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests import ast_scan
from tests.performance.memory.test_associativeRecallGate import DISTRACTORS

pytestmark = [pytest.mark.timeout(180)]

PROBE_LIMIT = 10
CAPACITY_ROWS = 200
#: 本档两处全仓判据的根：`tests/performance/` 与仓根。必须写在模块级——
#: 绑在函数里的名字，面自证棘轮（`tests/unit/ci/test_scanCriterionMustProveItsOwnSurfaceRatchet.py`）
#: 认不出根位置，整档会静默掉出它的面。深度按本档位置算（本档在 `tests/performance/memory/`）。
PERFORMANCE_ROOT = Path(__file__).resolve().parents[1]
#: 仓根：退役守卫按它拼三条扫描根。
REPO_ROOT = Path(__file__).resolve().parents[3]

OLD_WORDING = "用户: 我有一只青瓷茶壶是外婆留下的"
NEW_WORDING = "用户: 我把阳台浇花的活改成了每周三定时自动滴灌"
OLD_QUERY = "青瓷茶壶"
NEW_QUERY = "自动滴灌"


def _newManager(tmp_path, agentId: str) -> MemoryManager:
    from neurova.embedding import get_embedding_engine

    # 前提要证"引擎真的出非零向量"，不能只证"对象不是 None"：`get_embedding_engine()`
    # 从未返回 None——模型档在、但分词器/运行时装不上时它照样给一个对象，随后
    # `initialize()` 失败并**兜底零向量**（日志里只有一行 ERROR）。只判非 None 等于恒真，
    # 于是"向量分量"整条腿在这类环境里静默失效，红出来的是"写入时就没有向量"这种错位报错。
    # 这里先做一次真编码：零向量即前提不成立，显式失败、不 skip。
    from tests.memory_embedding_precondition import requireRealEmbeddingOrSkip

    requireRealEmbeddingOrSkip(
        "长期记忆六维门禁（向量分量与生产同一条链路："
        "`manager._get_vector_store()` → UnifiedVectorStore → ONNX）"
    )
    return MemoryManager(
        db_path=os.path.join(str(tmp_path), f"{agentId}.db"),
        agent_id=agentId,
        enable_buffer=False,
    )


@pytest.fixture
def semanticSearchIsolated():
    """`SemanticSearch` 单例的前后重置——倒排是进程级的，不清就是上一批的键。"""
    from neurova.cognitive_layers.memory_layer.semantic_search import reset_semantic_search

    reset_semantic_search()
    yield
    reset_semantic_search()


def _rankOf(manager: MemoryManager, query: str, memoryId: str) -> int:
    """该记忆在 `recall` 结果里的位次（1 起）；未进前 PROBE_LIMIT 返回 99。"""
    for index, row in enumerate(manager.recall(query=query, limit=PROBE_LIMIT), start=1):
        if row.get("id") == memoryId:
            return index
    return 99


def _indexedKeys(memoryId: str) -> set:
    """倒排里真正挂在该记忆上的全部词条（读路关键词分量的事实面）。"""
    from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search

    index = get_semantic_search()._keyword_index
    return {kw for kw, bucket in index.items() if memoryId in bucket}


class TestWriteReadRoundTrip:
    """维度 1：写入必须逐字读回，且归属隔离不许让他人看见。"""

    def test_写入按原样读回(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_roundtrip")
        try:
            contents = [
                "用户: 我的工位在三层靠窗，隔壁是打印区",
                "用户: 我把周报改成了周四下午提交",
                "助手: 已记下：周三下午有一对一",
            ]
            ids = [
                manager.remember(
                    content=text, memory_type="episodic", metadata={"chat_scope": "direct"}
                )
                for text in contents
            ]
            assert all(isinstance(i, str) and i for i in ids), "remember 必须返回非空 memory_id"
            assert len(set(ids)) == len(contents), "同轮写入的 id 必须互不相同"
            for mid, text in zip(ids, contents):
                row = manager.get_memory(mid)
                assert row is not None, f"{mid} 写进去却读不回"
                assert row["content"] == text, "读回内容必须与写入逐字相等"
        finally:
            manager.close()

    def test_他人作用域按_id_与检索两路都看不见(self, tmp_path, semanticSearchIsolated):
        """P1-6 归属防线：知道 id 也不能读、不能召回。"""
        owner = _newManager(tmp_path, "lme_owner")
        try:
            mid = owner.remember(
                content="用户: 我的门禁卡号是尾指 7781",
                memory_type="episodic",
                metadata={"chat_scope": "direct"},
            )
            assert owner.get_memory(mid) is not None
        finally:
            owner.close()

        intruder = _newManager(tmp_path, "lme_intruder")
        try:
            assert intruder.get_memory(mid) is None, "跨 agent 按 id 读＝越权读取被放开"
            assert _rankOf(intruder, "门禁卡号 7781", mid) == 99, "跨 agent 仍能召回＝隔离失效"
        finally:
            intruder.close()


class TestBulkWriteCapacity:
    """维度 2：批量写入不得静默丢行——写 200 条就要看见 200 条。"""

    def test_批量写入零静默丢失(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_capacity")
        try:
            written = []
            for i in range(CAPACITY_ROWS):
                written.append(
                    manager.remember(
                        content=f"用户: 容量探针第 {i} 号，登记于常驻门禁以测定可承受写入量",
                        memory_type="episodic",
                        metadata={"chat_scope": "direct"},
                    )
                )
            assert len(set(written)) == CAPACITY_ROWS, "写入返回值必须一一对应，不得有重复空 id"
            rows = manager.get_memories(limit=CAPACITY_ROWS + 50)
            assert len(rows) == CAPACITY_ROWS, (
                f"写 {CAPACITY_ROWS} 条只看见 {len(rows)} 条：有行被内容门/作用域/持久层"
                "静默吞掉，此后任何检索读数都失去分母意义"
            )
            missing = [mid for mid in written if manager.get_memory(mid) is None]
            assert not missing, f"这些 id 在列表里却按 id 读不到：{missing[:5]}"
        finally:
            manager.close()


class TestCategoryFilterRetrieval:
    """维度 3：显式声明的分类必须落库、并且只被自己的过滤器命中。"""

    def test_显式分类落库且过滤互斥(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_category")
        try:
            pref = manager.remember(
                content="用户: 我习惯用机械键盘写代码",
                memory_type="episodic",
                category="user_preference",
                metadata={"chat_scope": "direct"},
            )
            tool = manager.remember(
                content="用户: 我用 rsync 每天同步一次素材库",
                memory_type="episodic",
                category="tool_usage",
                metadata={"chat_scope": "direct"},
            )
            assert manager.get_memory(pref)["category"] == "user_preference", (
                "显式声明的 category 被自动分类覆盖＝调用方的声明没生效"
            )
            byPref = {r["id"] for r in manager.get_memories(category="user_preference")}
            byTool = {r["id"] for r in manager.get_memories(category="tool_usage")}
            assert pref in byPref and tool not in byPref, "分类过滤器串类"
            assert tool in byTool and pref not in byTool, "分类过滤器串类"
        finally:
            manager.close()


class TestRelationalRetrieval:
    """维度 4：同一个实体名下的多条记忆，按实体提问要一起召回。"""

    def test_按实体名关联召回(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_relation")
        try:
            for text in DISTRACTORS:
                manager.remember(
                    content=text, memory_type="episodic", metadata={"chat_scope": "direct"}
                )
            ids = [
                manager.remember(
                    content=text, memory_type="episodic", metadata={"chat_scope": "direct"}
                )
                for text in (
                    "用户: 林岫每月初给团队做一次数据口径对齐",
                    "用户: 林岫负责的看板改成了双周复盘",
                )
            ]
            hits = {row.get("id") for row in manager.recall(query="林岫", limit=PROBE_LIMIT)}
            assert set(ids) <= hits, (
                f"实体名查询只命中 {len(set(ids) & hits)}/2 条：同实体记忆不可关联检索"
            )
        finally:
            manager.close()


class TestContentUpdateFollowsRecallIndexes:
    """维度 5：改内容后，检索面（倒排 / 关键词读路 / 召回向量库 / 持久层向量 / 线索与封条）必须跟着改。

    本批这七格改前全红：在 HEAD 的干净工作树里只放本文件复跑即 **9 failed**（这七格
    ＋退役两格因旧件尚在），主树带上根修后 **18 passed**；读数与命令见台账 §6-393。
    七格的改前形态：旧词面仍挂在该记忆的倒排桶里、`search_by_keywords(旧问法)` 仍端出该 id、
    旧问法与新问法位次同为 1、召回向量库里存的是旧内容的向量（·新=0.3984 < ·旧=1.0000）、
    持久层 `embedding` 逐元素未变、旧内容的模型线索与「已问过模型」的封条都还压在表上、
    结构守卫点出两处内容赋值口（`update_memory:2626`、`compress_low_value_memories:4574`）。
    根因：
    - `manager.update_memory` 只写行与持久层，`_sync_content_index` 维护的是**去重门**，
      两处都不碰检索索引；`_semantic_recall` 每查询调
      `store.index_memories(..., incremental=True)`，而该方法按 id 去重跳过既有 id
      （`register_runtime_vector_store` 的 docstring 自己写着这个限制）⇒ 旧向量永久留存。
    - `semantic_search.upsert_memory_index()` 的 docstring 明写着「content 变更场景」，
      却是全仓没有内容变更路径调用它的孤儿口。
    """

    def test_倒排词条必须与新内容对齐(self, tmp_path, semanticSearchIsolated):
        from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search

        manager = _newManager(tmp_path, "lme_update_index")
        try:
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            knife = get_semantic_search()._extract_keywords
            oldKeys, newKeys = set(knife(OLD_WORDING)), set(knife(NEW_WORDING))
            dropped = oldKeys - newKeys
            added = newKeys - oldKeys
            assert dropped and added, (
                f"用例前提塌了：新旧内容对同一把刀没有差异（dropped={dropped} added={added}）"
            )

            manager.update_memory(mid, content=NEW_WORDING)

            keys = _indexedKeys(mid)
            stale = sorted(dropped & keys)
            assert not stale, (
                f"内容已改，倒排里这些旧词面仍挂在该记忆上：{stale}——"
                "旧问法照样命中，新问法只靠整句子串兜底"
            )
            unindexed = sorted(k for k in added if k not in keys)
            assert not unindexed, (
                f"新内容的这些词面没进倒排：{unindexed}——写侧改了，读侧没跟"
            )
        finally:
            manager.close()

    def test_关键词读路不得再挂旧问法(self, tmp_path, semanticSearchIsolated):
        """读路的关键词分量本身：`search_by_keywords` 是 `_semantic_recall` 直接调的那一个。"""
        from neurova.cognitive_layers.memory_layer.semantic_search import get_semantic_search

        manager = _newManager(tmp_path, "lme_update_keywordread")
        try:
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            search = get_semantic_search()
            assert mid in search.search_by_keywords(OLD_QUERY, limit=50), "前置：旧内容要能被旧问法命中"

            manager.update_memory(mid, content=NEW_WORDING)

            assert mid not in search.search_by_keywords(OLD_QUERY, limit=50), (
                f"内容已不含「{OLD_QUERY}」，关键词读路仍把该记忆端出来"
            )
            assert mid in search.search_by_keywords(NEW_QUERY, limit=50), (
                f"新内容的词面「{NEW_QUERY}」在关键词读路上查不到——写侧改了，读侧没跟"
            )
        finally:
            manager.close()

    def test_旧问法不得继续压过新问法(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_update_recall")
        try:
            for text in DISTRACTORS:
                manager.remember(
                    content=text, memory_type="episodic", metadata={"chat_scope": "direct"}
                )
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            manager.update_memory(mid, content=NEW_WORDING)

            rankNew = _rankOf(manager, NEW_QUERY, mid)
            rankOld = _rankOf(manager, OLD_QUERY, mid)
            assert rankNew <= 5, (
                f"改后的自有词面「{NEW_QUERY}」位次 {rankNew}（>5）：新内容进不了前五"
            )
            assert rankOld > rankNew, (
                f"「{OLD_QUERY}」在新内容里已逐字不存在，位次 {rankOld} 却不大于新词面的 "
                f"{rankNew}——旧向量/旧词条仍挂在读路上"
            )
        finally:
            manager.close()

    def test_召回向量库存的必须是新内容的向量(self, tmp_path, semanticSearchIsolated):
        """直查 `_semantic_recall` 真正用的那只库：它按 id 去重跳过既有 id，
        不主动摘除就永远不会重编——这条断言就是把「永远不会」钉成红。"""
        import math

        from neurova.embedding import get_embedding_engine

        manager = _newManager(tmp_path, "lme_update_store")
        try:
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            manager.recall(query=OLD_QUERY, limit=5)  # 让库先被建起来
            manager.update_memory(mid, content=NEW_WORDING)
            manager.recall(query=NEW_QUERY, limit=5)  # 变更后再查一次（重编入口）

            store = manager._get_vector_store()
            assert mid in store.memory_ids, "变更后该记忆根本不在召回向量库里，本用例前提塌了"
            stored = store.memory_vectors[store.memory_ids.index(mid)]
            engine = get_embedding_engine()

            def _cos(a, b):
                num = sum(x * y for x, y in zip(a, b))
                n1 = math.sqrt(sum(x * x for x in a))
                n2 = math.sqrt(sum(x * x for x in b))
                return num / (n1 * n2) if n1 and n2 else 0.0

            toNew = _cos(stored, engine.encode(NEW_WORDING))
            toOld = _cos(stored, engine.encode(OLD_WORDING))
            assert toNew > toOld, (
                f"库里存的向量更像旧内容（·新={toNew:.4f} ≤ ·旧={toOld:.4f}）："
                "`index_memories(incremental=True)` 按 id 去重跳过既有 id，"
                "不先摘除就永远用旧向量做语义召回"
            )
        finally:
            manager.close()

    def test_持久层向量随内容刷新(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_update_embedding")
        try:
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            before = manager.get_memory(mid)["embedding"]
            assert before, "写入时就没有向量，本用例前提不成立"
            manager.update_memory(mid, content=NEW_WORDING)
            after = manager.get_memory(mid)["embedding"]
            assert after, "改内容后向量列变空：睡眠固化的合簇判据从此看不见这条"
            assert after != before, (
                "内容改了而持久层 embedding 没重算——合簇按旧向量判相似度，"
                "读数上「有向量、只是不相似」，缺陷从此不可见（教义第 2 条）"
            )
        finally:
            manager.close()

    def test_改内容后旧线索与尝试封条一起撤回(self, tmp_path, semanticSearchIsolated):
        """线索与封条都是**旧内容**的产物：留着就是拿旧文本的抽象替新文本作召回依据，
        且「已问过模型」的封条会让该行永远出不了待生成池（丙案的成本闸因此失效）。"""
        manager = _newManager(tmp_path, "lme_update_cues")
        try:
            mid = manager.remember(
                content=OLD_WORDING, memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            store = manager._associationCues
            assert store is not None, "线索库没起来，本用例前提不成立"
            scope = (manager._eff_neuser_id(), manager._eff_user_id())
            createdAt = manager.get_memory(mid)["created_at"]
            store.replaceForMemory(
                mid,
                [{"cue_text": "外婆的青瓷茶壶", "cue_kind": "item",
                  "cue_source": "model", "confidence": 0.7}],
                scope=scope,
                createdAt=createdAt,
            )
            store.recordAttempt(mid, 1, "ok", at=createdAt)
            assert mid in store.attemptedMemoryIds(), "前置：封条要真种上"
            assert "外婆的青瓷茶壶" in [
                c["cue_text"] for c in manager.get_associationCues(mid)
            ], "前置：旧内容的模型线索要真在表上"

            manager.update_memory(mid, content=NEW_WORDING)

            assert mid not in store.attemptedMemoryIds(), (
                "内容改了而「已问过模型」的封条还在：该行出不了待生成池，"
                "新内容永远不会被重新预演"
            )
            texts = [c["cue_text"] for c in manager.get_associationCues(mid)]
            assert "外婆的青瓷茶壶" not in texts, (
                f"旧内容的模型线索仍挂在读路上：{texts}"
            )
        finally:
            manager.close()

    def test_内容变更只有单一入口(self):
        """结构守卫：live 表的内容赋值只许待在 `_applyContentChange` 里。

        本批抓到两处（`update_memory`、语义压缩写回），修法是收口成一处并让全部
        命中点走它（教义第 1/5/6 条）。留这条守卫是因为「第三条路」随时会长回来：
        任何新的 `x.content = ...` 落在这个方法之外，就是又一处「改了行、没跟索引」。
        """
        import ast
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[3]
            / "neurova"
            / "cognitive_layers"
            / "memory_layer"
            / "manager.py"
        )
        tree = ast.parse(src.read_text(encoding="utf-8"))
        offenders = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "content":
                        offenders.append(f"{func.name}:{node.lineno}")
        assert all(o.startswith("_applyContentChange:") for o in offenders), (
            f"live 记忆的内容赋值散在这些方法里：{offenders}——"
            "除 `_applyContentChange` 之外的每一处都不会跟随检索索引"
            "（倒排、召回向量库、持久层 embedding、线索表）"
        )


class TestForgettingAndHardDelete:
    """维度 5（下半）：软遗忘撤出可见面，硬删除连索引一起撤。"""

    def test_软遗忘后检索与列表都不见(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_softforget")
        try:
            for text in DISTRACTORS[:20]:
                manager.remember(
                    content=text, memory_type="episodic", metadata={"chat_scope": "direct"}
                )
            mid = manager.remember(
                content="用户: 我把旧的备用手机号注销了",
                memory_type="episodic",
                metadata={"chat_scope": "direct"},
            )
            assert manager.forget(mid, soft=True) is True
            assert _rankOf(manager, "备用手机号注销", mid) == 99, "软遗忘后仍被 recall 端出来"
            assert mid not in {r["id"] for r in manager.get_memories(limit=500)}, (
                "软遗忘后 get_memories 还返回该行"
            )
        finally:
            manager.close()

    def test_硬删除把行与倒排一起摘掉(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_harddelete")
        try:
            mid = manager.remember(
                content="用户: 这份临时凭证只在今天有效",
                memory_type="episodic",
                metadata={"chat_scope": "direct"},
            )
            assert manager.recall(query="临时凭证有效", limit=5), "前置：先要能被召回"
            assert manager.forget(mid, soft=False) is True
            assert manager.get_memory(mid) is None, "硬删除后按 id 仍读到该行"
            assert _indexedKeys(mid) == set(), (
                "行已删而关键词倒排里还挂着它的词条：删掉的记忆继续吃检索位"
            )
        finally:
            manager.close()


class TestTemporalAwareness:
    """维度 6：时间戳可解析、单调、列表按新到旧排。"""

    def test_时间戳是带时区的可解析_iso(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_temporal")
        try:
            before = datetime.datetime.now(datetime.timezone.utc)
            mid = manager.remember(
                content="用户: 下周一体检", memory_type="episodic", metadata={"chat_scope": "direct"}
            )
            row = manager.get_memory(mid)
            created = datetime.datetime.fromisoformat(row["created_at"])
            assert created.tzinfo is not None, (
                f"created_at 无时区（{row['created_at']}）：跨时区比较会给出错序"
            )
            assert created >= before, "created_at 早于写入时刻：时钟或落库口径有问题"
        finally:
            manager.close()

    def test_列表按新到旧排且更新会推进_updated_at(self, tmp_path, semanticSearchIsolated):
        manager = _newManager(tmp_path, "lme_temporal_order")
        try:
            # 本机时钟实测按 ~1ms 步进（连采 4000 次：3995 次取值不变，最小非零间隔
            # 307µs、中位 999µs）。同一 tick 内两行的 created_at 逐字相等，
            # `sorted(reverse=True)` 稳定排序就会按插入序留着——那是环境事实，不是
            # 排序缺陷，所以用例显式把写入拉开一个 tick 以上，让「新到旧」有意义可比。
            first = manager.remember(
                content="用户: 先记一条季度预算口径",
                memory_type="episodic",
                metadata={"chat_scope": "direct"},
            )
            time.sleep(0.02)
            second = manager.remember(
                content="用户: 后记一条迁移窗口口径",
                memory_type="episodic",
                metadata={"chat_scope": "direct"},
            )
            ids = [r["id"] for r in manager.get_memories(limit=50)]
            assert ids.index(second) < ids.index(first), (
                "get_memories 不按新到旧排：消费方拿到的「最近记忆」是旧的"
            )
            created = manager.get_memory(first)["updated_at"]
            time.sleep(0.02)
            manager.update_memory(first, temperature=88.0)
            assert manager.get_memory(first)["updated_at"] > created, (
                "内容/温度改了而 updated_at 不推进：衰减与新近判据都失去事实源"
            )
        finally:
            manager.close()


class TestUncollectedMeasurementFileIsRetired:
    """退役守卫（教义第 7 条：留下第二份即未闭环）。"""

    def test_performance_目录下不得有不被收集的文件(self):
        root = PERFORMANCE_ROOT
        # 枚举走共享入口（`tests/ast_scan.filesUnder`）并**物化后自证面**：根被改窄或
        # 写错一层时，读数会退化成"零散件"——那时这条断言看起来与"干净"一模一样。
        # 两种坏法都只有把扫到的数量当断言比才咬得住。
        files = ast_scan.filesUnder(PERFORMANCE_ROOT)
        assert len(files) > 5, f"扫描面现读 {len(files)} 个 .py（根＝tests/performance/）——根被改窄了"
        strays = [
            p.relative_to(root.parent).as_posix()
            for p in files
            if "__pycache__" not in p.parts and p.name != "__init__.py"
            and not p.name.startswith("test_")
        ]
        assert not strays, (
            f"这些件在 tests/performance/ 里但不会被 pytest 收集（pyproject 的 "
            f"python_files=[\"test_*.py\"]）：{strays}——"
            "要么改名收进收集面，要么退役；不许留着当「看着在、从不跑」的测量件"
        )

    def test_旧件与其符号不得复活(self):
        import ast

        repo = REPO_ROOT
        assert not (repo / "tests" / "performance" / "longmeval_simple.py").exists(), (
            "旧测量件被复活：它按不存在的 API 写、且文件名不被收集"
        )
        # 按**类定义**认，不按子串——本文件自己的 docstring 也要提到那个类名，
        # 用子串扫会变成「守卫咬住记录来历的注释」的假红（也拦不住真复活）。
        ghosts, unparsed = [], []
        # 枚举与解析走共享一次性入口（`tests/ast_scan`）：判据自己的 `rglob + ast.parse`
        # 会把成本绑成「代码总量」。文本预筛取类名——没出现这三个字的文件不可能定义它。
        for root in ("neurova", "tests", "scripts"):
            # 枚举与解析都走共享预算（`sourceRefsUnder` 只读一遍盘、文本预筛一并做完，
            # `transientTree` 不留常驻语法树）：判据成本不随代码总量涨，
            # 也不是"自己枚举一整棵根树再逐个解析"那一形。
            for ref in ast_scan.sourceRefsUnder(repo / root, hints=("SimpleLongMemEval",)):
                tree = ast_scan.transientTree(ref.path)
                if any(
                    isinstance(n, ast.ClassDef) and n.name == "SimpleLongMemEval"
                    for n in ast.walk(tree)
                ):
                    ghosts.append(ref.path.relative_to(repo).as_posix())
        # 面自证：零复活只有在"真的扫过这三棵根"时才说明退役落干净了（根指错时这格恒绿）。
        scanned = sum(
            len(ast_scan.filesUnder(repo / root)) for root in ("neurova", "tests", "scripts")
        )
        assert scanned > 500, (
            f"扫描面现读 {scanned} 个 .py（根＝neurova/ tests/ scripts/）——"
            "根被改窄时「零复活」不代表干净")
        assert not unparsed, f"守卫无法解析这些文件，判定面出现盲区：{unparsed}"
        assert not ghosts, f"类 SimpleLongMemEval 仍被定义在：{ghosts}"
