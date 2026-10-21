"""记忆联想召回的常驻判据集（TM-1，2026-10-21）

根因（本仓自有断点，非「外部项目有所以要有」）：
- 记忆检索质量此前**没有任何被 pytest 收集的判据**。唯一的形状件
  `tests/performance/longmeval_simple.py` 因 `pyproject.toml:102-103` 的
  `python_files=["test_*.py"]` / `python_classes=["Test*"]` 双双不匹配其文件名与类名，
  实测 `--collect-only` 报 `collected 0 items`——一份看着在、实际从不运行的测量件。
  没有基线读数，任何检索改动的「有效」都不可证，按 `AGENTS.md` §1 修复教义第 3 条，
  无红可咬的改动不许开工。本文件先把判据建起来。
- 本文件测的是**可达性上界**：本仓 chat 主路的记忆候选只由「向量近邻 + 整句查询子串」
  两路融合（`manager.py:2098-2101`、`manager.py:2104-2109`），提示拼装层的主题相关性
  又是关键词子串计数（`injector.py:568-573`）。因此「查询与记忆无共同词面却实质相关」
  这类提问，今天完全靠嵌入向量的近邻运气。

判据形态（四道，各司其职）：
1. `test_联想查询集自证词面不相交` —— 数据集**自反证**：联想子集与目标记忆的中文字面
   重合必须 ≤30%，且至少 3 条为 0%；描述性子集必须 ≥90%。有人把语料改弱来凑绿，先红这里。
2. `test_描述性召回地板` —— 词面重合类查询必须 top-1 命中。这是能力地板，掉分即回归。
3. `test_联想召回基线只降不升` —— 棘轮：基线取**本轮实测值**（见 `audit-reports/` 台账
   §6-381），此后只许升不许降；本文件不主张今天达标，只钉住「不得更差」。
4. `test_联想召回目标_hit1须达六成` / `test_招牌案例_无词面重合也必须召回` —— 目标值，
   今天**够不到**，挂 `xfail(strict=True)`：语义即「将来要绿」，一旦 TM-2/TM-3 把它做到，
   strict xfail 会以 XPASS 变红，逼着摘标记并回写台账——不留静默达成的口子。

前置与口径：本地 ONNX 嵌入档必须可用（`models/embedding/bge-small-zh-v1.5/model.onnx`
已入 git），与 `test_onnx_lazy_init_deadlock.py` 同一前提；缺档即显式失败，
**不做 skip**——skip 会把它变成第二条 `longmeval_simple.py`。语料固定、`enable_buffer=False`
同步写入，读数经独立复跑逐位一致（hit@1=2/10、hit@5=6/10、MRR=0.35，ranks 全等）。
"""

import math
import os

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

pytestmark = [pytest.mark.timeout(180)]

# ────── 语料：10 条目标记忆 × (描述性查询 / 联想查询)，另 66 条干扰项 ──────
# 联想查询刻意避开目标记忆的措辞与实体名：问的是「未来那件还没发生的事」。
TARGETS = [
    ("allergy", "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏", "团队聚餐选餐厅时要注意什么"),
    ("review", "用户: 我们组每个月末做代码评审，轮流主持", "这周有一段整空档，安排点什么合适"),
    ("kid", "用户: 我的孩子叫小豆，今年四岁，最近喜欢挖沙", "周末带孩子去哪儿玩比较合适"),
    ("budget", "用户: 我们今年的服务器预算只批到十二万，已经花掉九万", "能不能把集群扩到三十台机器"),
    ("commute", "用户: 我每天早上七点二十从通州出发，地铁换乘两次", "明天要不要约客户吃早餐"),
    ("med", "用户: 我在吃一种需要忌酒的处方药，医生叮嘱整个疗程都不能喝", "部门年会要敬酒怎么办"),
    ("dog", "用户: 我家那只叫煤球的金毛怕打雷，一到雷雨天就钻床底", "下周有雷雨我出门该做什么安排"),
    ("anniv", "用户: 我太太的生日是三月十七号，她喜欢园艺", "三月份我该提前准备点什么"),
    ("deploy", "用户: 生产库的迁移窗口只允许在周日凌晨两点到四点之间", "周三下午能不能改表结构"),
    ("diet", "用户: 我最近在戒糖，甜点和含糖饮料都停了", "午饭后来杯奶茶怎么样"),
]

