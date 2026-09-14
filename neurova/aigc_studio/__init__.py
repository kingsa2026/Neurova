# -*- coding: utf-8 -*-
"""创作专区后端域（aigc_studio，2026-09-14 R3）。

功能规格对标 huobao-drama（CC BY-NC-SA 4.0：仅功能对齐，代码自研）：
小说 → 分集剧本 → 角色/场景/道具资产（定妆一致性 seed、@引用参考图）→
分镜 → 批量首帧/图生视频（账本 batch_key 关联，重启恢复收口）→
旁白 TTS / SRT 字幕 → FFmpeg 合并或连播清单导出。

生成通道全部复用批次0/1 单源：llm.generators.protocols（实测协议矩阵）、
runtime（凭据/落盘/本地化）、task_ledger + recovery（未决任务重启续拉）。
"""

from neurova.aigc_studio.store import (
    StudioStore, get_store, reset_store,
)

__all__ = ["StudioStore", "get_store", "reset_store"]
