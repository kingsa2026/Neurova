"""规则联想线索（TM-2a）的写入侧与检索侧行为判据 —— 批 A 红灯集

根因（本仓自有断点，档案见 `docs/04-plans/联想线索落地工单_2026-10-21.md`）：
记忆检索的可达性完全由「词面 + 嵌入近邻」两路决定——`manager.py:2098-2101` 的关键词路是
整句查询子串匹配，`semantic_search.py:224` 的倒排只从 `content` 抽词，`_embeddingForNewRow`
（`manager.py:1317/1347`）把 `content` 原文喂编码器。于是与记忆**无共同词面**却实质相关的提问
没有第二条访问路径。TM-1 实测（`8d372ca2`/§6-381）：联想子集 hit@1=2/10、hit@5=6/10、MRR=0.35。

本批做法：写入时从**本仓既有规则面**（多标签类别上位 + CJK 关键词面 + 已抽实体）派生若干
「只参与检索、永不进提示」的联想线索，落 `memory_cues` 表并把线索词条并入同一份关键词倒排的
**同一个 memory_id 桶**。零模型调用、不动排序公式、不做级联替换。

命名纪律：本仓不叫 trigger——`explainability.py` 的死 trigger-chain 与 `schema.py` 的死
`trigger_chains` 表已在册，复用该词即造第二份口径（本批同批净删那份死 DDL）。
"""

import ast
import inspect
import io
import os
import re

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from tests.ast_scan import parseSource

pytestmark = [pytest.mark.timeout(60)]

# 生产根按 __file__ 反推（不写死盘符+项目名：常驻守卫 TestNoHardcodedDevMachinePaths
# 逐行扫 tests/**/*.py，注释里的复现命令也算）
_TESTS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRODUCTION_ROOT = os.path.join(os.path.dirname(_TESTS_ROOT), "neurova")

# 与目标记忆**零中文字面重合**的一条：今天无论词法还是稠密路都打不中（TM-1 ranks 里那条 99）
TARGET = "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏"
DISJOINT_QUERY = "团队聚餐选餐厅时要注意什么"

_CUE_KINDS = {"hypernym", "situation", "foresight"}


@pytest.fixture
def manager(tmp_path):
    mgr = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"),
        agent_id="cue_batch_a",
        enable_buffer=False,
    )
    yield mgr
    mgr.close()


def _writeCorpus(mgr: MemoryManager) -> str:
    """落 66 行干扰项 + 目标行。干扰集**复用 TM-1 判据集那一份**（单一事实源），
    不在这里另抄一套——抄了就会漂移，两边读数也就失去可比性。

    没有干扰项时「命中」是白给的：本批第一版用 12 行语料配 limit=12，
    等于把全库交回来，那条断言恒真（被活体反证当场抓到）。
    """
    from tests.performance.memory.test_associativeRecallGate import DISTRACTORS

    for text in DISTRACTORS:
        mgr.remember(content=text, memory_type="episodic", metadata={"chat_scope": "direct"})
    return mgr.remember(content=TARGET, memory_type="episodic", metadata={"chat_scope": "direct"})


