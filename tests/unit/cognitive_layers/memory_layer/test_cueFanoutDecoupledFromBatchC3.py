"""C-3：把「去重」与批量 N 解耦，改用地面化的**扇出门**（判据集）

来历（同一根因链上的两个实测）：
- 批 C-1 标定发现联想通道误注入的主因是「别的记忆的线索更像」：目标线索余弦 0.465–0.612，
  而**其它记忆的线索**可达 0.687 ⇒ 泛词才是问题。
- 批 N 扫描发现旧实现把它交给错了地方：`filterModelCues` 的 `usedNormKeys` 在函数体内新建，
  于是「同一条线索被两条记忆复用」在**同批被挡、跨批各自留下** —— 去重窗口＝批大小，
  N 偷偷兼任了质量参数（换 N 就换结论，成本扫描的读数也因此被污染）。

本批把两件事分开：
1. **写入侧不再按批去重**。一条上位名本就可能同时指向多条记忆，那是**正当共享**，
   按批丢弃等于少给一条访问路，而且丢哪条只看切批边界——纯运气。
2. 检索侧按 **全局扇出**裁：同一条线索（`norm_key`）挂住的记忆数超过一次检索能区分的上限时，
   它已经不可能提供区分度，只能并列灌满候选 ⇒ 整条不参与通道，并计入 `droppedByFanout`。
   门槛值由检索预算推出（见 `CUE_FANOUT_CAP` 注释），不是拍的魔法数；
   但**它是从预算推出来的上界、不是按真机分布标定出来的最优值**——留了读数以便日后重定。
"""

import os

import pytest

from neurova.cognitive_layers.memory_layer import association_cue_generation as gen
from neurova.cognitive_layers.memory_layer import association_cue_index as cueIndex
from neurova.cognitive_layers.memory_layer import association_cues
from neurova.cognitive_layers.memory_layer.manager import MemoryManager

pytestmark = [pytest.mark.timeout(180)]


def _rows(texts):
    return [{"index": i, "memory_id": f"m{i}", "content": t} for i, t in enumerate(texts)]


class TestFilterIsIndependentOfBatchSize:
    """正题：同一组线索，怎么切批都不能改变最终留下的集合。"""

    SHARED = "海鲜类食材的聚餐点菜场合"

    def test_跨记忆复用同词不再被批内丢弃(self):
        texts = [
            "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏",
            "用户: 上次吃螃蟹也起了疹子，海鲜得小心",
        ]
        rows = _rows(texts)
        parsed = [{"index": 0, "text": self.SHARED}, {"index": 1, "text": self.SHARED}]

        kept, dropped = gen.filterModelCues(parsed, rows)

        assert dropped == 0, f"同一条线索被第二条记忆复用时仍被挡（去重窗口没拆掉）：{dropped}"
        assert kept[0] and kept[1], f"两条记忆里有一条没拿到该线索：{kept}"
        assert kept[0][0]["cue_text"] == kept[1][0]["cue_text"] == self.SHARED

    def test_切批方式不改变落库集合(self):
        """一整批 vs 一行一批：合并后的结果集必须逐条相等。"""
        texts = [
            "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏",
            "用户: 上次吃螃蟹也起了疹子，海鲜得小心",
            "用户: 我最近戒糖，甜点和含糖饮料都停了",
        ]
        cue = self.SHARED
        allRows = _rows(texts)

        whole, _d1 = gen.filterModelCues(
            [{"index": i, "text": cue} for i in range(len(texts))], allRows
        )
        wholeSet = sorted(c["cue_text"] for cues in whole.values() for c in cues)

        perRow = []
        for i, text in enumerate(texts):
            one = [{"index": 0, "memory_id": f"m{i}", "content": text}]
            kept, _d2 = gen.filterModelCues([{"index": 0, "text": cue}], one)
            perRow.extend(c["cue_text"] for cues in kept.values() for c in cues)
        perRowSet = sorted(perRow)

        assert wholeSet == perRowSet == [cue] * len(texts), (
            f"批切方式改变了结果：整批 {wholeSet} vs 逐行 {perRowSet}"
        )

    def test_每条记忆的线索上限仍然生效(self):
        """拆掉批内去重不能顺手把「每行最多几条」也拆了——那是形态约束，与 N 无关。"""
        texts = ["用户: 我最近在戒糖，甜点和含糖饮料都停了"]
        rows = _rows(texts)
        parsed = [{"index": 0, "text": f"控糖场合专用词{i}"} for i in range(9)]

        kept, _dropped = gen.filterModelCues(parsed, rows)
        assert len(kept[0]) == gen.CUES_PER_MEMORY, (
            f"每条线索上限失效：拿到 {len(kept[0])}，应为 {gen.CUES_PER_MEMORY}"
        )


