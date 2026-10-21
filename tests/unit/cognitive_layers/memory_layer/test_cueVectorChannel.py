"""联想线索**向量通道**（TM-2b/批 C-1）的行为判据 —— 先红

为什么是向量通道而不是词法通道（本会话实测否掉了批 A 那条词法消费的假设）：
词法那把刀是「连续中文按 2–4 字**非重叠**切片」（`semantic_search.py:113-119`），
两句不同的话切片几乎对不上——把「理想线索」灌进词法倒排后，TM-1 的联想读数
**一字未动**（ranks 逐位相同）。而外部那套触发器匹配走的是**余弦**，不是 BM25。
改为「每条线索一个向量、查询与线索算余弦、过门限后把 memory_id 并进候选」，
实测（同一 ONNX 档、同一 66 行干扰集）：

| 通道 | hit@1 | hit@5 | MRR |
|---|---|---|---|
| 现状（仅正文向量） | 2/10 | 6/10 | 0.381 |
| 盲写线索（真实生成器水位） | 3/10 | **10/10** | **0.567** |
| 理想线索（看着答案倒写，含泄漏） | 10/10 | 10/10 | 1.000 |

⇒ 验收线按**盲写**那一档定（10/10 是上限不是期望，不许当承诺）。
本文件里 `BLIND_CUES` 这份数据同时是批 C-2 生成器的**质量验收样本**：
生成器产出的线索至少要达到这组的水位，否则不值那张模型账单。
"""

import os

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

pytestmark = [pytest.mark.timeout(240)]

# 语料**复用 TM-1 判据集那一份**（单一事实源）。本文件第一版自造了 66 行干扰项，
# 且那些行彼此几乎同文——语料被出简单了，目标不靠通道也能排第 1，
# 「关掉通道读数不降」这条差分判据当场把它抓了出来（开=10/10 关=10/10）。
from tests.performance.memory.test_associativeRecallGate import TARGETS, DISTRACTORS  # noqa: E402


# 只看记忆那一行写出来的「这东西以后什么时候用得上」——不看任何查询（防答案泄漏）
BLIND_CUES = {
    "allergy": ["海鲜类食材", "外出就餐点菜", "就医与用药提醒", "饮食禁忌"],
    "review": ["月底的时间安排", "团队会议", "轮值与排班", "工作日程"],
    "kid": ["带孩子出门", "儿童活动安排", "送小孩的玩意儿", "周末怎么过"],
    "budget": ["资源扩容", "经费与审批", "采购计划", "成本核算"],
    "commute": ["早晨的时间表", "通勤路线", "约在几点见面", "上班路上"],
    "med": ["饮酒场合", "聚餐喝酒", "用药注意事项", "健康约束"],
    "dog": ["雷暴天气", "宠物安置", "出门前的交代", "狗的状态"],
    "anniv": ["生日礼物", "三月的日程", "园艺爱好", "纪念日安排"],
    "deploy": ["数据库变更", "上线时间安排", "周日凌晨窗口", "发布计划"],
    "diet": ["甜品选择", "饮料推荐", "饮食控制", "聚餐点餐"],
}

ACCEPTANCE = {"hit5": 9, "mrr": 0.50}


def _attachModelCues(mgr: MemoryManager, rows: dict) -> None:
    """把验收样本按批 C-2 生成器的**产物形态**写入同一张线索表（cue_source=model）。"""
    for key, (memoryId, text) in rows.items():
        mem = mgr._memories[memoryId]
        cues = [
            {
                "cue_text": cue,
                "cue_kind": "situation",
                "cue_source": "model",
                "confidence": 0.8,
                "norm_key": f"acceptance_{key}_{index}",
            }
            for index, cue in enumerate(BLIND_CUES[key])
        ]
        mgr._associationCues.replaceForMemory(
            memoryId, cues, scope=(mem.neuser_id, mem.user_id), createdAt=mem.created_at
        )


