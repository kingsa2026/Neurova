# -*- coding: utf-8 -*-
"""外部 agent 数据导入：核心只认 Ingest Bundle，方言转换在 converters 里。

设计见 docs/specs/2026-09-20-external-agent-ingest-design.md。

包初始化只有一件事：导入 converters/，让各家指纹登记进 probe。这样 probe_store 单独
可用（不必先知道要导哪家），而"认得出却无路可走"的指纹不可能存在——指纹与转换器同名同处。
"""
__all__ = ("converters",)      # 导入即登记各家指纹

from neurova.memory_ingest import converters  # noqa: F401
