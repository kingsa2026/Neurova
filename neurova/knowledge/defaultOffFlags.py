# -*- coding: utf-8 -*-
"""D 组默认关开关的**名册与委托**（升级计划 §13.1 D 组行 / §13.2 并入点 / §15.1「观测与开关」）。

边界只有一句：本模块**不读环境变量**。它登记"有哪几项、env 键叫什么、票面声明的默认态
是什么、住在哪个模块、现值找谁问"，现值一律由归属模块自己的谓词给出。
判据 `testRegistryNeverReadsEnvironmentItself` 用 AST 钉这一条——第二个读取点就是第二个
事实源（教义第 6 条），而九项各读各的正是这次要治的形态。

立这一份的因由：此前仓内没有任何一处能一次答出"这九项现在分别是什么态"，前端只能抄一张
静态表（`NeurUI/src/config/ontologyStatic.ts`），而且抄漏了 D-03——它的守卫断言写成
`rows.length == DEFAULT_OFF_ROWS.length`，漏一项照样绿。有了名册，读数面与前端表都从这儿取。

归属跨两层（八项在 knowledge/agent，D-16 的门控住在端点层），所以解点用**字符串引用＋
调用时刻解析**，不在本模块建立对 `api.endpoints` 的静态 import 边：登记面不该因为
谁在被登记而拖进整条装配链。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List

_RESOLVED: Dict[str, Callable[[], str]] = {}


@dataclass(frozen=True)
class DefaultOffFlag:
    """一行＝一项开关的登记内容。"""

    flagId: str
    envKey: str
    #: 票面声明的默认态（§13.1 那行的"默认值"列）。与实测现值是两件事，两样都要报。
    declaredDefault: str
    #: 归属模块（点分路径）＋解点属性名，合起来是"现值找谁问"。
    homeModule: str
    readoutRef: str
    #: 这一项在管什么（面板上的说明文本由 i18n 负责，这里只给工程注记）。
    note: str
    _cache: Dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def readout(self) -> Callable[[], str]:
        key = f"{self.homeModule}.{self.readoutRef}"
        fn = _RESOLVED.get(key)
        if fn is None:
            fn = getattr(importlib.import_module(self.homeModule), self.readoutRef)
            _RESOLVED[key] = fn
        return fn

    def mode(self) -> str:
        """现值形读数（"off" / "on" / "legacy" / "kreuzberg" 等，逐项形态由解点定）。"""
        return self.readout()


#: 顺序即面板顺序；与 §13.1 票面九项逐字对齐（少一项或多一项都由判据①当场红）。
DEFAULT_OFF_FLAGS: tuple = (
    DefaultOffFlag(
        flagId="D-01", envKey="NEUROVA_KB_QUERY_NORMALIZE", declaredDefault="off",
        homeModule="neurova.knowledge.query_normalization", readoutRef="normalizeMode",
        note="检索侧查询归一（别名/量词/单位），非法值回落 off"),
    DefaultOffFlag(
        flagId="D-02", envKey="NEUROVA_KB_AMBIGUITY_CLARIFY", declaredDefault="off",
        homeModule="neurova.knowledge.ambiguity_clarification", readoutRef="ambiguityMode",
        note="歧义澄清块注入"),
    DefaultOffFlag(
        flagId="D-03", envKey="NEUROVA_KB_MISS_CAPTURE", declaredDefault="off",
        homeModule="neurova.agent.knowledge_retriever_adapter", readoutRef="missCaptureMode",
        note="零命中查询落候选别名，只进人工审批面"),
    DefaultOffFlag(
        flagId="D-04", envKey="NEUROVA_KB_FACT_SURFACE", declaredDefault="off",
        homeModule="neurova.knowledge.foundation.read_surface", readoutRef="factSurfaceMode",
        note="事实读面（零锚点种子与治理富化；两池交织已被 011 否证，不重开）"),
    DefaultOffFlag(
        flagId="D-06", envKey="NEUROVA_CONDITION_CLASSES_ROUTE", declaredDefault="off",
        homeModule="neurova.knowledge.derivation_citation", readoutRef="conditionClassRouteMode",
        note="条件类推导进检索主路；注意逐规则 enforce 档会让单条结论在主路（v35，见 §12.6）"),
    DefaultOffFlag(
        flagId="D-08", envKey="NEUROVA_KB_DUAL_VECTOR", declaredDefault="off",
        homeModule="neurova.knowledge.vector_index", readoutRef="dualVectorMode",
        note="双通道向量（标题/正文各一条）"),
    DefaultOffFlag(
        flagId="D-11", envKey="NEUROVA_RETRIEVAL_FUSION", declaredDefault="off",
        homeModule="neurova.agent.retrieval_fusion", readoutRef="fusionMode",
        note="多路结果融合（RRF）"),
    DefaultOffFlag(
        flagId="D-16", envKey="NEUROVA_KB_EVENT_SUMMARY", declaredDefault="off",
        homeModule="neurova.api.endpoints.knowledge_common", readoutRef="eventSummaryMode",
        note="条目事件摘要写回并进索引输入（LLM 成本按条目）"),
    DefaultOffFlag(
        flagId="D-19", envKey="NEUROVA_KB_PARSER", declaredDefault="legacy",
        homeModule="neurova.knowledge.parser_shadow", readoutRef="parserMode",
        note="解析主路：legacy | kreuzberg_shadow | kreuzberg"),
)


def defaultOffReadings() -> List[Dict[str, str]]:
    """一次答完九项：登记态、现值、是否仍为默认态、归属与解点。

    不回传环境变量内容——只回"这一项是什么态"（读数面的判据⑤钉这一条）。
    """
    rows: List[Dict[str, str]] = []
    for flag in DEFAULT_OFF_FLAGS:
        mode = flag.mode()
        rows.append({
            "flagId": flag.flagId,
            "envKey": flag.envKey,
            "declaredDefault": flag.declaredDefault,
            "mode": mode,
            "isDefault": mode == flag.declaredDefault,
            "homeModule": flag.homeModule,
            "readoutRef": flag.readoutRef,
            "note": flag.note,
        })
    return rows
