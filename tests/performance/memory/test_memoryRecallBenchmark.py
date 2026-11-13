# -*- coding: utf-8 -*-
"""C7（graphiti 对照批）：对外记忆基准最小集——多轮注入→间隔追问→读数。

与 test_associativeRecallGate 的分工：那份钉「联想召回」能力地板与棘轮；
本文件是**可对外复述的基准读数面**——模拟 LongMemEval 式的多轮会话注入
与间隔追问，产出 hit@1/hit@5/MRR、检索延迟分位、单次注入字符量（token
成本代理）与 fact 级有效期（C6）联动读数。断言只设宽松下限（防彻底退化），
**不进 protected_tests 门禁**——基准是证据，不是门。

前置：本地 ONNX 嵌入档（同 associativeRecallGate）；缺档 skip 并说明，
不假装失败。判分时钟纪律：延迟只设量级护栏（墙钟，答"有没有爆炸"），
细粒度读数一律打印不设门。
"""

import json
import os
import time

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

pytestmark = [pytest.mark.timeout(180)]

# ────── 语料：8 段多轮会话（每段 3 轮围绕一个可追问事实）＋ 40 条干扰 ──────
# probe 刻意与原文错开措辞（间隔追问形态：问的时候换说法/用指代）。
SESSIONS = [
    {"topic": "shrimp", "turns": ["用户: 周末去海鲜市场买了两斤大虾",
                                  "用户: 晚上吃完浑身起红疹",
                                  "助手: 已记录：进食虾后出现皮疹，待复查过敏原"],
     "probe": "下个月部门聚餐订菜单，哪类菜要先帮你划掉"},
    {"topic": "flight", "turns": ["用户: 我订了 12 月 3 号飞新加坡的航班",
                                  "用户: 航班是早上七点五十起飞",
                                  "助手: 已记录：12 月 3 日 07:50 飞新加坡"],
     "probe": "那天叫车应该约几点"},
    {"topic": "vpn", "turns": ["用户: 出差只能走公司 VPN 连内网",
                               "用户: 但 VPN 在酒店网络下经常掉线",
                               "助手: 已记录：差旅场景 VPN 稳定性问题"],
     "probe": "我下次在外面办公网络方面要注意什么"},
    {"topic": "salary", "turns": ["用户: 我的房租每个月一万二",
                                  "用户: 房东说明年开始涨到一万三",
                                  "助手: 已记录：房租现价 12000，明年 13000"],
     "probe": "帮我算算居住开销涨了多少个百分点"},
    {"topic": "kid", "turns": ["用户: 我儿子现在在读小学三年级",
                               "用户: 他每周二四放学后练游泳",
                               "助手: 已记录：孩子周二/周四游泳训练"],
     "probe": "帮我看看周中哪几天傍晚不适合安排加班会"},
    {"topic": "coffee", "turns": ["用户: 我对咖啡因特别敏感，下午喝咖啡会失眠",
                                  "用户: 拿铁也不行，改喝洋甘菊茶了",
                                  "助手: 已记录：午后禁咖啡因，已改洋甘菊茶"],
     "probe": "下午的茶歇饮品帮我参谋一下"},
    {"topic": "deadline", "turns": ["用户: 招标文件的递交截止是本月 25 号下午五点",
                                    "用户: 里面还要求附资质复印件",
                                    "助手: 已记录：投标截止 25 日 17:00，需资质复印件"],
     "probe": "我最晚哪天得把材料准备齐"},
    {"topic": "gym", "turns": ["用户: 我办了公司旁边健身房的黑金卡",
                               "用户: 一般周一三五中午去练四十分钟",
                               "助手: 已记录：健身节奏为一三五午间"],
     "probe": "帮我把午休安排里固定出运动时段"},
]

DISTRACTORS = [
    "用户: 会议室 C 的白板笔没水了",
    "助手: 已记录：更换白板笔",
    "用户: 新版文档站用了暗色主题",
    "用户: 食堂周三供应红烧肉",
    "助手: 菜单信息已记下",
    "用户: 打卡系统升级到人脸识别",
    "用户: 项目周报改成飞书表格提交",
    "助手: 周报渠道已更新",
    "用户: 公司门口修路，绕行两个星期",
    "用户: 新打印机支持双面打印",
    "助手: 打印机功能已登记",
    "用户: 客服排班软件换成了排班蜂",
    "用户: 办公室门禁卡要年年续",
    "助手: 门禁续期规则已记录",
    "用户: 代码仓默认分支改名为 main",
    "用户: 邮件签名统一加了法务声明",
    "助手: 签名规范已同步",
    "用户: 差旅报销要附行程单",
    "助手: 报销材料清单已更新",
    "用户: 测试环境数据库每晚重置",
    "用户: 企业微信换了新头像",
    "助手: 展示信息已更新",
    "用户: 年会节目报名开始了",
    "用户: 楼下快递柜扩容了一倍",
    "助手: 快递柜信息已记录",
    "用户: 服务器机房空调检修预告",
    "用户: 内网门户首页加了导航",
    "助手: 门户改版已记录",
    "用户: 新同事培训视频一共六集",
    "用户: 前台电话换成 8008",
    "助手: 前台号码已更新",
    "用户: 办公软件升级到新版 wps",
    "用户: 食堂饭卡支持手机充值",
    "助手: 充值方式已记录",
    "用户: 公司班车增加一条线路",
    "用户: 值班室搬到了二楼",
    "助手: 值班室位置已更新",
    "用户: 团建地点投票开始了",
    "用户: 打印纸要省着用",
    "助手: 耗材提示已记录",
]

PROBE_LIMIT = 10

