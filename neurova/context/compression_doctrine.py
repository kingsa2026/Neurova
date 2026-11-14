# -*- coding: utf-8 -*-
"""压缩教义 —— 折叠摘要的成文质量纪律（B3，对照改进项）。

把"什么必须逐字保留、什么该丢、丢不起时按什么优先级"从单次 prompt 措辞
升级为**版本化、有覆盖门禁的规则资产**：规则文本随本模块单源演进，任何
宿主覆盖必须显式 `acknowledge_risk=True`——防止一处随手改措辞，全链路
摘要质量静默劣化（摘要丢了路径/签名/决策理由，事后检索与下钻全断）。

文本为本仓自研（中文），不搬运任何第三方教义文本；只吸收"分类学 +
版本化 + 覆盖门禁"的形制。与 `summarizing_compressor` 的防幻觉 factsheet
互补：教义管"留什么丢什么"，factsheet 管"留下来的标识符必须真实"。
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

#: 教义版本：规则文本变更时递增（读数/日志可对账"这份摘要是哪版规则写的"）。
DOCTRINE_VERSION = "1.0.0"

_COMPRESS_PHILOSOPHY = """压缩哲学：
- 折叠服务于当前任务，但要有节制：上下文容量宝贵，靠折叠已消费的内容省空间，不靠少用工具。
- 按需折叠，不按比例折叠；每次折叠只处理自上次折叠以来新增的、任务已消费完的增量。
- 摘要必须自足：后来者（包括未来的你）不回读原文也能接续任务。"""

_KEEP_RULES = """必须逐字保留（不改写、不缩写、不意译）：
- 完整文件路径与行号（如 src/index.ts:12-18、model.py:45），不得缩成裸文件名——裸名无法检索、无法下钻还原；
- 专有名词、版本号原文（不意译）；
- 函数/类/类型签名，以及承重代码行（那一行本身就是结论时，抄那一行，不只写"见某文件"）；
- 错误信息与堆栈原文——事后要靠原文串检索；
- 决策及其理由（用户已做的决定与偏好："选 X 弃 Y，因为 Z"——没有"因为"，决策看起来就像武断）；
- 精确值：配置键、阈值、魔数、数量、日期时间（"周三前"不得写成"近期"）；
- 用户意图与硬约束：范围、优先级、验收标准、禁做事项，不得走样；
- 目标及其演变：初始目标、中途转向及转向原因、当前目标——丢了演变，后续工作就成了无源之水；
- 开放事项：未完成/未解决的问题与待办，逐条带走，不得静默丢弃；
- 引用锚点：关键消息的轮次编号，便于日后凭它下钻还原原文。"""

_DROP_RULES = """应当丢弃（提取结论，丢掉外壳）：
- 已提取结果后的冗长日志与命令输出；
- 重复的文件读取与重复的状态检查；
- 已消费的探索过程——结论留下，过程丢掉；
- 死路探索——但必须留一行教训："试过 X，因 Y 失败"；
- 得出结论之前的往返讨论与自我修正（留结论，丢路程）。"""

_PRIORITY_RULES = """优先级（空间不足时按序保全，丢后面的保前面的）：
1. 用户总目标、目标演变与硬约束（丢这些等于换任务）；
2. 决策及理由；
3. 精确工件：路径、签名、错误原文、精确值；
4. 结论与关键发现；
5. 教训。"""

_OUTPUT_RULES = """输出形态：
- 连续中文摘要（不罗列、不解释规则本身）；
- 密集、可扫读；跨主题时按短小标题分组，便于读者跳到需要的部分；
- 丢弃的大件（脚本/报告/长输出）留一行内容描述（它覆盖什么，而非它在哪里）。"""

_DEFAULT_DOCTRINE: Dict[str, str] = {
    "philosophy": _COMPRESS_PHILOSOPHY,
    "keep": _KEEP_RULES,
    "drop": _DROP_RULES,
    "priority": _PRIORITY_RULES,
    "output": _OUTPUT_RULES,
}

#: 允许覆盖的段键（封闭集合；拼装顺序即此表顺序）。
DOCTRINE_SECTIONS = ("philosophy", "keep", "drop", "priority", "output")


def defaultDoctrine() -> Dict[str, str]:
    """规范教义文本（副本；调用方改动不影响单源）。"""
    return dict(_DEFAULT_DOCTRINE)


def renderDoctrine(sections: Optional[Mapping[str, str]] = None) -> str:
    """按段拼装教义文本（段序固定 = DOCTRINE_SECTIONS）。"""
    parts = sections or _DEFAULT_DOCTRINE
    return "\n\n".join(str(parts[key]) for key in DOCTRINE_SECTIONS if parts.get(key))


def resolveDoctrine(
    overrides: Optional[Mapping[str, str]] = None,
    *,
    acknowledge_risk: bool = False,
) -> Dict[str, str]:
    """合并覆盖项；任何覆盖都必须 `acknowledge_risk=True`，否则拒绝。

    教义各段都是承重件：改措辞可能让摘要丢路径/签名/决策理由，直接劣化
    事后检索与下钻。门禁与 `prompts` 治理同形制：要改，就显式认下风险。
    非字符串值的覆盖一律丢弃（坏部分不污染好默认）。
    """
    clean = {}
    for key, value in dict(overrides or {}).items():
        if key in _DEFAULT_DOCTRINE and isinstance(value, str) and value.strip():
            clean[key] = value
    if clean and not acknowledge_risk:
        raise ValueError(
            "覆盖压缩教义必须 acknowledge_risk=True；"
            f"涉及段：{sorted(clean)}。教义是质量承重件，改措辞会静默劣化摘要质量。"
        )
    merged = dict(_DEFAULT_DOCTRINE)
    merged.update(clean)
    return merged
