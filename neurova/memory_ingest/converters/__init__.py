# -*- coding: utf-8 -*-
"""各家落盘方言 → Ingest Bundle 的转换器：一个模块一家。

新增一家 = 新建模块 + 在此登记，指纹由转换器自己向 probe 注册，识别面与适配面同名同处，
不会出现在 A 处能认出、B 处无路可走的两张皮。
"""
from __future__ import annotations

from typing import Callable, Dict

from neurova.memory_ingest.converters import qwenpaw_history

CONVERTERS: Dict[str, Callable] = {qwenpaw_history.CONVERTER_NAME: qwenpaw_history.convert}
