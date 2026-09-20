# -*- coding: utf-8 -*-
"""各家落盘方言 → Ingest Bundle 的转换器：一个模块一家。

新增一家 = 新建模块（末尾 register_handprint）+ 在 CONVERTERS 里登记一项；识别面与适配面
同名同处，不可能出现"认得出却无路可走"的指纹。
"""
from __future__ import annotations

from typing import Callable, Dict

from neurova.memory_ingest.converters import (codex_rollout, dialog_daily,
                                    legacy_session, opencode_session,
                                    qwenpaw_history)

CONVERTERS: Dict[str, Callable] = {
    qwenpaw_history.CONVERTER_NAME: qwenpaw_history.convert,
    dialog_daily.CONVERTER_NAME: dialog_daily.convert,
    legacy_session.CONVERTER_NAME: legacy_session.convert,
    opencode_session.CONVERTER_NAME: opencode_session.convert,
    codex_rollout.CONVERTER_NAME: codex_rollout.convert,
}
