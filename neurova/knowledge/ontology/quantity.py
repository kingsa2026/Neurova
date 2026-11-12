"""量值唯一解析/归一/比较实装（specs/2026-11-12 §3 W1）。

数值 qualifier 的判据单源：validation 数值判、admission 写入口归一、函数层
selector 聚合、抽取 prompt 数值引导，四处全部消费本模块——任何一处自己再写
一份单位表或解析正则，就是第二事实源（通则 6）。

- **解析**：`parseQuantity`——"200MB"/"2.5GB"/"3亿"/"12kg"/"45%" →
  `{value, unit, dimension, multiplier}`；解析失败返回 None（诚实，不猜）。
- **归一**：`normalizeTo`——同维换算到目标单位；跨维/未知单位/跨币种返回 None。
- **比较**：`compareQuantity`——归一后比大小；不可比返回 None。
- 单位表是**数据**（模块内常量闭集，通则 2）：新增单位改表不改代码。

歧义消解：单字母大小写敏感（`M`=兆计数、`m`=米；`G`=十亿计数、`g`=克；
`T`=万亿计数、`t`=吨）；多字符单位 casefold 匹配。裸 `K/M/G/T` 按业务计数
倍率读，数据量单位必须带 `B`（`KB/MB/GB`）。货币只做同币族固定倍率（万/亿），
汇率换算明确不做。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: 大小写敏感的单字母单位（歧义消解：先按原样精确匹配）
CASE_SENSITIVE_UNITS: Dict[str, Tuple[str, float]] = {
    "M": ("count", 1e6), "G": ("count", 1e9), "T": ("count", 1e12),
    "K": ("count", 1e3),
    "m": ("length", 1.0), "g": ("mass", 1.0), "t": ("mass", 1e6),
    "s": ("time", 1.0), "h": ("time", 3600.0), "d": ("time", 86400.0),
    "B": ("data", 1.0), "b": ("data", 1.0),
}

#: 多字符单位（casefold 匹配）：{单位名: (维, 折算到基准单位的倍率)}
UNITS: Dict[str, Tuple[str, float]] = {
    # 数据量（基准 B）
    "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9),
    "tb": ("data", 1e12), "pb": ("data", 1e15),
    "kib": ("data", 1024.0), "mib": ("data", 1024.0 ** 2),
    "gib": ("data", 1024.0 ** 3), "tib": ("data", 1024.0 ** 4),
    "字节": ("data", 1.0),
    # 计数倍率（基准 count）
    "k": ("count", 1e3), "万": ("count", 1e4), "亿": ("count", 1e8),
    "count": ("count", 1.0),
    # 长度（基准 m）
    "mm": ("length", 1e-3), "cm": ("length", 1e-2), "km": ("length", 1e3),
    "米": ("length", 1.0), "公里": ("length", 1e3),
    # 质量（基准 g）
    "mg": ("mass", 1e-3), "kg": ("mass", 1e3),
    "吨": ("mass", 1e6), "克": ("mass", 1.0), "千克": ("mass", 1e3),
    # 时间（基准 s）
    "sec": ("time", 1.0), "min": ("time", 60.0),
    "秒": ("time", 1.0), "分": ("time", 60.0), "小时": ("time", 3600.0),
    "天": ("time", 86400.0),
    # 比率（基准 %）
    "%": ("ratio", 1.0), "percent": ("ratio", 1.0),
    # 货币（同币族固定倍率；跨币种换算明确不做）
    "元": ("currency", 1.0), "万元": ("currency", 1e4), "亿元": ("currency", 1e8),
    "美元": ("currency", 1.0), "usd": ("currency", 1.0), "$": ("currency", 1.0),
}

#: 货币族（跨族换算拒绝）：表外币种解析为 generic，不臆测汇率
CURRENCY_FAMILIES = {"元": "cny", "万元": "cny", "亿元": "cny",
                     "美元": "usd", "usd": "usd", "$": "usd"}

#: 各维的基准单位名（写入口归一的目标形态）
BASE_UNITS = {"data": "B", "count": "count", "length": "m", "mass": "g",
              "time": "s", "ratio": "%"}

_NUMBER_RE = re.compile(r"^([0-9][0-9,]*(?:\.[0-9]+)?|[0-9]*\.[0-9]+)\s*(.*)$")


def _resolveUnit(unitRaw: str) -> Optional[Tuple[str, float]]:
    """单位词形 → (维, 倍率)：单字母先按原样精确匹配，再 casefold 查多字符表。"""
    if unitRaw in CASE_SENSITIVE_UNITS:
        return CASE_SENSITIVE_UNITS[unitRaw]
    return UNITS.get(unitRaw.casefold())


def parseQuantity(text: Any) -> Optional[Dict[str, Any]]:
    """解析量值文本 → `{value, unit, dimension, multiplier}`；失败返回 None。

    - 纯数值/表外词形 → dimension=generic（unit 如实保留，不换算不臆测）；
    - 表内单位 → 该维＋倍率；非数字开头/空/纯词形 → None。
    """
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return {"value": float(text), "unit": "", "dimension": "generic",
                "multiplier": 1.0}
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = raw.replace(",", "").replace("，", "")
    match = _NUMBER_RE.match(raw)
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unitRaw = match.group(2).strip()
    if not unitRaw:
        return {"value": value, "unit": "", "dimension": "generic",
                "multiplier": 1.0}
    entry = _resolveUnit(unitRaw)
    if entry is None:
        return {"value": value, "unit": unitRaw, "dimension": "generic",
                "multiplier": 1.0}
    dimension, multiplier = entry
    return {"value": value, "unit": unitRaw, "dimension": dimension,
            "multiplier": multiplier}


def normalizeTo(value: Any, unit: str, targetUnit: str) -> Optional[float]:
    """同维换算到目标单位；跨维/未知单位/跨币种/非数值返回 None（诚实不猜）。"""
    if isinstance(value, str):
        parsed = parseQuantity(value)
        if parsed is None:
            return None
        number = float(parsed["value"])
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    else:
        return None
    src = _resolveUnit(str(unit or "").strip())
    dst = _resolveUnit(str(targetUnit or "").strip())
    if src is None or dst is None or src[0] != dst[0]:
        return None
    if src[0] == "currency":
        familySrc = CURRENCY_FAMILIES.get(str(unit or "").strip())
        familyDst = CURRENCY_FAMILIES.get(str(targetUnit or "").strip())
        if familySrc is None or familyDst is None or familySrc != familyDst:
            return None
    return number * src[1] / dst[1]


def compareQuantity(a: Optional[Dict[str, Any]],
                    b: Optional[Dict[str, Any]]) -> Optional[int]:
    """比较两个 parseQuantity 产物：-1/0/1；不同维/generic/任一缺席 → None。"""
    if a is None or b is None:
        return None
    if a.get("dimension") != b.get("dimension") or a.get("dimension") == "generic":
        return None
    av = float(a["value"]) * float(a.get("multiplier", 1.0))
    bv = float(b["value"]) * float(b.get("multiplier", 1.0))
    return -1 if av < bv else (1 if av > bv else 0)


def canonicalQuantity(text: Any) -> Optional[Dict[str, Any]]:
    """写入口归一形态：解析后折到基准单位 `{value, unit, dimension}`。

    generic 维（表外单位/纯数值）不折算，如实保留原词形——归一只做表内
    确定性换算，不做任何臆测。
    """
    parsed = parseQuantity(text)
    if parsed is None:
        return None
    dimension = parsed["dimension"]
    if dimension in BASE_UNITS:
        return {"value": float(parsed["value"]) * float(parsed["multiplier"]),
                "unit": BASE_UNITS[dimension], "dimension": dimension}
    return {"value": float(parsed["value"]), "unit": parsed["unit"],
            "dimension": dimension}


def canonicalQualifier(text: Any) -> Optional[Dict[str, Any]]:
    """admission 写入口消费的入口名（与 canonicalQuantity 同一实装）。"""
    return canonicalQuantity(text)


def numericQualifierKeys(term: Optional[Dict[str, Any]]) -> List[str]:
    """术语 qualifier_schema 里声明为数值的键（`{"type": "number"}` 或 `"number"`）。

    单点判据：validation 数值判、admission 归一、graph_bridge prompt 引导
    三处共用；未声明 schema / term 缺席 → 空（存量零漂移）。
    """
    schema = (term or {}).get("qualifier_schema") or {}
    allowed = schema.get("allowed") or {}
    keys: List[str] = []
    for key, spec in allowed.items():
        declared = spec.get("type") if isinstance(spec, dict) else spec
        if str(declared or "").casefold() == "number":
            keys.append(str(key))
    return sorted(keys)