DISTRACTORS = [
    "用户: 上季度我们把日志采集从 filebeat 换成了 fluent-bit",
    "助手: 好的，我把 fluent-bit 的配置变更记录在案",
    "用户: 会议室 B 的投影仪换成激光的了",
    "用户: 团队的周报模板改成了三段式",
    "助手: 已记录：周报模板调整",
    "用户: 楼下的咖啡店开始用可回收杯",
    "用户: 我们的镜像仓库做了分层缓存",
    "助手: 镜像分层缓存已写入知识库",
    "用户: 新同事的工牌照片这周补拍",
    "用户: 办公室绿植由前台每周浇水",
    "助手: 好的，绿植排班记下了",
    "用户: 内部 wiki 搜索接口上周升级了",
    "用户: 财务报销系统每月五号关账",
    "助手: 记下了：报销每月五号关账",
    "用户: 测试环境的域名换成了 .test.internal",
    "用户: 车库月卡到期需要续办",
    "助手: 月卡续办事宜已登记",
    "用户: 客服工单系统增加了自动分类",
    "用户: 每周三下午是固定的一对一时间",
    "助手: 已记录一对一时间安排",
    "用户: 服务器的时区统一设为 UTC+8",
    "助手: 时区配置已同步",
    "用户: 新版本把首页改成了卡片流",
    "用户: 打印机卡纸要先重启进纸模块",
    "助手: 打印机故障处理记录在案",
    "用户: 团队午餐一般点粤菜",
    "助手: 记下了：午餐偏好粤菜",
    "用户: 网关限流阈值从 200 提到了 400",
    "助手: 已记录限流阈值变更",
    "用户: 办公室空调温度设定在 24 度",
    "用户: 数据库慢查询日志每周归档一次",
    "助手: 慢查询归档周期已记录",
    "用户: 新采购了十把人体工学椅",
    "用户: 快递代收点在园区北门",
    "助手: 北门代收点信息已记下",
    "用户: 迭代回顾会改到双周一次",
    "助手: 已记录回顾会节奏",
    "用户: 前端构建时间从四分钟降到两分钟",
    "用户: 值班表按月轮换",
    "助手: 值班轮换规则记下了",
    "用户: 客户回访话术增加了满意度提问",
    "用户: 备份策略是每日全量加每小时增量",
    "助手: 已记录备份策略",
    "用户: 工位显示器支架是明年三月采购",
    "用户: 内部分享用的是跨平台直播方案",
    "助手: 直播方案信息已登记",
    "用户: 代码评审清单增加了安全检查项",
    "助手: 已记录评审清单变更",
    "用户: 团队用了新的番茄钟应用",
    "用户: 园区停车费每月三百元",
    "助手: 停车费信息已记下",
    "用户: 移动端崩溃率上周降到千分之二",
    "用户: 供应商合同年底续签",
    "助手: 合同续签时间已登记",
    "用户: 新人入职手册增加了安全章节",
    "用户: 会议室预定系统支持取消三次",
    "助手: 已记录预定规则",
    "用户: 数据看板每天六点自动刷新",
    "用户: 客服知识库做了去重整理",
    "助手: 知识库整理完成",
    "用户: 网络出口带宽扩容到两个 G",
    "用户: 周五的分享会推迟到下周",
    "助手: 分享会延期已记录",
    "用户: 测试机池增加了两台 arm 节点",
    "用户: 团队用的是灰度发布流程",
    "助手: 已记录发布流程",
]

PROBE_LIMIT = 10

# 棘轮基线：2026-10-21 本机实测（台账 §6-381 同值）。只许升，不许降。
_ASSOCIATIVE_BASELINE = {"hit5": 6, "mrr": 0.35}
# 目标值：TM-2（条目级抽象线索）/ TM-3（前瞻线索）的验收线，今天够不到。
_ASSOCIATIVE_TARGET = {"hit1": 6}