class TestRuleCuesAreWrittenAndPersisted:
    def test_写入记忆即长出规则线索(self, manager):
        memoryId = _writeCorpus(manager)

        cues = manager.get_associationCues(memoryId)
        assert cues, "规则联想线索未随写入派生——写侧仍只有 content 一条访问路"
        for cue in cues:
            assert cue["cue_kind"] in _CUE_KINDS, f"线索种类越出闭集: {cue['cue_kind']}"
            assert cue["cue_source"] == "rule", "本批只许零成本规则派生，模型生成属批 C"
            assert cue["cue_text"].strip(), "空线索进倒排只会污染评分"

    def test_线索落库并走迁移注册表(self, manager):
        """线索必须长在既有 per-agent 记忆库里，经 register_migration 加版本——
        不新建第六个存储，也不写 `IF NOT EXISTS` 就完事（AGENTS.md §3 SQLite 条）。"""
        import sqlite3

        from neurova.cognitive_layers.memory_layer.persist_landing import persistCompanionPath

        # `memories` 与它的迁移都长在**同目录 persist 伴生库**（实测：主库只有
        # memory_emotions 且 user_version=0）。判据若量主库，量的就不是生产那张表。
        dbPath = str(persistCompanionPath(manager._db_path))
        columns = set()
        with sqlite3.connect(dbPath) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if any(row[0] == "memory_cues" for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")):
                columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_cues)")}

        assert version >= 4, f"memory 域 schema 版本仍为 {version}，迁移步骤没注册或未跑"
        assert {"cue_id", "memory_id", "cue_text", "cue_kind", "cue_source", "norm_key"} <= columns, (
            f"memory_cues 列不全，实有 {sorted(columns)}"
        )

    def test_重复派生不涨表(self, manager):
        """同一行同一线索不得二次入库——否则线索表随写入次数无界增长，
        而它没有任何清理消费方（AGENTS.md §2「只写不读」同形）。"""
        memoryId = _writeCorpus(manager)
        first = len(manager.get_associationCues(memoryId))
        assert first > 0, "前提不成立：一条线索都没派生出来"

        manager.refresh_associationCues(memoryId)
        second = len(manager.get_associationCues(memoryId))
        assert second == first, f"重派生使线索数由 {first} 涨到 {second}，去重键没咬住"