# 宽松下限（防彻底退化；精确基线归 associativeRecallGate 棘轮管）
_FLOOR = {"hit1": 3, "hit5": 6, "mrr": 0.40}  # n=8
_P95_SECONDS_CEILING = 10.0  # 量级护栏：只答"有没有爆炸"


@pytest.fixture
def benchmarkCorpus(tmp_path):
    from tests.memory_embedding_precondition import requireRealEmbeddingOrSkip

    requireRealEmbeddingOrSkip("记忆基准（多轮注入→间隔追问，走生产稠密+词法双路）")

    manager = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"),
        agent_id="memory_benchmark",
        enable_buffer=False,
    )
    injectedChars = 0
    for session in SESSIONS:
        for turn in session["turns"]:
            manager.remember(content=turn, memory_type="episodic",
                             metadata={"chat_scope": "direct"})
            injectedChars += len(turn)
    for text in DISTRACTORS:
        manager.remember(content=text, memory_type="episodic",
                         metadata={"chat_scope": "direct"})
    # C6 联动：两条已失效记忆（曾有效、现已过期）——检索面不得再吐
    manager.remember(content="用户: 旧办公室在城西产业园 3 号楼",
                     memory_type="semantic",
                     valid_until="2020-01-01T00:00:00+00:00",
                     metadata={"chat_scope": "direct"})
    manager.remember(content="用户: 上一版报销上限是每单五百元",
                     memory_type="semantic",
                     valid_until="2020-01-01T00:00:00+00:00",
                     metadata={"chat_scope": "direct"})

    rows = manager.get_memories(limit=2000)
    assert len(rows) == len(DISTRACTORS) + sum(len(s["turns"]) for s in SESSIONS) + 2, (
        f"语料应全量落库，实落 {len(rows)} 行——有行被内容门吞掉时读数失真")
    yield manager, injectedChars
    manager.close()


def _rankOf(manager: MemoryManager, query: str, probeTurns) -> int:
    """目标会话任一轮命中即算会话命中，取最高位次（1 起）；未进前 10 返回 99。"""
    started = time.monotonic()
    hits = manager.recall(query=query, limit=PROBE_LIMIT)
    elapsed = time.monotonic() - started
    best = 99
    for index, row in enumerate(hits, start=1):
        if (row.get("content") or "") in probeTurns:
            best = min(best, index)
    return best, elapsed, hits


def _measure(manager: MemoryManager) -> dict:
    ranks, latencies, injectedChars = [], [], 0
    expiredLeak = 0
    for session in SESSIONS:
        rank, elapsed, hits = _rankOf(manager, session["probe"],
                                      session["turns"])
        ranks.append(rank)
        latencies.append(elapsed)
        injectedChars += sum(len(str(h.get("content") or "")) for h in hits)
        for h in hits:
            if "城西产业园" in str(h.get("content") or "") or \
                    "每单五百元" in str(h.get("content") or ""):
                expiredLeak += 1
    ordered = sorted(latencies)
    p50 = ordered[len(ordered) // 2]
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    hit1 = sum(1 for r in ranks if r <= 1)
    hit5 = sum(1 for r in ranks if r <= 5)
    mrr = sum(1.0 / r for r in ranks if r != 99) / len(ranks)
    return {
        "n": len(ranks), "hit1": hit1, "hit5": hit5,
        "mrr": round(mrr, 3), "ranks": ranks,
        "latency_p50_s": round(p50, 4), "latency_p95_s": round(p95, 4),
        "avg_injected_chars": round(injectedChars / len(SESSIONS), 1),
        "expired_leak": expiredLeak,
    }


class TestMemoryRecallBenchmark:
    def test_intervalProbe_recallAndLatency(self, benchmarkCorpus):
        manager, injectedChars = benchmarkCorpus
        reading = _measure(manager)
        print("[C7 基准读数] " + json.dumps(reading, ensure_ascii=False))
        print("[C7 注入总量] %d chars（%d 轮语料 + %d 干扰 + 2 过期）"
              % (injectedChars, sum(len(s["turns"]) for s in SESSIONS),
                 len(DISTRACTORS)))
        assert reading["hit1"] >= _FLOOR["hit1"], (
            f"间隔追问 top-1={reading['hit1']}/{reading['n']} 低于宽松下限 "
            f"{_FLOOR['hit1']}——检索链路可能退化：{reading['ranks']}")
        assert reading["hit5"] >= _FLOOR["hit5"], (
            f"间隔追问 hit@5={reading['hit5']}/{reading['n']} 低于宽松下限 "
            f"{_FLOOR['hit5']}：{reading['ranks']}")
        assert reading["mrr"] >= _FLOOR["mrr"], (
            f"间隔追问 MRR={reading['mrr']} 低于宽松下限 {_FLOOR['mrr']}")
        assert reading["latency_p95_s"] < _P95_SECONDS_CEILING, (
            f"检索 p95 延迟 {reading['latency_p95_s']}s 超量级护栏 "
            f"{_P95_SECONDS_CEILING}s——先查环境再谈检索")
        assert reading["expired_leak"] == 0, (
            "已过期的 fact（C6 validity 窗口）混进召回结果——时间语义失守")

    def test_expiredFactsInvisible_evenInBroadProbe(self, benchmarkCorpus):
        """专测 C6 联动：直问过期内容也不得召回。"""
        manager, _injected = benchmarkCorpus
        for probe in ("旧办公室在哪", "报销上限是多少"):
            for row in manager.recall(query=probe, limit=PROBE_LIMIT):
                content = str(row.get("content") or "")
                assert "城西产业园" not in content and "每单五百元" not in content, (
                    f"过期记忆仍被召回：{content}")