_CJK_OVERLAP_MAX = 0.30
_SURFACE_OVERLAP_MIN = 0.90


def _cjkChars(text: str) -> set:
    return {ch for ch in text if "\u4e00" <= ch <= "\u9fff"}


def _overlapRatio(query: str, memory: str) -> float:
    """查询与记忆的中文字面重合度（按较短一侧归一）。"""
    left, right = _cjkChars(query), _cjkChars(memory)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _rankOf(manager: MemoryManager, query: str, expectedContent: str) -> int:
    """目标记忆在 recall 结果里的位次（1 起）；未进前 PROBE_LIMIT 返回 99。"""
    hits = manager.recall(query=query, limit=PROBE_LIMIT)
    for index, row in enumerate(hits, start=1):
        if (row.get("content") or "") == expectedContent:
            return index
    return 99


def _measure(manager: MemoryManager, pickQuery) -> dict:
    ranks = [_rankOf(manager, pickQuery(text, foreshadow), text) for _key, text, foreshadow in TARGETS]
    hit1 = sum(1 for r in ranks if r <= 1)
    hit5 = sum(1 for r in ranks if r <= 5)
    mrr = sum(1.0 / r for r in ranks if r != 99) / len(ranks)
    return {"n": len(ranks), "hit1": hit1, "hit5": hit5, "mrr": round(mrr, 3), "ranks": ranks}


@pytest.fixture
def recallCorpus(tmp_path):
    from neurova.embedding import get_embedding_engine

    engine = get_embedding_engine()
    assert engine is not None, (
        "本地 ONNX 嵌入档不可用：本判据测的是生产同款稠密+词法双路检索，"
        "缺 models/embedding/bge-small-zh-v1.5/model.onnx 时读数无意义。"
        "该前提与 test_onnx_lazy_init_deadlock.py 直接构造 ONNXEmbeddingEngine 一致，"
        "不以 skip 蒙过（skip 会让判据退化成第二条 longmeval_simple.py）。"
    )

    manager = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"),
        agent_id="assoc_recall_gate",
        enable_buffer=False,
    )
    for text in DISTRACTORS:
        manager.remember(content=text, memory_type="episodic", metadata={"chat_scope": "direct"})
    for _key, text, _foreshadow in TARGETS:
        manager.remember(content=text, memory_type="episodic", metadata={"chat_scope": "direct"})

    rows = manager.get_memories(limit=2000)
    assert len(rows) == len(DISTRACTORS) + len(TARGETS), (
        f"语料应落 {len(DISTRACTORS) + len(TARGETS)} 行，实落 {len(rows)}——"
        "有行被内容门/作用域吞掉时，读数不再反映检索能力"
    )
    yield manager
    manager.close()


class TestAssociativeRecallDatasetIsSelfProving:
    """数据集必须自己证明「联想」确实没有词面可走。"""

    def test_联想查询集自证词面不相交(self):
        ratios = [_overlapRatio(foreshadow, text) for _key, text, foreshadow in TARGETS]
        for ratio, (_key, text, foreshadow) in zip(ratios, TARGETS):
            assert ratio <= _CJK_OVERLAP_MAX, (
                f"联想查询与目标记忆字面重合 {ratio:.2f}：{foreshadow} ↔ {text}；"
                "该条已退化成描述性召回，不能作为联想判据"
            )
        disjoint = sum(1 for r in ratios if r == 0.0)
        assert disjoint >= 3, f"零词面重合的联想查询应≥3 条，实有 {disjoint} 条"

    def test_描述性对照组确有词面可走(self):
        ratios = [_overlapRatio(text[:18], text) for _key, text, _foreshadow in TARGETS]
        assert min(ratios) >= _SURFACE_OVERLAP_MIN, (
            f"描述性对照组最低重合度 {min(ratios):.2f} < {_SURFACE_OVERLAP_MIN}——"
            "两组不再可比，地板与棘轮的差值失去意义"
        )


