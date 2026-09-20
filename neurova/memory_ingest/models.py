# -*- coding: utf-8 -*-
"""导入面的共享常量。

VALID_ORIGINS 从 MemoryOrigin 枚举导出而非另抄一份：闭集一旦在两处各写一遍，
就会漂成"第三份副本"那类缺陷（记忆信任级与检索权重同源，见 models.MemoryOrigin）。
"""
from neurova.cognitive_layers.memory_layer.models import MemoryOrigin

VALID_ORIGINS = frozenset(member.value for member in MemoryOrigin)