class TestCuesOpenTheSecondAccessPath:
    def test_线索词面可被查询经同一倒排命中(self, manager):
        """机制判据（批 A 交付的就是这个），写成**差分**形态。

        第一版这里是「查一次看它在不在结果里」——13 行语料配 limit=12 等于把全库交回来，
        那条断言白给（被活体反证当场抓到）。正确形态是同一份查询在「带线索」与
        「摘掉线索」两种索引状态下做差：
        ① 词法面（机制层，硬判据）：只在线索里出现的词，必须能把这条记忆捞进 `search_by_keywords`，
           摘掉线索后必须捞不到；
        ② 端到端（能力层）：66 行真实竞争下按 limit=5 取名次，带线索的名次必须不劣于摘掉线索。
        """
        from neurova.cognitive_layers.memory_layer.semantic_search import (
            get_semantic_search,
        )

        memoryId = _writeCorpus(manager)
        cueTexts = [c["cue_text"] for c in manager.get_associationCues(memoryId)]
        assert cueTexts, "前提不成立：没有线索"

        # 探针必须用**索引实际那把刀**选词。第一版用了本模块自带的 cueTokens，
        # 与 `_extract_keywords` 切法不同，于是造出一条两边都不认的查询——
        # 「写侧按一套词切、读侧按另一套词查」正是本批要防的第二条断链，
        # 判据自己犯了就当场红（这一次它红了）。
        search = get_semantic_search()
        contentKeywords = set(search._extract_keywords(TARGET))
        cueOnly = sorted(
            {
                kw
                for text in cueTexts
                for kw in search._extract_keywords(text)
                if kw not in contentKeywords
            }
        )
        assert cueOnly, f"线索词面全是正文已有的词，测不到新增可达性；线索={cueTexts}"
        # 查询取**线索原文**（而非某个切片词）：索引侧与查询侧都把同一串过同一把刀，
        # 词面重合是构造出来的必然，不用去猜切法边界
        probe = next(text for text in cueTexts if set(search._extract_keywords(text)) - contentKeywords)
        query = probe

        withCues = memoryId in search.search_by_keywords(query, limit=1000)
        assert withCues, (
            f"仅存在于线索里的词「{probe}」没能把该记忆捞进倒排；线索={cueTexts}"
        )

        # 摘掉线索词（退回旧索引形态），同一条查询必须捞不到——证 withCues 不是白给的
        search.remove_memory_index(memoryId)
        search.upsert_memory_index({"id": memoryId, "content": TARGET})
        withoutCues = memoryId in search.search_by_keywords(query, limit=1000)
        assert not withoutCues, (
            f"摘掉线索词后「{probe}」仍能捞到该记忆——说明这条可达性本来就有，"
            "本判据没咬住线索这一层"
        )

        # 复原（含线索），再做端到端名次差分：带线索的名次不得劣于摘掉线索
        def _rank() -> int:
            for index, row in enumerate(manager.recall(query=query, limit=5), start=1):
                if row.get("id", "") == memoryId:
                    return index
            return 99

        search.remove_memory_index(memoryId)
        search.upsert_memory_index({"id": memoryId, "content": TARGET})
        rankNoCue = _rank()
        search.remove_memory_index(memoryId)
        search.upsert_memory_index({"id": memoryId, "content": TARGET}, cues=cueTexts)
        rankWithCue = _rank()
        assert rankWithCue <= rankNoCue, (
            f"带线索的名次 {rankWithCue} 劣于摘掉线索的 {rankNoCue}——"
            "线索并进同一份倒排后不该让原顺序变差"
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "批 A 的诚实边界：规则线索的内容只来自行上已有的结构化标签（类型/类别/情感的中文上位名），"
            "它抬不动「团队聚餐选餐厅要注意什么」这类需要**具体情境推断**的零词面查询——"
            "这类内容由批 C（用户裁丙：空闲窗口内模型生成、不设调用上限、段落级全量）承担。"
            "批 C 落地后本条以 XPASS 变红 ⇒ 摘标记并把读数抬进 TM-1 棘轮基线。"
        ),
    )
    def test_零词面情境查询经线索命中(self, manager):
        memoryId = _writeCorpus(manager)
        targetChars = {ch for ch in TARGET if "\u4e00" <= ch <= "\u9fff"}
        queryChars = {ch for ch in DISJOINT_QUERY if "\u4e00" <= ch <= "\u9fff"}
        assert not (targetChars & queryChars), "用例前提失效：这条查询与记忆已有共同字面"

        hits = manager.recall(query=DISJOINT_QUERY, limit=5)
        assert memoryId in [h.get("id", "") for h in hits], (
            f"「{DISJOINT_QUERY}」未能召回「{TARGET}」"
        )

    def test_线索只加候选不改排序公式(self, manager):
        """RRF 权重与 origin 信任是既有单源（manager.py:2104-2115），本批不得为线索另立打分口径。"""
        src = inspect.getsource(MemoryManager._semantic_recall)
        assert "0.7 / (60" in src and "0.3 / (60" in src, (
            "既有 RRF 融合权重被改动——线索应只并候选，不该动排序公式"
        )
        assert "origin_weights" in src, "origin 信任权重不得被线索通道绕过"


class TestCuesNeverBecomeEvidence:
    def test_渲染面不得出现线索文本(self, manager):
        """「访问路径 ≠ 证据」今天只是巧合：injector 每行只渲染 content（:604）。
        本判据把巧合钉成契约，防后人把线索当摘要塞进提示。"""
        from neurova.context.injector import UnifiedContextInjector

        memoryId = _writeCorpus(manager)
        cueTexts = [c["cue_text"] for c in manager.get_associationCues(memoryId)]
        assert cueTexts, "前提不成立：无线索可验"

        injector = UnifiedContextInjector(memory_manager=manager)
        rendered = injector._build_memory_context(
            manager.get_memories(limit=50), user_input=DISJOINT_QUERY
        )
        for cueText in cueTexts:
            assert cueText not in rendered, f"线索文本「{cueText}」泄漏进提示——它只参与检索"

    def test_跨作用域不得互见线索(self, manager):
        """线索三元组必须与主表一致（§6-163 身份单源裁定）：未绑定身份不得读到别人的线索。"""
        memoryId = _writeCorpus(manager)
        assert manager.get_associationCues(memoryId), "前提不成立：本作用域无线索"

        manager.set_request_scope("other_neuser", "other_user")
        try:
            assert manager.get_associationCues(memoryId) == [], (
                "换到他人作用域仍读到原属主的线索——线索表少了作用域这一道门"
            )
        finally:
            manager.clear_request_scope()
        assert manager.get_associationCues(memoryId), "归还作用域后线索应重新可见（门是隔离不是删除）"


