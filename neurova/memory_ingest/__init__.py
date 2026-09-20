# -*- coding: utf-8 -*-
"""外部 agent 数据导入：核心只认 Ingest Bundle，方言转换在 converters 里。

设计见 docs/specs/2026-09-20-external-agent-ingest-design.md。公开入口在 intake（Task 6
接入后再从此处再导出，避免包初始化依赖尚未存在的模块）。
"""
