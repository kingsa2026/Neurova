# -*- coding: utf-8 -*-
"""渠道入站媒体 → 附件单点：素材键与落地形态的单一定义处。

**刻意不接语音**（本仓的一条裁定，不是一次省略）：渠道语音已由 `voice_precheck` 在入队之前
转写，并把 ASR 真产物写进 `VOICE_CONTEXT_KEY`——那条读侧已被证明活着（网页音频附件也复用
同一个键）。把同一份字节再落成音频附件＝同一句话转写两遍，历史里同时留下「转写文本」与
「音频附件」两种形态，正是同功能两份实现。界线由
`tests/unit/channels/test_channelMediaLandsAsAttachments.py` 的反向判据钉住。

为什么要分两处动手：入站队列 `channel_ingress_queue` 落库时用 `default=str` 序列化 metadata，
字节键过队即变形；而"这一轮是谁"要到 `channel_router.resolveTurnIdentity` 才算得出来。
⇒ `stageInboundMedia` 在入队前只**挪位置不定属主**（字节→暂存路径字符串），
`landInboundMedia` 在属主已知处**登记**（暂存/本地路径→files_api 记录，随即清掉暂存副本）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 本地路径形态的入站素材键 → 允许的类型（wechat_ilink / wecom_aibot 解析后挂的就是这些键）。
#: 类型最终由服务端按文件名判定（`files_api._determine_file_type`），这里只声明"这键算素材"。
PATH_MEDIA_KEYS: Dict[str, str] = {
    "image_path": "image",
    "video_path": "video",
    "file_path": "file",
}

#: 字节形态的入站素材键（`wechat_kf` 用 `media_bytes` 同时承载图片/文件）。
BYTES_MEDIA_KEYS: tuple = ("media_bytes",)

#: 语音素材键：由预检转写，**不进附件路**（见模块文档串）。列出来是为了点名排除，
#: 免得后来人以为"漏了一个键"顺手加进来。
VOICE_MEDIA_KEYS: frozenset = frozenset({"audio_bytes"})

#: staging 产物键（字符串路径，过队列安全）。
STAGED_MEDIA_KEY = "staged_media_path"


def _stagedRoot() -> Path:
    from neurova.core.data_root import dataLanding

    root = dataLanding("tmp", "channel-media")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pathSegment(value: str) -> str:
    """把任意身份/作用域串压成一个能过路径段校验的**目录段**。

    渠道属主是 `ch:{渠道}:{发送者}`、会话作用域也是渠道拼出来的串，两者都天然带 `:`，
    而 P0 那道校验拒的正是穿越字符——照原样拒就等于渠道媒体永远落不了地。
    这里只换目录写法，不放宽校验：非安全字符逐个换成 `_`，**连续的点并成一枚**
    （`../../etc/passwd` 只换斜杠会得到 `.._.._etc_passwd`——`..` 原语还在，仍被那道校验拒掉，
    这是判据实测抓到的一格），再去掉首尾 `._-` 以满足「必须以字母数字开头」。
    记录里的属主字段仍存原值（`get_attachment_info` 按原值比属主）。
    """
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))
    cleaned = re.sub(r"\.{2,}", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or "unknown"


def mediaCandidates(metadata: Any) -> List[tuple]:
    """列出这一轮的入站素材 `(路径, 服务端类型)`。语音键一律不在此列。

    返回空表＝这条消息没有任何可落地的媒体素材（下游据此判断"纯媒体轮"还是"空消息"）。
    """
    if not isinstance(metadata, dict):
        return []
    candidates: List[tuple] = []
    for key, _allowed in PATH_MEDIA_KEYS.items():
        value = str(metadata.get(key) or "").strip()
        if value:
            candidates.append((value, ""))
    staged = str(metadata.get(STAGED_MEDIA_KEY) or "").strip()
    if staged:
        candidates.append((staged, ""))
    return candidates


def hasInboundMedia(metadata: Any) -> bool:
    """这一轮是否带着媒体素材（用于放开"正文为空即丢弃"那道总闸）。"""
    return bool(mediaCandidates(metadata))


def stageInboundMedia(message: Any) -> int:
    """把字节形态的素材先落成暂存文件，返回暂存条数。必须在入队之前调用。

    原字节键**不清空**——它在同进程里还有别的读者（知识入站）；这里只是另挂一个
    字符串键供属主已知的那一步登记，登记完由 `landInboundMedia` 删掉暂存副本。
    """
    metadata = getattr(message, "metadata", None)
    if not isinstance(metadata, dict):
        return 0

    staged = 0
    for key in BYTES_MEDIA_KEYS:
        data = metadata.get(key)
        if not isinstance(data, (bytes, bytearray)) or not data:
            continue
        declared = str(metadata.get("file_name") or "").strip()
        name = declared or f"{getattr(message, 'message_type', 'media') or 'media'}.bin"
        target = _stagedRoot() / f"{getattr(message, 'message_id', 'inbound')}_{Path(name).name}"
        try:
            target.write_bytes(bytes(data))
        except OSError as exc:
            logger.warning("渠道入站媒体暂存失败（%s）: %s", key, exc)
            continue
        metadata[STAGED_MEDIA_KEY] = str(target)
        staged += 1
    return staged


def landInboundMedia(
    *, metadata: Any, user_id: str, agent_id: str, session_id: str
) -> List[Dict[str, Any]]:
    """把入站素材登记成附件元数据，形状与 `console.attach_files` 那份逐字一致。

    下游 `ChatPipeline._step_inject_attachments` 只认这一种形状（图片→vision 切片、
    视频→抽帧、文档→抽文本），所以这里不新增字段也不换键名——两处两份表示就是双源。
    登记成功后删掉暂存副本，只留属主名下那一份。
    """
    candidates = mediaCandidates(metadata)
    if not candidates:
        return []

    from neurova.api.endpoints import files_api

    attachments: List[Dict[str, Any]] = []
    for source, _declaredType in candidates:
        path = Path(source)
        if not path.is_file():
            logger.warning("渠道入站媒体不在盘上，跳过登记: %s", source)
            continue
        try:
            info = files_api.persistBytes(
                user_id=_pathSegment(user_id), agent_id=_pathSegment(agent_id),
                session_id=_pathSegment(session_id),
                filename=path.name, data=path.read_bytes(), ownerId=user_id,
            )
        except files_api.FileRejection as rej:
            logger.warning("渠道入站媒体被落盘规则拒绝: %s → %s", path.name, rej.detail)
            continue
        except OSError as exc:
            logger.warning("渠道入站媒体读取失败: %s → %s", path.name, exc)
            continue

        attachments.append({
            "file_id": info["file_id"],
            "filename": info["filename"],
            "file_type": info["file_type"],
            "mime_type": info["mime_type"],
            "size": info["size"],
            "path": info["path"],
        })
        if str(source).startswith(str(_stagedRoot())):
            path.unlink(missing_ok=True)

    if attachments and isinstance(metadata, dict):
        metadata.pop(STAGED_MEDIA_KEY, None)
    return attachments
