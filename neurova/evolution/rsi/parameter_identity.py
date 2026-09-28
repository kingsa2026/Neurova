# -*- coding: utf-8 -*-
"""参数表身份守卫 —— 身份 = **物理落点唯一**，不是名字唯一（Issue #289 · 004）。

## 为什么按名字登记出过事

真账 `rsi_receipts.jsonl` 的 262 行里，每个 sleep 批次同时写下两行互相矛盾的记录：

```
{"parameter_path":"sleep.similarity_threshold","old_value":0.7,"new_value":0.72}
{"parameter_path":"sleep.merge_threshold",     "old_value":0.7,"new_value":0.74}
```

同一真实参数两个名字，同批各写一值（14 对 14，共 28 行永久留在账上）。
别名后来收成 property（`memory_layer/sleep.py`），**但没有任何守卫防止它复发**——
而 004 正要往这张表里加参数，所以守卫必须先于入表动作。

## 判据

`OPTIMIZABLE_PARAMETERS` 中每项解析到 `(宿主类, 属性真实落点)` 二元组，
**该二元组在整张表内唯一**。别名（property 写透到另一属性）必须被识别为
同一落点：

- 直连属性 ⇒ 落点是它自己；
- property 别名 ⇒ 落点是它 setter 里**真正写入的**那个属性名。

`property` 的真实落点靠解析 setter 的**字节码**得出（`STORE_ATTR` 的常量实参），
不靠执行 setter —— 执行会真的改对象状态，把一次静态检查变成一次有副作用的写入。
"""

from __future__ import annotations

import dis
from typing import Dict, Iterator, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 003 的负债记账必须存在的两列（入表前置条件的事实源）。
DEBT_COST_FIELD = "cost"
DEBT_REPAYMENT_FIELD = "repayment"


def resolve_physical_landing(host: type, name: str) -> str:
    """把 `(宿主类, 属性名)` 解析到**物理落点**属性名。

    返回的是"这个 setpoint 最终写到哪个属性上"：

    - 普通属性 / 实例属性 ⇒ 名字就是落点；
    - `property` ⇒ 解析 setter 字节码里的 `STORE_ATTR`，取它真正写入的属性名；
      解析不出（C 实现、闭包写、多层转发）时**如实返回属性名本身**并在日志里
      点名 —— 不许猜一个"看起来像真身"的名字，那会让守卫给出假绿。
    """
    descriptor = None
    for klass in getattr(host, "__mro__", (host,)):
        if name in vars(klass):
            descriptor = vars(klass)[name]
            break
    if isinstance(descriptor, property):
        landing = _landing_of_property(descriptor)
        if landing is not None:
            return landing
        logger.debug("property %s.%s 的真实落点解析不出，退回属性名本身", host, name)
    return name


def _landing_of_property(descriptor: property) -> Optional[str]:
    """解析 property setter 写入的属性名（读 setter 的 `STORE_ATTR` 字节码）。"""
    setter = descriptor.fset
    if setter is None:
        return None
    targets: List[str] = []
    try:
        for instruction in dis.get_instructions(setter):
            if instruction.opname in {"STORE_ATTR", "STORE_FAST", "STORE_NAME"}:
                if isinstance(instruction.argval, str):
                    targets.append(instruction.argval)
    except TypeError:  # pragma: no cover - C 实现的 setter 无法反汇编
        return None
    # setter 里最后一个赋值即最终落点（中间可能有临时变量赋值）。
    return targets[-1] if targets else None


def parameter_hosts() -> Dict[str, type]:
    """参数表各系统的**宿主类**单一事实源（守卫与编排器共用，不各写一份）。"""
    from neurova.evolution.rsi.orchestrator import parameter_host_classes

    return parameter_host_classes()


def iter_parameter_landings(
    table: Optional[Dict[str, List[Dict[str, str]]]] = None,
    hosts: Optional[Dict[str, type]] = None,
) -> Iterator[Tuple[str, str, str]]:
    """逐项产出 `(system, name, 物理落点)`。

    `table` / `hosts` 可注入，供构造样本反证守卫不恒绿。
    """
    if table is None:
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

        table = RSIIntegrationManager.OPTIMIZABLE_PARAMETERS
    if hosts is None:
        hosts = parameter_hosts()
    for system_name, params in table.items():
        host = hosts.get(system_name)
        for param in params:
            name = param["name"]
            landing = resolve_physical_landing(host, name) if host is not None else name
            yield system_name, name, landing


def duplicate_physical_landings(
    table: Optional[Dict[str, List[Dict[str, str]]]] = None,
    hosts: Optional[Dict[str, type]] = None,
) -> List[str]:
    """同一物理落点被表里多于一项占用的清单（空列表 = 身份唯一）。"""
    seen: Dict[Tuple[str, str], List[str]] = {}
    for system_name, name, landing in iter_parameter_landings(table, hosts):
        seen.setdefault((system_name, landing), []).append(name)
    return [
        f"{system}.{landing} ← {sorted(names)}"
        for (system, landing), names in sorted(seen.items())
        if len(names) > 1
    ]


def debt_accounting_present() -> bool:
    """003 的负债记账是否已落地（**入表前置条件**的事实源）。

    只认两件事：负债账本模块可导入，且回执行形态里带 `cost` / `repayment` 两列名。
    任一缺失即判"记账不存在" —— 那正是工单 018 `_is_placeholder` 修过的
    "棘轮奖励自己编辑空对象"的第二形态。
    """
    try:
        from neurova.evolution.rsi.debt_ledger import RECEIPT_FIELDS
    except Exception as e:  # noqa: BLE001 - 记账面不可用即判不存在，不猜
        logger.debug("负债记账面不可用: %s", e)
        return False
    return admits_into_table(
        cost_field=DEBT_COST_FIELD if DEBT_COST_FIELD in RECEIPT_FIELDS else None,
        repayment_field=DEBT_REPAYMENT_FIELD if DEBT_REPAYMENT_FIELD in RECEIPT_FIELDS else None,
    )


def admits_into_table(*, cost_field: Optional[str], repayment_field: Optional[str]) -> bool:
    """入表前置判据：该参数是否已有记账。

    两个字段都齐才准入 —— 缺一个就是"代价记了、偿还记不了"的半截账，
    半截账会让反向闸在"还了没"这件事上永久失明。
    """
    return cost_field == DEBT_COST_FIELD and repayment_field == DEBT_REPAYMENT_FIELD
