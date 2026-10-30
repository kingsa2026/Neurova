# -*- coding: utf-8 -*-
"""读侧守卫族（specs/2026-10-30）。

- `answer_fact_guard`：生成后句级事实回查（W5）——只标记不改写。
"""

from .answer_fact_guard import GuardReport, guardMode, runAnswerFactGuard

__all__ = ["GuardReport", "guardMode", "runAnswerFactGuard"]