@pytest.fixture
def corpus(tmp_path):
    from neurova.embedding import get_embedding_engine

    assert get_embedding_engine() is not None, (
        "本判据测的是生产同款稠密检索，缺本地 ONNX 档时读数无意义"
        "（前提与 test_onnx_lazy_init_deadlock.py 一致，不以 skip 蒙过）"
    )
    # 单例复位必须在这里做：`get_semantic_search()` 是进程级单例，而记忆 id 是每个 fixture
    # 从 mem_000001 确定性重放的——上一个用例并进去的线索词会串到下一个用例的倒排里，
    # 「关掉通道读数不降」这条差分因此测的是残留状态而不是通道（本轮就这么翻过车）。
    from neurova.cognitive_layers.memory_layer.semantic_search import reset_semantic_search

    reset_semantic_search()
    mgr = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"), agent_id="cue_channel_c1", enable_buffer=False
    )
    for text in DISTRACTORS:
        mgr.remember(content=text, memory_type="episodic", metadata={"chat_scope": "direct"})
    rows = {}
    for key, text, _query in TARGETS:
        rows[key] = (
            mgr.remember(content=text, memory_type="episodic", metadata={"chat_scope": "direct"}),
            text,
        )
    yield mgr, rows
    mgr.close()
    reset_semantic_search()


def _rankOf(mgr: MemoryManager, targetText: str, limit: int = 5) -> int:
    """目标记忆在当前检索结果里的名次（按正文匹配；未进前 limit 记 99）。"""
    for index, row in enumerate(mgr.recall(query=targetText, limit=limit), start=1):
        if (row.get("content") or "") == targetText:
            return index
    return 99


def _rankForQuery(mgr: MemoryManager, query: str, targetText: str, limit: int = 5) -> int:
    """**用联想查询去搜**，按正文定位目标记忆的名次。

    这里曾错过一次：写成 `_rankOf(mgr, text)` 等于拿记忆正文当查询，量的是描述性召回
    （恒 10/10），而差分判据当场把「关掉通道读数不降」报了出来——那条判据值回票价。
    """
    for index, row in enumerate(mgr.recall(query=query, limit=limit), start=1):
        if (row.get("content") or "") == targetText:
            return index
    return 99


def _measure(mgr: MemoryManager, limit: int = 5) -> dict:
    ranks = [_rankForQuery(mgr, query, text, limit) for _key, text, query in TARGETS]
    hit1 = sum(1 for r in ranks if r <= 1)
    hit5 = sum(1 for r in ranks if r <= 5)
    mrr = sum(1.0 / r for r in ranks if r != 99) / len(ranks)
    return {"hit1": hit1, "hit5": hit5, "mrr": round(mrr, 3), "ranks": ranks}


class TestCueVectorChannelLiftsAssociativeRecall:
    """净增益用**配对比较**断言，不用绝对线。

    原因（本会话实测，不粉饰）：绝对读数受跑序影响——本文件单跑 hit@5=9/10，
    与批 A 的判据文件同进程跑时掉到 7/10，隔离模拟里不复现，根因尚未锁定
    （已登记待查）。同 fixture 内「开/关」两次相邻测量之差没有这个问题：
    它把外环境当作两边共同的加数消掉了，剩下的差只可能来自通道本身。
    """

    def test_盲写线索对同一语料有可归因的净增益(self, corpus, monkeypatch):
        mgr, rows = corpus
        before = _measure(mgr)
        onStats0 = mgr.associationCueChannelStats()

        _attachModelCues(mgr, rows)
        mgr.invalidateAssociationCueIndex()
        after = _measure(mgr)
        onStats = mgr.associationCueChannelStats()

        monkeypatch.setenv("NEUROVA_MEMORY_CUE_CHANNEL", "off")
        off = _measure(mgr)
        offStats = mgr.associationCueChannelStats()
        monkeypatch.delenv("NEUROVA_MEMORY_CUE_CHANNEL")

        print(
            f"[配对读数] 无线索={before['hit5']}/10 有线索={after['hit5']}/10 "
            f"关断={off['hit5']}/10｜MRR {before['mrr']}→{after['mrr']}（关断 {off['mrr']}）"
        )
        print(f"  有线索 ranks={after['ranks']}  关断 ranks={off['ranks']}")

        assert onStats.get("injected", 0) > onStats0.get("injected", 0), "挂线索后通道没注入过候选"
        assert offStats.get("skippedOff", 0) > onStats.get("skippedOff", 0), "关断没被通道读到"
        assert after["hit5"] > off["hit5"], (
            f"同一 fixture 内关掉通道读数不降（开 {after['hit5']} ↔ 关 {off['hit5']}）——"
            "净增益不可归因于通道"
        )
        assert after["mrr"] > off["mrr"], f"MRR 差分不成立：开 {after['mrr']} ↔ 关 {off['mrr']}"

    def test_描述性地板不得被线索挤掉(self, corpus):
        """线索只**加**分不**减**分：挂上线索后，正文原句查询的名次不得比挂之前差。"""
        mgr, rows = corpus
        before = {key: _rankOf(mgr, text) for key, (_mid, text) in rows.items()}
        _attachModelCues(mgr, rows)
        mgr.invalidateAssociationCueIndex()
        after = {key: _rankOf(mgr, text) for key, (_mid, text) in rows.items()}
        regressed = {key: (before[key], after[key]) for key in rows if after[key] > before[key]}
        assert not regressed, f"通道让已有正文命中掉名次（前→后）：{regressed}"
        assert all(rank <= 5 for rank in after.values()), f"描述性地板失守：{after}"


