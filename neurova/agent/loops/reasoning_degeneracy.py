# -*- coding: utf-8 -*-
"""思考流退化判据（单源）与增量守卫。

病根（2026-10-22 default 会话实测）：思考模型的 reasoning 通道会退化成**同一个短单元
无限连发**——那次是一条 `lock` 连发 16384 字符、正文 0 字、`finish_reason=length`，
垃圾原样流了 3 分 58 秒进前端思考面板。四道停止门都拦不到：门控在**轮末**才求值，
而退化发生在**一次调用内部**的 token 流上，等判到预算早被吃光了。

判据与节拍都只认这一份实现：`OpenAILoop` 流式、`AnthropicLoop` 流式、非流式存储三处
各拼一遍正则，就会漂移成"某条环的守卫恒不触发"（与 §6-77 的 usage 归一同形）。

口径：文本**尾部**由单一短单元连发构成的重复区，长度达到 `MIN_DEGENERACY_CHARS`
即判退化；重复区之前那段仍是可看的思考，展示/回放只取那一段。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# 阈值窗口：尾部连发区至少这么长才判退化。它显著大于正常思考里合理出现的复述
# （分隔线、省略号、同一个词换句式重述），又远小于事故那次的 16384 字符。
MIN_DEGENERACY_CHARS = 2048

# 重复单元长度上限：超过它就是**段落级**自我复述（内容问题），不是 token 级解码退化。
MAX_DEGENERACY_PERIOD = 32

# 复查节拍：累计每长出这么多字符再复查一次尾部，避免每片都全量扫描
DEGENERACY_CHECK_STRIDE = MIN_DEGENERACY_CHARS // 4


@dataclass(frozen=True)
class Degeneracy:
    """一次退化判定：`unit` 连发 `repeats` 次，从 `start` 起到文本末尾。"""

    unit: str
    start: int
    repeats: int
    chars: int


def findDegeneracy(text: str) -> Optional[Degeneracy]:
    """识别文本尾部的连发作废区；不成立返回 None。

    取**最小周期**：同一串 `locklock…` 报 `lock` 而不是 `locklock`，否则点名提示里
    写出来的"连发的是什么"就成了假事实。
    """
    if not text or len(text) < MIN_DEGENERACY_CHARS:
        return None

    best: Optional[Degeneracy] = None
    for period in range(1, min(MAX_DEGENERACY_PERIOD, len(text)) + 1):
        unit = text[-period:]
        start = len(text) - period
        repeats = 1
        while start - period >= 0 and text[start - period : start] == unit:
            start -= period
            repeats += 1
        chars = len(text) - start
        if chars >= MIN_DEGENERACY_CHARS and (best is None or chars > best.chars):
            best = Degeneracy(unit=unit, start=start, repeats=repeats, chars=chars)
    return best


def stripDegeneracy(text: str) -> "tuple[str, Optional[Degeneracy]]":
    """剥掉尾部作废区，返回（还能看的思考, 判定）。非流式存储面用这一份。"""
    found = findDegeneracy(text)
    if found is None:
        return text, None
    return text[: found.start], found


def noticeText(found: Degeneracy) -> str:
    """截断的点名提示（走前端已在用的 reasoning 通道，不静默吞掉）。"""
    unit = found.unit if len(found.unit) <= 12 else f"{found.unit[:12]}…"
    return f"\n[思考流退化：检测到「{unit}」连发 {found.repeats} 次，已截断本轮思考]\n"


#: 思考退化、而"关思考/降档"这条旋钮在这台网关上又发不出去时的收尾交代。
#: 文案单源在此——流式恢复路径与非流式恢复路径都要用同一句（两处各写一份迟早漂）。
#: 之所以不再重试：实测（2026-10-22 真网关）重试轮带着零思考控制重打，6 分钟后
#: 在同处又截断一次，多出来的预算正好被第二段连发吃掉。
FUTILE_THINKING_RETRY_NOTICE = (
    "⚠️ 思考过程出现退化（同一片段反复连发），且该服务商网关不支持关闭思考，"
    "已停止原地重试。建议改用非思考模型，或调低深度思考档位后重发。"
)


class ReasoningStreamGuard:
    """流式思考的增量守卫：累计分片、按节拍复查、判定后停止转发。

    `consume()` 是唯一的进料口：返回本次**应当转发**的文本片段列表（判定退化后恒为空，
    判定的那一次在原文后附上点名提示）。调用方据此决定是否终止这一次读取。
    """

    def __init__(self) -> None:
        self._parts: List[str] = []
        self._chars = 0
        self._lastChecked = 0
        self.found: Optional[Degeneracy] = None

    @property
    def aborted(self) -> bool:
        return self.found is not None

    @property
    def rawText(self) -> str:
        return "".join(self._parts)

    @property
    def cleanText(self) -> str:
        """作废区之前的思考——前端展示与记忆/回放落点只认这份。"""
        return self.rawText if self.found is None else self.rawText[: self.found.start]

    def reset(self) -> None:
        """429 重试的 reset：半截思考作废，判定节拍一并归零。"""
        self._parts.clear()
        self._chars = 0
        self._lastChecked = 0
        self.found = None

    def consume(self, piece: str) -> List[str]:
        if self.found is not None:
            return []
        self._parts.append(piece)
        self._chars += len(piece)
        forwarded = [piece]
        if self._chars < MIN_DEGENERACY_CHARS:
            return forwarded
        if self._chars - self._lastChecked < DEGENERACY_CHECK_STRIDE:
            return forwarded
        self._lastChecked = self._chars
        found = findDegeneracy(self.rawText)
        if found is None:
            return forwarded
        self.found = found
        forwarded.append(noticeText(found))
        return forwarded