@pytest.fixture
def fanoutManager(tmp_path):
    from neurova.embedding import get_embedding_engine
    from neurova.cognitive_layers.memory_layer.semantic_search import reset_semantic_search

    if get_embedding_engine() is None:
        pytest.skip(
            "本判据需要本地 ONNX 档（缺档时通道不点火，测不到门）："
            "补件 `pip install -r requirements-full.lock`（含 numpy/onnxruntime）"
        )
    reset_semantic_search()
    mgr = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"), agent_id="cue_fanout_c3", enable_buffer=False
    )
    yield mgr
    mgr.close()
    reset_semantic_search()


def _attachSharedCue(mgr, contents, cueText):
    ids = []
    for i, content in enumerate(contents):
        memId = mgr.remember(content=content, memory_type="episodic",
                             metadata={"chat_scope": "direct"})
        mem = mgr._memories[memId]
        mgr._associationCues.replaceForMemory(
            memId,
            [{
                "cue_text": cueText,
                "cue_kind": "situation",
                "cue_source": "model",
                "confidence": 0.7,
                "norm_key": association_cues.cueNormKey(cueText),
            }],
            scope=(mem.neuser_id, mem.user_id),
            createdAt=mem.created_at,
        )
        ids.append(memId)
    return ids


class TestFanoutGate:
    def test_扇出超限的线索不参与通道(self, fanoutManager):
        """同一条线索挂到「超过一次检索能区分的条数」时，它只能并列灌满候选 ⇒ 整条出局。"""
        contents = [
            f"用户: 第{i}件彼此无关的往事，场所与人员各不相同编号{i}"
            for i in range(cueIndex.CUE_FANOUT_CAP + 1)
        ]
        _attachSharedCue(fanoutManager, contents, "以后用得上的事")
        fanoutManager.invalidateAssociationCueIndex()

        candidates = fanoutManager.associationCueChannelCandidates()
        assert candidates == [], f"超限扇出的线索仍进了通道索引：{candidates}"
        assert fanoutManager.associationCueChannelStats().get("droppedByFanout", 0) >= 1, (
            f"扇出门没有读数：{fanoutManager.associationCueChannelStats()}"
        )

    def test_正当共享的线索不受影响(self, fanoutManager):
        """两条记忆共用一个上位名是正当形态（上位名本就共享），门不得误伤。"""
        contents = [
            "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏",
            "用户: 上次吃螃蟹也起了疹子，海鲜得小心",
        ]
        ids = _attachSharedCue(fanoutManager, contents, "海鲜类食材的聚餐点菜场合")
        fanoutManager.invalidateAssociationCueIndex()

        candidates = set(fanoutManager.associationCueChannelCandidates())
        assert candidates == set(ids), f"正当共享的线索被门挡掉了：{candidates} vs {set(ids)}"

    def test_门槛值有出处且不静默(self, fanoutManager):
        """门槛必须写明它是从检索预算推出来的，且被挡的条数看得见——否则又成隐式上限。"""
        assert cueIndex.CUE_FANOUT_CAP >= 2, f"门槛退化：{cueIndex.CUE_FANOUT_CAP}"
        stats = fanoutManager.associationCueChannelStats()
        assert "droppedByFanout" in stats, f"缺扇出读数，日后无法按真机分布重定门槛：{sorted(stats)}"