class TestCueChannelSafetyProperties:
    def test_一键关断后不编码不注入(self, corpus, monkeypatch):
        mgr, rows = corpus
        _attachModelCues(mgr, rows)
        mgr.invalidateAssociationCueIndex()

        monkeypatch.setenv("NEUROVA_MEMORY_CUE_CHANNEL", "off")
        stats = mgr.associationCueChannelStats()
        mgr.recall(query="部门年会要敬酒怎么办", limit=5)
        statsAfter = mgr.associationCueChannelStats()
        assert statsAfter.get("skippedOff", 0) > stats.get("skippedOff", 0), (
            f"关断后没有 skippedOff 计数：{statsAfter}——开关没落到统计面"
        )
        assert statsAfter.get("injected", 0) == stats.get("injected", 0), (
            "关断状态下仍注入了候选"
        )

    def test_低质匹配被门限挡住(self, corpus):
        """无关线索不得注入——外部那套高门的原话就是「加法安全」，本仓同样要求。"""
        mgr, rows = corpus
        mem = mgr._memories[rows["allergy"][0]]
        mgr._associationCues.replaceForMemory(
            rows["allergy"][0],
            [
                {
                    "cue_text": "公司年度财务审计安排",
                    "cue_kind": "situation",
                    "cue_source": "model",
                    "confidence": 0.8,
                    "norm_key": "bogus_audit",
                }
            ],
            scope=(mem.neuser_id, mem.user_id),
            createdAt=mem.created_at,
        )
        mgr.invalidateAssociationCueIndex()

        reading = mgr.associationCueChannelStats()
        before = dict(reading)
        mgr.recall(query="今天天气适合跑步吗", limit=5)
        after = mgr.associationCueChannelStats()
        assert after.get("injected", 0) == before.get("injected", 0), (
            f"无关线索越过了门限被注入：{before} → {after}"
        )

    def test_作用域门同样管住向量通道(self, corpus):
        mgr, rows = corpus
        _attachModelCues(mgr, rows)
        mgr.invalidateAssociationCueIndex()

        memoryId = rows["med"][0]
        assert mgr.get_associationCues(memoryId), "前提：本作用域有线索"
        mgr.set_request_scope("other_neuser", "other_user")
        try:
            assert mgr.get_associationCues(memoryId) == []
            assert mgr.associationCueChannelCandidates() == [], (
                "他人作用域仍拿到线索候选 id——向量通道漏了作用域门"
            )
        finally:
            mgr.clear_request_scope()

    def test_索引规模有上限(self, corpus):
        """线索档规模上限是**公平性**边界（冷启动不该吃掉整轮固化窗口），
        不是模型调用预算——用户裁的丙只放开调用侧，这里不放。"""
        mgr, rows = corpus
        limit = mgr.associationCueIndexCapacity()
        assert isinstance(limit, int) and limit > 0, f"容量上限缺失：{limit}"