class TestAssociativeRecallBaseline:
    def test_描述性召回地板(self, recallCorpus):
        reading = _measure(recallCorpus, lambda text, _foreshadow: text[:18])
        assert reading["hit1"] == reading["n"], (
            f"词面重合查询未能全部 top-1：{reading['ranks']}；"
            "描述性召回是能力地板，此处掉分即检索链路回归"
        )

    def test_联想召回基线只降不升(self, recallCorpus):
        reading = _measure(recallCorpus, lambda _text, foreshadow: foreshadow)
        print(f"[TM-1 联想读数] {reading}  基线={_ASSOCIATIVE_BASELINE}")
        assert reading["hit5"] >= _ASSOCIATIVE_BASELINE["hit5"], (
            f"联想 hit@5 由 {_ASSOCIATIVE_BASELINE['hit5']} 掉到 {reading['hit5']}（棘轮只降不升）"
        )
        assert not (reading["mrr"] + 1e-9 < _ASSOCIATIVE_BASELINE["mrr"]), (
            f"联想 MRR 由 {_ASSOCIATIVE_BASELINE['mrr']} 掉到 {reading['mrr']}（棘轮只降不升）"
        )


class TestMetricInstrumentIsSharp:
    """度量器本身要会咬——防「恒真的假绿」（`AGENTS.md` §4 禁止恒真断言）。"""

    def test_目标缺席必须记为零命中(self):
        ranks = [1, 3, 99, 99]
        hit5 = sum(1 for r in ranks if r <= 5)
        mrr = sum(1.0 / r for r in ranks if r != 99) / len(ranks)
        assert hit5 == 2 and math.isclose(mrr, (1.0 + 1 / 3) / 4), "命中/倒数排名口径算错"

    def test_位次下滑必须反映到读数下滑(self):
        good = _pseudoReading([1, 1, 2, 3, 4, 5, 6, 8, 99, 99])
        worse = _pseudoReading([5, 6, 8, 9, 99, 99, 99, 99, 99, 99])
        assert good["hit5"] > worse["hit5"] and good["mrr"] > worse["mrr"], (
            "同一份度量器对更差的排序不敏感 ⇒ 判据恒真"
        )


def _pseudoReading(ranks):
    return {
        "hit5": sum(1 for r in ranks if r <= 5),
        "mrr": sum(1.0 / r for r in ranks if r != 99) / len(ranks),
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TM-1 已知缺口，非本批修复项：联想查询的 top-1 只有 2/10（hit@5=6/10、MRR=0.35），"
        "根因是写侧不存在任何「预演未来问法」的产物、检索可达性全由词面与嵌入近邻决定。"
        "TM-2（条目级抽象线索）/ TM-3（前瞻线索，落 10 轮低负荷固化窗口）达成后"
        "本用例以 XPASS 变红 ⇒ 摘掉本标记、把 top-1 抬进基线并回写台账（§6-381 续笔）。"
    ),
)
def test_联想召回目标_hit1须达六成(recallCorpus):
    reading = _measure(recallCorpus, lambda _text, foreshadow: foreshadow)
    assert reading["hit1"] >= _ASSOCIATIVE_TARGET["hit1"], f"当前 top-1={reading['hit1']}/10"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "同族缺口的单点形态：与记忆零中文字面重合的提问（汉字重合 0%）今天连前 10 都进不了。"
        "该条一旦能被召回，说明写侧线索真的接进了检索路——摘标记并回写台账。"
    ),
)
def test_招牌案例_无词面重合也必须召回(recallCorpus):
    target = next(text for key, text, _q in TARGETS if key == "allergy")
    query = next(q for key, _text, q in TARGETS if key == "allergy")
    assert _overlapRatio(query, target) == 0.0, "该用例的前提是零中文字面重合，语料被改动即前提失效"
    assert _rankOf(recallCorpus, query, target) <= PROBE_LIMIT, (
        f"「{query}」未能召回「{target}」"
    )
