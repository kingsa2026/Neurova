# -*- coding: utf-8 -*-
"""入站语音的口径唯一定义处（教义第 6 条）。

原本只管"渠道用户发来的语音"进入统一消息之后下游按什么读它；转写超时与转写引擎
取法两项被网页音频附件复用后，一并收在这里——同一件事两处定义就是两个事实源。
出站侧的口径在 `voice_egress.py`。三个量此前各有一份：

- metadata 键名 `"audio_bytes"`：写在 `feishu.py`、`wechat_ilink.py`，读在
  `voice_precheck.py`——三处字面量，第四处（Telegram）一加就是第四份；
- 语音类型集合 `{"voice", "audio"}`：`voice_precheck.py` 自定义；
- 下载大小上限：`feishu.py` 自定义。

本批接第三个下载者（Telegram 的 `getFile` → 文件下载），先收口再造第二份。
另有一处同词不同物的不在本面：`neurova/agent_core.py` 里的 `audio_bytes` 读点服务的是
HTTP 上传路（它按 `metadata["media_type"]=="voice"` 分支，而渠道入站从不写那个键），
两条转写路是否合流另一次裁定（登记在台账本批那格）。
"""

from __future__ import annotations

#: 入站语音字节挂在 `ChannelMessage.metadata` 上的键（写入方＝各渠道适配器，读取方＝预转写）。
AUDIO_BYTES_KEY = "audio_bytes"

#: 被视为"语音"的消息类型：各平台原生标记不一（飞书 audio、其余多为 voice），下游同一口径处理。
INBOUND_VOICE_TYPES = frozenset({"voice", "audio"})

#: 转写成功前的正文占位——预转写成功会被真实文本替换；取不到字节时就以它进回合。
INBOUND_VOICE_PLACEHOLDER = "[语音]"

#: 单次入站语音的下载上限（声明长度与实际字节两道都按它判）。
VOICE_DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024

#: 一次语音转写的等待上限（秒）：群语音通常 <60s，本地 funasr 推理秒级；超时即降级。
#: 渠道预转写与网页音频附件转写共用这一个口径——两处各写一个 20 就是两个事实源，
#: 改一处另一处静默不一致（超时表现会因入口不同而莫名差别二十秒）。
TRANSCRIBE_TIMEOUT_SECONDS = 20.0


def getAsrTranscriber():
    """返回 ASR 转写协程函数：VoiceEngine 优先，降级 ASRManager（与 /audio/transcribe 同口径）。

    入站语音的两个转写者（渠道预检 `voice_precheck`、网页附件
    `agent/chat_pipeline`）都从这里取引擎，避免各接一份 ASR 装配。
    延迟导入，测试可 patch 本函数替换依赖。
    """
    from neurova.api.endpoints.audio import _get_asr_manager

    manager = _get_asr_manager()
    if manager is None or not hasattr(manager, "transcribe"):
        raise RuntimeError("ASR 不可用")
    return manager.transcribe