class TestRuleDerivationIsModelFree:
    def test_全量重建必须带线索图(self):
        """`build_keyword_index` 是 clear+全量重建。调用点若不带线索图，就会出
        「增量认线索、全量丢线索」的第二条陈旧路径——索引在某次重建后静默退化，
        而写入侧一切正常。按 AST 钉两处调用点的实参个数，不匹配散文字。"""
        roots = [
            os.path.join(PRODUCTION_ROOT, "cognitive_layers", "memory_layer", "manager.py"),
            os.path.join(
                PRODUCTION_ROOT, "cognitive_layers", "memory_layer", "neurova_recall.py"
            ),
        ]
        offenders = []
        for path in roots:
            tree = parseSource(io.open(path, encoding="utf-8").read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "build_keyword_index"):
                    continue
                if len(node.args) + len(node.keywords) < 2:
                    offenders.append(f"{os.path.basename(path)}:{node.lineno}")
        assert not offenders, (
            f"全量重建调用点没带线索图（第二条陈旧路径）：{offenders}"
        )

    def test_派生路径不引用模型客户端(self):
        """批 A 的立身之处是零成本：派生器里出现任何 LLM 调用点即红（本仓写侧 $0 纪律，
        `moe_dependency_extractor.py:1-4` 明写）。按 AST 取调用形态，不匹配散文字。"""
        from neurova.cognitive_layers.memory_layer import association_cues

        tree = parseSource(inspect.getsource(association_cues))
        banned = re.compile(r"(llm|client|generate|complete|chat_completion)", re.I)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and banned.search(node.attr):
                offenders.append(f"line {node.lineno}: .{node.attr}")
            elif isinstance(node, ast.Name) and banned.search(node.id) and isinstance(
                node.ctx, ast.Load
            ):
                offenders.append(f"line {node.lineno}: {node.id}")
        assert not offenders, f"规则线索派生里出现模型调用面：{offenders}"

    def test_派生是确定性的(self, manager):
        """同输入两次派生必须逐条相等——否则线索表不可重放，A/B 也测不出真实差集。

        按**写侧真实签名**调用（带行上的类型标签）。只喂正文不喂标签时多标签可能整片为空
        （实测 `classify_category_multi_label` 对本行返回 `[]`、单标签只落到 general），
        那种空是正确行为，但把它当判据前提就是「两边都空所以相等」的假绿。
        """
        once = manager.deriveRuleAssociationCues(TARGET, memoryType="episodic")
        twice = manager.deriveRuleAssociationCues(TARGET, memoryType="episodic")
        assert once, "带类型标签仍派生不出线索——词表没接上"
        assert once == twice, f"派生不稳定：{once} ↔ {twice}"

    def test_派生失败不得被fail_soft吞成静默(self, manager, caplog):
        """本批实测踩过一次真坑：INSERT 绑定参数少给一个，异常被 remember 的
        fail-soft 收成一行 warning——记忆照写、线索恒空、不盯日志就是假绿。
        判据双钉：既要有线索，也要没有线索告警。"""
        import logging

        with caplog.at_level(logging.WARNING):
            memoryId = _writeCorpus(manager)

        assert manager.get_associationCues(memoryId), "线索为空——派生被吞掉了"
        swallowed = [
            record.getMessage() for record in caplog.records if "联想线索" in record.getMessage()
        ]
        assert not swallowed, f"派生异常被 fail-soft 吞掉：{swallowed}"
