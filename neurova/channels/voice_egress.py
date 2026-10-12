# -*- coding: utf-8 -*-
"""渠道语音出站契约（单点定义处）。

为什么要有这个模块：出站"能不能发语音、以什么形态发"此前没有一处说法——传输层
`manager.send_message(message_type=...)` 早就支持类型化回发（且 `base.py` 契约与各适配器
签名齐备，由 `test_b4_gen1_send_signature.py` 钉着），但回合生成的 `audio_path` 在
`channel_router` 就被丢掉，回发也只发文本。补这条链时如果每个适配器各自判"我支持什么"，
就会长出第二份词汇表（P2 那次给插件造出与 `skills/permissions.py` 并列的第二份权限词汇，
同族教训）。故形态、判定与回发项类型都只在此处定义一次。

三种形态按"平台侧到底能收什么"分：
- `none`：渠道不支持音频出站 ⇒ 只回文本，且**必须点名丢弃**（静默丢弃就是本批根修的形态）。
- `audio_file`：平台能收音频文件（上传后以文件消息发出），用户可点开播放。
- `voice_bubble`：平台原生语音气泡（需平台指定的编码/时长约束，如飞书要 opus）。

默认 `none` 是安全侧：声明能力必须有真出口，`TestDeclaredCapabilityMustBeImplemented`
按 AST 验这一点——置个标志就当支持，比不发更坏（它让"这条渠道能收语音"成为假事实）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

VOICE_OUT_NONE = "none"
VOICE_OUT_AUDIO_FILE = "audio_file"
VOICE_OUT_VOICE_BUBBLE = "voice_bubble"

VOICE_OUT_MODES = (VOICE_OUT_NONE, VOICE_OUT_AUDIO_FILE, VOICE_OUT_VOICE_BUBBLE)

#: 回发语音时交给适配器的 message_type 值（适配器据此走自己的上传/发送分支）。
VOICE_MESSAGE_TYPE = "voice"


@dataclass
class VoiceReply:
    """一条"语音回发项"：与文本条并列出现在 handler 返回值里，由 manager 按渠道能力落地。

    只带本地路径，不带字节——音频可达数 MB，塞进消息对象会让 handler 链上的日志/快照
    把它整份打印出来；适配器发送时按路径读。
    """

    file_path: str
    # 回合文本（供不支持音频的渠道留档/日志对照；不参与发送）
    paired_text: str = ""

    def __str__(self) -> str:  # 防止被误当字符串直接发出
        return f"<VoiceReply {os.path.basename(self.file_path)}>"


def turnAudioCandidate(audio_path: Optional[str], paired_text: str = "") -> Optional[VoiceReply]:
    """第一道闸（回合侧）：只认"真在位且非空"的音频文件。

    渠道无关——`channel_router` 拿到 `resp["audio_path"]` 时用这一道；它不该、也无法
    知道目标渠道能不能收音频（适配器实例在 manager 手里）。
    """
    if not audio_path:
        return None
    try:
        if not os.path.isfile(audio_path) or os.path.getsize(audio_path) <= 0:
            return None
    except OSError:
        return None
    return VoiceReply(file_path=str(audio_path), paired_text=paired_text or "")


def resolveVoiceReply(
    audio_path: Optional[str],
    voice_out_mode: str,
    paired_text: str = "",
) -> Optional[VoiceReply]:
    """第二道闸（渠道侧）：能力不支持一律 None。

    两道闸分开是为了让"被丢弃"这件事发生在**有适配器实例、能写清渠道名**的地方——
    在回合侧丢弃就只能静默吞掉（今天正是这一形）。
    """
    if voice_out_mode not in (VOICE_OUT_AUDIO_FILE, VOICE_OUT_VOICE_BUBBLE):
        return None
    return turnAudioCandidate(audio_path, paired_text)


def isVoiceReply(item) -> bool:
    """回发项是否语音项——供 manager 的分派循环用，避免各处 isinstance import 散开。"""
    return isinstance(item, VoiceReply)
