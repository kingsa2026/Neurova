# -*- coding: utf-8 -*-
"""压缩纪律·图像分档裁剪（reference_af 借鉴项 P1-6）——上下文分级裁剪。

S6 压缩纪律补充两条图像裁剪纪律，合成"分级裁剪"：

1. **「图像先于文本丢弃」**——窗口超预算时先摘旧消息的图像部件（换占位
   文本），文本轮不动：图像是窗口里固定计价最高（`IMAGE_PART_TOKENS`）、
   任务复用价值最低的载荷，能靠裁图回到预算内就不折叠文本。
2. **「长上下文模型只裁旧图」**——图像保留窗口按模型上下文窗口分档：
   长上下文模型只裁保留窗口之外的旧图，近期图像永不裁；窗口未知/短上下文
   按基础档（`model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN` 单源，调用时读）。

两条纪律共用一套"保留窗口"语义：最近 keep 窗条含图消息的图像永不裁，
窗口外的旧图从最旧起裁——与 `neurova/agent/image_retention.py` 的请求装配
防线同构。压缩侧是第二道防线：池归档/截图进上下文等上游变化可能带着更早
的图像部件进入折叠窗。

边界注记：池侧折叠（`context/orchestrator.py` 的 `_apply_window_budget` /
`manual_compact`）暂未启用裁图档——其覆盖账/防召回按消息内容指纹记账，
部件替换会扰动指纹对账；启用前需先把裁图事件接进对账口径，不在本批硬接。
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    # 注解名可被解析器/`get_type_hints` 看见；运行期仍走函数内惰性导入，
    # 依赖方向保持 压缩器 → 本模块（模块级导入会反向成环）。
    from neurova.context.window_compactor import WindowTokenMeter

# 单源读数：`MULTIMODAL_IMAGE_RETAIN_PER_TURN` 必须经模块属性在调用时读取
# （`from ... import` 值绑定会钉死 import 期快照，单源改值/测试 monkeypatch
# 都不再生效——见 tests/unit/agent/test_imageRetentionReadsSingleSource.py）。
from neurova.llm import model_limits

#: 长上下文模型判定线（上下文窗口 token，输入+输出总容量）：≥ 此值保留窗放宽一档
LONG_CONTEXT_WINDOW_TOKENS = 200_000

#: 超长上下文模型判定线：≥ 此值再放宽一档（只裁更旧的图）
ULTRA_LONG_CONTEXT_WINDOW_TOKENS = 1_000_000

#: 长上下文档：图像保留窗口（最近 N 条含图消息的图像部件原样保留）
LONG_CONTEXT_IMAGE_KEEP_WINDOW = 8

#: 超长上下文档：图像保留窗口
ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW = 16


def resolveImageKeepWindow(model_id: str) -> int:
    """按模型上下文窗口分档解析图像保留窗口（keep 窗，含图消息条数）。

    - 窗口未知或低于长上下文线 → 基础档（单源现值，不放宽）；
    - ≥ `LONG_CONTEXT_WINDOW_TOKENS` → 长上下文档；
    - ≥ `ULTRA_LONG_CONTEXT_WINDOW_TOKENS` → 超长上下文档。

    未知模型不猜档（fail-open 的反面：裁剪纪律宁紧勿松，多裁图不裁文本）。
    """
    window = model_limits.get_model_context_window(str(model_id or ""))
    if window is not None and int(window) >= ULTRA_LONG_CONTEXT_WINDOW_TOKENS:
        return ULTRA_LONG_CONTEXT_IMAGE_KEEP_WINDOW
    if window is not None and int(window) >= LONG_CONTEXT_WINDOW_TOKENS:
        return LONG_CONTEXT_IMAGE_KEEP_WINDOW
    return int(model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN)


def _isImagePart(part: typing.Any) -> bool:
    return isinstance(part, dict) and part.get("type") == "image_url"


def _imageMessageIndexes(messages: typing.List[dict]) -> typing.List[int]:
    """含图消息的下标序列（原顺序；只统计多模态分段 content）。"""
    indexes: typing.List[int] = []
    for i, msg in enumerate(messages):
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list) and any(_isImagePart(p) for p in content):
            indexes.append(i)
    return indexes


def _placeholderText() -> str:
    # 占位文案单源：与请求装配防线（image_retention）同一句——两道防线换下
    # 的占位在视图里同形，模型读到的语义一致。
    from neurova.agent.image_retention import IMAGE_OMITTED_PLACEHOLDER

    return IMAGE_OMITTED_PLACEHOLDER


def _stripImageParts(msg: dict) -> typing.Tuple[dict, int]:
    """把一条消息的图像部件换成占位文本（浅拷贝，不改原消息）。

    Returns:
        (新消息, 摘除的图像部件数)；无图像部件时返回原消息与 0。
    """
    content = msg.get("content")
    if not isinstance(content, list):
        return msg, 0
    newParts: typing.List[typing.Any] = []
    stripped = 0
    for part in content:
        if _isImagePart(part):
            newParts.append({"type": "text", "text": _placeholderText()})
            stripped += 1
        else:
            newParts.append(part)
    if not stripped:
        return msg, 0
    out = dict(msg)
    out["content"] = newParts
    return out, stripped


def stripImagesOverBudget(
    messages: typing.List[dict],
    budget_tokens: int,
    keep_window: int,
    meter: typing.Optional["WindowTokenMeter"] = None,
) -> typing.Tuple[typing.List[dict], typing.Dict[str, int]]:
    """第一档裁剪：窗口超预算时从最旧的窗口外含图消息起逐条摘图。

    - 只摘 keep 窗之外的旧图（`keep_window` 条最近的含图消息永不裁——
      「长上下文模型只裁旧图」）；文本轮永不触碰（「图像先于文本丢弃」）；
    - 无旧图可裁或已回到预算内即停——剩余缺口交给第二档（文本折叠）；
    - 计量经 `WindowTokenMeter` 单源（图像段按 `IMAGE_PART_TOKENS` 固定计价，
      与折叠判据同一把尺）；未传 meter 时自建一次性 meter；
    - 不就地改写调用方列表（返回新列表，被改写消息浅拷贝，与
      `image_retention.apply_image_retention` 同形）。

    Returns:
        (裁图后消息列表, stats)。stats：`images_stripped`（摘除的图像部件数）、
        `messages_touched`（被改写消息数）、`tokens_before`、`tokens_after`。
        未超预算或无图可裁时原样返回（零行为变化）。
    """
    working = list(messages or [])
    keep_window = max(0, int(keep_window or 0))
    budget = int(budget_tokens or 0)
    if meter is None:
        # 惰性引入：本模块不依赖压缩器模块（compact_window 总是自带 meter，
        # 这里只为独立调用兜底一把尺），依赖方向保持 压缩器 → 本模块。
        from neurova.context.window_compactor import WindowTokenMeter

        meter = WindowTokenMeter()

    tokensBefore = meter.total(working)
    stats = {
        "images_stripped": 0,
        "messages_touched": 0,
        "tokens_before": tokensBefore,
        "tokens_after": tokensBefore,
    }
    if budget <= 0 or tokensBefore <= budget:
        return working, stats

    # 每轮重定位含图消息并从最旧的窗口外一条摘起；working 以新列表对象推进，
    # meter 的整窗缓存按对象身份失效，读数始终是当前窗口的真值。
    while True:
        imageIndexes = _imageMessageIndexes(working)
        strippable = imageIndexes[: len(imageIndexes) - keep_window] if keep_window else imageIndexes
        if not strippable:
            break  # 窗口外已无旧图：诚实停下，剩余缺口交给文本折叠档
        target = strippable[0]
        strippedMsg, strippedCount = _stripImageParts(working[target])
        if not strippedCount:
            # 理论不可达（含图消息必有部件）；防死循环兜底
            break
        working = working[:target] + [strippedMsg] + working[target + 1:]
        stats["images_stripped"] += strippedCount
        stats["messages_touched"] += 1
        tokensAfter = meter.total(working)
        stats["tokens_after"] = tokensAfter
        if tokensAfter <= budget:
            break
    return working, stats
