# -*- coding: utf-8 -*-
"""D7 召回质量评测核心（可复用）。

消费方：
- tests/performance/memory/test_memoryRecallTemperatureBenchmark.py（三态对照基准）
- neurova/benchmark/recall_auto_tune.py（自动调参工具，D8）

语料/查询集/指标计算单一事实源在此。评测走生产融合召回
（NeurovaRecallEngine），语料经 SQL 直插 + 受控温度改写（切勿与
remember 交错开第二条连接的未提交事务——会把 manager 持久化锁死）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

# ── 近期热点（8 条，C 态温度 92~97，刚访问）────────────────────────────
HOT_TOPICS = [
    ("h1", "已记录：进食虾后出现皮疹，待复查过敏原", "下周部门聚餐订菜单，哪类菜要先帮你划掉"),
    ("h2", "已记录：12 月 3 日 07:50 的航班飞新加坡", "那天去机场叫车应该约几点"),
    ("h3", "已记录：差旅场景 VPN 稳定性问题待解决", "下次在外地办公，网络方面要注意什么"),
    ("h4", "已记录：房租现价 12000，明年涨到 13000", "帮我算算居住成本涨了多少个百分点"),
    ("h5", "已记录：孩子每周二、周四放学后游泳训练", "帮我看下周中哪几天傍晚不适合安排加班"),
    ("h6", "已记录：午后禁咖啡因，已改洋甘菊茶", "下午茶歇的饮品帮我参谋一下"),
    ("h7", "已记录：投标截止本月 25 日 17:00，需附资质复印件", "我最晚哪天要把材料准备齐"),
    ("h8", "已记录：健身节奏为周一三五午间四十分钟", "帮我把午休里固定出运动时段"),
]

# ── 老而重要（8 条，结晶+重要，C 态温度 55~65，60 天未访问）────────────
OLD_IMPORTANT = [
    ("o1", "公司成立于 2015 年 3 月", "公司是什么时候成立的"),
    ("o2", "核心产品代号是星轨", "我们的核心产品代号叫什么"),
    ("o3", "年假政策：入职满三年每年 15 天", "满三年的年假有几天"),
    ("o4", "报销需要直属上级和财务双签", "报销的审批流程是什么"),
    ("o5", "数据库默认时区是 UTC", "数据库用的时区是什么"),
    ("o6", "客服热线是 400-800-1234", "客服电话是多少"),
    ("o7", "月度复盘固定在每月最后一个周五", "复盘会一般什么时候开"),
    ("o8", "生产环境禁止 root 直连", "生产环境的登录方式有什么要求"),
]

# ── 冷门强相关（8 条，C 态温度 22~28，90 天未访问，文本强相关）─────────
COLD_RELEVANT = [
    ("c1", "仓库温湿度传感器型号是 SHT31", "仓库的温湿度传感器是什么型号"),
    ("c2", "服务器机房在合肥", "机房在哪个城市"),
    ("c3", "供应商对接人姓陈", "供应商那边对接人姓什么"),
    ("c4", "报表工具用的是 Metabase", "公司的报表工具是什么"),
    ("c5", "办公室绿植每周五浇水", "办公室绿植什么时候浇水"),
    ("c6", "我的停车位编号是 B12", "我的停车位是几号"),
    ("c7", "备用网络热点密码是 88888888", "备用网络的密码是什么"),
    ("c8", "打印机型号是 HP M405", "打印机是什么型号"),
]

# ── 易混淆对（6 对：内容相近，查询只应命中目标那条）────────────────────
CONFUSABLE_PAIRS = [
    ("p1a", "前端负责人是张伟", "p1b", "后端负责人是李强", "前端负责人是谁"),
    ("p2a", "上海仓库在浦东新区", "p2b", "北京仓库在大兴区", "上海的仓库在哪个区"),
    ("p3a", "A 项目预算是 50 万", "p3b", "B 项目预算是 80 万", "A 项目的预算是多少"),
    ("p4a", "周一例会在九点", "p4b", "周四例会在十点", "周一例会几点开"),
    ("p5a", "报销系统账号是 fin01", "p5b", "OA 系统账号是 admin01", "报销系统的账号是什么"),
    ("p6a", "新人导师是王芳", "p6b", "新人导师助理是刘明", "新人导师是谁"),
]

# ── 干扰项底料（程序化展开，确定性无随机）───────────────────────────────
_DISTRACTOR_SEEDS = [
    "会议室白板笔更换", "文档站暗色主题上线", "食堂周三供应红烧肉", "打卡系统升级人脸识别",
    "项目周报改飞书表格", "公司门口修路绕行", "新打印机支持双面打印", "客服排班软件更换",
    "办公室门禁卡年度续期", "代码仓默认分支改名", "邮件签名加法务声明", "差旅报销附行程单",
    "测试环境数据库每晚重置", "企业微信头像更换", "年会节目报名启动", "楼下快递柜扩容",
    "机房空调检修预告", "内网门户首页加导航", "新同事培训视频六集", "前台电话更换",
    "办公软件升级新版", "食堂饭卡手机充值", "公司班车增线路", "值班室搬到二楼",
    "团建地点投票启动", "打印纸节约使用", "耗材领用登记", "工位绿植轮换",
]

_QUERY_CATEGORIES = ["recent_hot", "old_important", "cold_relevant", "confusable"]

# 各状态温度分配：A=100 均匀 / B=60 均匀 / C=按角色塑形（D5 设计终态）
_STATE_ASSIGNS = {
    "A": lambda _i: 100.0,
    "B": lambda _i: 60.0,
}


def build_corpus_specs() -> Tuple[
    List[Tuple[str, str, Callable[[str], Optional[float]], float, int, float, str]],
    List[Tuple[str, str, str, Optional[str]]],
]:
    """返回 (rows, queries)。

    rows: (role_id, content, temp_fn(state)->float|None, last_accessed_days_ago,
            access_count, importance, lifecycle_stage)
    queries: (category, query_text, expected_role, confusable_role|None)
    """
    rows: list = []
    queries: list = []

    for i, (rid, content, probe) in enumerate(HOT_TOPICS):
        rows.append((rid, content, lambda s, i=i: 92.0 + (i % 6) if s == "C" else None,
                     0.01, 10 + i % 5, 40.0, "active"))
        queries.append(("recent_hot", probe, rid, None))

    for i, (rid, content, probe) in enumerate(OLD_IMPORTANT):
        rows.append((rid, content, lambda s, i=i: 55.0 + (i % 11) if s == "C" else None,
                     60.0, 3, 90.0, "crystallized"))
        queries.append(("old_important", probe, rid, None))

    for i, (rid, content, probe) in enumerate(COLD_RELEVANT):
        rows.append((rid, content, lambda s, i=i: 22.0 + (i % 7) if s == "C" else None,
                     90.0, 0, 30.0, "active"))
        queries.append(("cold_relevant", probe, rid, None))

    for i, (ra, ca, rb, cb, probe) in enumerate(CONFUSABLE_PAIRS):
        base = 50.0 + (i % 11)
        rows.append((ra, ca, lambda s, b=base: b if s == "C" else None, 10.0, 2, 40.0, "active"))
        rows.append((rb, cb, lambda s, b=base: b if s == "C" else None, 10.0, 2, 40.0, "active"))
        queries.append(("confusable", probe, ra, rb))

    for i in range(28):
        seed = _DISTRACTOR_SEEDS[i % len(_DISTRACTOR_SEEDS)]
        rows.append((f"distract{i:02d}", f"例行记录 {i:02d}：{seed}（备忘编号 {i:02d}）",
                     lambda s, i=i: 25.0 + (i * 37 % 51) if s == "C" else None,
                     (i % 40) + 1, i % 4, 30.0, "active"))

    return rows, queries


def state_temperature(temp_fn: Callable[[str], Optional[float]], state: str) -> float:
    """A=100 均匀 / B=60 均匀 / C=按角色塑形；未知状态回退 60。"""
    if state == "A":
        return 100.0
    if state == "B":
        return 60.0
    v = temp_fn(state)
    return v if v is not None else 60.0


def build_seeded_manager(
    db_path: str,
    state: str,
    rows: Optional[List[tuple]] = None,
) -> Tuple[MemoryManager, Dict[str, str], List[tuple]]:
    """建库 → 播种语料（SQL 批量改写温度/元数据）→ 分层装载。

    db_path 的父目录须已存在。rows 缺省用 build_corpus_specs() 的语料。
    注意：温度改写必须在全部 remember 完成后一次性提交——与 remember
    交错开第二条连接的未提交事务会把 manager 持久化锁死（database is
    locked，每行 33s 重试）。
    """
    from neurova.core.cancel_token import clearTurnCancelToken

    clearTurnCancelToken()
    if rows is None:
        rows, queries = build_corpus_specs()
    else:
        _, queries = build_corpus_specs()
    manager = MemoryManager(db_path=str(db_path), agent_id="dq", enable_buffer=False)
    role_to_id: Dict[str, str] = {}
    pending: List[tuple] = []
    now = datetime.now(timezone.utc)
    for rid, content, temp_fn, idle_days, access_count, importance, stage in rows:
        mem_id = manager.remember(
            content=content,
            memory_type="semantic" if stage == "crystallized" else "episodic",
            metadata={"chat_scope": "direct"},
        )
        role_to_id[rid] = mem_id
        la = (now - timedelta(days=idle_days)).isoformat()
        created = (now - timedelta(days=idle_days + 5)).isoformat()
        pending.append((state_temperature(temp_fn, state), la, access_count,
                        importance, stage, created, mem_id))
    conn = sqlite3.connect(str(manager._persist_db_path))
    for args in pending:
        conn.execute(
            "UPDATE memories SET temperature = ?, last_accessed_at = ?,"
            " access_count = ?, importance = ?, lifecycle_stage = ?,"
            " created_at = ? WHERE id = ?",
            args,
        )
    conn.commit()
    conn.close()
    # 以受控温度重载快照（热层/冷层分层装载）
    manager._load_from_db()
    return manager, role_to_id, queries


def make_engine(manager: MemoryManager):
    """构造生产同款融合召回引擎（传统通道，确定性打分）。"""
    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

    return NeurovaRecallEngine(memory_manager=manager, use_plugins=False)


def run_recall_queries(
    engine,
    queries: List[tuple],
    role_to_id: Dict[str, str],
    limit: int = 5,
    channels: Optional[List[Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """跑查询集并聚合 Hit@5 / MRR（整体 + 分类别）。"""
    per_cat: Dict[str, Dict[str, Any]] = {}
    for category, query, expected_rid, confusable_rid in queries:
        expected = role_to_id[expected_rid]
        result = engine.recall(query, limit=limit, channels=channels)
        recalled = [m.memory_id for m in result.recalled_memories[:limit]]
        hit = expected in recalled
        rank = recalled.index(expected) + 1 if expected in recalled else 0
        mrr = 1.0 / rank if rank else 0.0
        cat = per_cat.setdefault(category, {"hits": 0, "n": 0, "mrr_sum": 0.0, "pair_win": 0})
        cat["n"] += 1
        cat["hits"] += int(hit)
        cat["mrr_sum"] += mrr
        if confusable_rid:
            mate = role_to_id[confusable_rid]
            mate_rank = recalled.index(mate) + 1 if mate in recalled else 99
            cat["pair_win"] += int(bool(rank) and rank < mate_rank)

    metrics: Dict[str, Any] = {"hit5": 0, "mrr": 0.0, "n": 0}
    for category, agg in per_cat.items():
        agg["hit5_rate"] = agg["hits"] / agg["n"]
        agg["mrr"] = agg["mrr_sum"] / agg["n"]
        metrics[category] = dict(agg)
        metrics["hit5"] += agg["hits"]
        metrics["mrr"] += agg["mrr_sum"]
        metrics["n"] += agg["n"]
    metrics["hit5"] = metrics["hit5"] / metrics["n"]
    metrics["mrr"] = metrics["mrr"] / metrics["n"]
    return metrics, per_cat


def evaluate_state(
    db_path: str,
    state: str,
    drop_temperature_channel: bool = False,
    rows: Optional[List[tuple]] = None,
) -> Dict[str, Any]:
    """便捷入口：按状态建库播种 → 融合召回 → 指标。"""
    from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

    manager, role_to_id, queries = build_seeded_manager(db_path, state, rows)
    engine = make_engine(manager)
    channels = None
    if drop_temperature_channel:
        channels = [c for c in RecallChannel if c != RecallChannel.TEMPERATURE]
    metrics, _ = run_recall_queries(engine, queries, role_to_id, channels=channels)
    return metrics
