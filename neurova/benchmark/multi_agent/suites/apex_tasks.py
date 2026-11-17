# -*- coding: utf-8 -*-
"""APEX 式 T3 量规任务集（P3-3，评测报告 G-12 后续扩充）。

财务/分析族的**结构量规**任务：判据仍是切面断言（报告须含的量规小节/要素标记），
不评判观点优劣——与 seed_tasks 的最小切面同一条纪律。任务面取投资银行分析场景
（对照 Mercor APEX 投行分析基准的任务形态）：估值、可比、并购、授信、LBO、
财报解读、IPO、尽调、董事会备忘录，外加一条 T3 不可解题（防"永远尝试"刷分）。

登记入口统一走 `suites.registerBuiltinSuites()`（幂等），不在此自行注册。
"""
from __future__ import annotations

from neurova.benchmark.multi_agent.suites.seed_tasks import markerChecker
from neurova.benchmark.multi_agent.tasks import BenchmarkTask


def _t3(taskId: str, prompt: str, markers, description: str = "",
        unsolvable: bool = False, infeasibleMarker: str = "") -> BenchmarkTask:
    return BenchmarkTask(
        task_id=taskId,
        suite="t3_rubric",
        prompt=prompt,
        check=markerChecker(tuple(markers), infeasibleMarker=infeasibleMarker),
        unsolvable=unsolvable,
        description=description,
    )


APEX_TASKS = (
    _t3(
        "t3-rubric-dcf-valuation",
        "为一家年营收 8 亿元、增速 25% 的 SaaS 公司搭建 DCF 估值框架，"
        "输出须分【自由现金流预测】【折现率 WACC】【终值计算】【敏感性分析】四节。",
        ("【自由现金流预测】", "【折现率 WACC】", "【终值计算】", "【敏感性分析】"),
        "DCF 估值框架四要素",
    ),
    _t3(
        "t3-rubric-comparables",
        "给出可比公司分析：说明【可比公司选取】标准，列示【估值倍数】（EV/EBITDA、P/E），"
        "讨论目标公司相对的【溢价折价】，并给出【结论区间】。",
        ("【可比公司选取】", "【估值倍数】", "【溢价折价】", "【结论区间】"),
        "可比公司分析四要素",
    ),
    _t3(
        "t3-rubric-ma-thesis",
        "撰写一项并购交易的投行论证：含【交易逻辑】【战略协同】【估值区间】【交易结构】【整合风险】。",
        ("【交易逻辑】", "【战略协同】", "【估值区间】", "【交易结构】", "【整合风险】"),
        "并购论证五要素",
    ),
    _t3(
        "t3-rubric-credit-memo",
        "为一名申请流动资金贷款的制造业企业写授信备忘录：含【借款人概况】【偿债能力】【担保结构】【信用评级建议】。",
        ("【借款人概况】", "【偿债能力】", "【担保结构】", "【信用评级建议】"),
        "授信备忘录四要素",
    ),
    _t3(
        "t3-rubric-lbo-model",
        "概述 LBO 杠杆收购测算框架：含【资金结构】【杠杆倍数】【退出假设】【IRR 测算】【债务偿还路径】。",
        ("【资金结构】", "【杠杆倍数】", "【退出假设】", "【IRR 测算】", "【债务偿还路径】"),
        "LBO 测算五要素",
    ),
    _t3(
        "t3-rubric-earnings-review",
        "解读一份上市公司季报并输出电话会要点：含【业绩概览】【盈利质量】【管理层指引】【风险提示】。",
        ("【业绩概览】", "【盈利质量】", "【管理层指引】", "【风险提示】"),
        "财报解读四要素",
    ),
    _t3(
        "t3-rubric-ipo-memo",
        "为拟 IPO 企业写发行备忘录摘要：含【公司概况】【募资用途】【估值讨论】【承销安排】。",
        ("【公司概况】", "【募资用途】", "【估值讨论】", "【承销安排】"),
        "IPO 备忘录四要素",
    ),
    _t3(
        "t3-rubric-due-diligence",
        "为一项股权投资设计尽调方案：含【财务尽调】【法律尽调】【商业尽调】【关键风险清单】。",
        ("【财务尽调】", "【法律尽调】", "【商业尽调】", "【关键风险清单】"),
        "尽调方案四要素",
    ),
    _t3(
        "t3-rubric-board-memo",
        "起草一份提请董事会审议对外投资的备忘录：含【议案背景】【财务影响】【替代方案】【决策建议】。",
        ("【议案背景】", "【财务影响】", "【替代方案】", "【决策建议】"),
        "董事会备忘录四要素",
    ),
    _t3(
        "t3-rubric-infeasible-price",
        "在未提供该公司任何财务数据与市场参数的情况下，精确预测其三年后 IPO 发行价，"
        "保留两位小数（以元计）。",
        (),
        "不可解题：应声明不可行而非编造精确价格",
        unsolvable=True,
        infeasibleMarker="不可行",
    ),
)
