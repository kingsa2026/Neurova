"""截图进模型上下文的**闸门与归一化单源**（T-09 · D-4）。

两条 loop（OpenAI 兼容环 / Anthropic 环）只在**切片形状**上不同：
- OpenAI 用 `{"type":"image_url","image_url":{"url":"data:<mime>;base64,…"}}`；
- Anthropic 用 `{"type":"image","source":{"type":"base64","media_type":…,"data":…}}`。

三闸与图片归一化必须只有一份：两环各写一份，迟早漂移成"某条环给图、另一条不给"的
分裂读数，而那正是最难查的一类（教义第 6 条）。所以本模块持有判定，loop 只做形状装配。

三道闸（缺一不可，顺序即口径）：
① 本轮有**具名感知缺口**——快照类工具失败；文本事实够用就走文本，这是分层兜底不是每步喂图；
② 视觉能力读数为 `available`（T-07 的 `capability_state` 单源；`unknown`/`not-configured`
   都不给——为一个不知道支不支持图的模型付 base64）；
③ 本轮还没给过（`MAX_PERCEPTION_IMAGES_PER_TURN`）。

`peek` 与 `commit` 分家：先确认图片能归一化成功再决定消费，否则"取走了却挂不上"
会把本轮后面真需要图的机会饿掉。
"""
import base64
import typing

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 指令与图同生命周期：只活在这一次请求里，不进历史（2026-09-09 图片串台事故的形状）。
PERCEPTION_INSTRUCTION_TEXT = (
    "[本轮附上的图片是屏幕/页面的当前实际画面，"
    "上一轮的结构化快照没拿到事实，请结合图片继续]"
)
PERCEPTION_ATTACH_REASON = "快照类感知具名失败，且本轮尚未附过图"


def claimTurnPerception() -> typing.Optional[typing.Dict[str, typing.Any]]:
    """三闸全开且图片归一化成功时给出载荷，否则 None（**不消费槽**）。"""
    from neurova.core import turn_context as _tc

    if _tc.turnPerceptionGivenCount() >= _tc.MAX_PERCEPTION_IMAGES_PER_TURN:
        return None
    gapTools = _tc.turnPerceptionGapTools()
    if not gapTools:
        return None

    from neurova.computer_use.capability_state import CAP_AVAILABLE, reading

    if reading("vision").state != CAP_AVAILABLE:
        return None

    image = _tc.peekTurnPerceptionImage()
    if not image:
        return None
    normalized = _normalizeToBytes(image)
    if normalized is None:
        return None
    data, mime = normalized
    return {
        "gapTool": gapTools[-1],
        "imageTool": image.get("toolName") or "",
        "bytes": data,
        "mime": mime,
    }


def commitTurnPerception(agent: typing.Any, offer: typing.Dict[str, typing.Any]) -> None:
    """挂上图之后才消费槽，并在事件面留痕——静默兜底最难查。"""
    from neurova.core import turn_context as _tc

    taken = _tc.takeTurnPerceptionImage()
    append = getattr(agent, "append_tool_event", None)
    if not callable(append):
        return
    append({
        "type": "perception_image",
        "gapTool": offer.get("gapTool", ""),
        "imageTool": (taken or {}).get("toolName") or offer.get("imageTool", ""),
        "reason": PERCEPTION_ATTACH_REASON,
    })


def _normalizeToBytes(image: typing.Dict[str, typing.Any]) -> typing.Optional[typing.Tuple[bytes, str]]:
    """base64 → 归一化后的 (字节, mime)。超闸门的图先降采样，挡 provider 413。"""
    try:
        from neurova.attachment_parser import normalize_image_for_llm

        raw = base64.b64decode(image.get("base64") or "")
        return normalize_image_for_llm(raw, image.get("mime") or "image/png")
    except Exception as e:  # noqa: BLE001 - 挂不上图就让这一轮照旧走文本事实
        logger.warning("感知截图归一化失败（本轮不附图）: %s", e)
        return None
