"""shell 命令分段解析器（OpenClaw 启发 P0-6 exec 命令分段审批）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-6 / §2.5）：
  OpenClaw 的 exec 审批把 shell 命令解析成候选段（pipeline、&& 链、
  inline command 全拆开）逐段匹配白名单或要求人工审批——"白名单命令 +
  注入段"无法搭便车。Neurova 的 governance.match_whitelist 对整条命令
  做前缀匹配且优先于内容检测，``ls && evil`` 会命中前缀 ``ls`` 直接
  ALLOW——分段审批要堵的正是这个洞。

解析语义（保守、防绕过优先）：
  - 切分顺序：先按 && / || / ; / | 切段，再剥每段的引号内联命令
    （$( )、` `、>( ) 之类不做递归展开——含任何子命令痕迹即整段上报）。
  - 段 = 可执行词序列的首 token + 原文本（首 token 用于白名单前缀匹配）。
  - 解析器只负责"切"，不裁决；裁决在 governance（全部段命中白名单才
    放行，任一段未命中 → 保持原整串走内容检测/审批）。
  - 引号内的 && ; | 不是分隔符（shlex 感知引号）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CommandSegment:
    """一个候选段：白名单匹配用 head，展示/审计用 text。"""

    text: str  # 原始段文本（strip 后）
    head: str  # 段首可执行词（用于前缀/精确匹配）
    connector: str = ""  # 与前段的连接符（""/&&/||/;/|）
    quoted: bool = False  # 段整体是否处于引号内（inline 提取物）

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "head": self.head,
            "connector": self.connector,
            "quoted": self.quoted,
        }


def _split_top_level(command: str, seps: str) -> List[str]:
    """按 seps 中的单字符分隔符切段；引号感知，引号内不切。

    字符级扫描跟踪引号/转义状态；引号不平衡时引号保持开启，
    引号内分隔符一律不切（保守：宁整段裁决不误切）。
    """
    quote: Optional[str] = None
    esc = False
    buf_chars: List[str] = []
    segments: List[str] = []
    for ch in command:
        if esc:
            buf_chars.append(ch)
            esc = False
            continue
        if ch == "\\" and quote != "'":
            buf_chars.append(ch)
            esc = True
            continue
        if quote:
            buf_chars.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf_chars.append(ch)
            continue
        if ch in seps:
            segments.append("".join(buf_chars))
            buf_chars = []
            continue
        buf_chars.append(ch)
    segments.append("".join(buf_chars))
    return segments


def _first_word(text: str) -> str:
    """段首可执行词（跳过前导空白/env 前缀的最简实现）。"""
    stripped = text.strip()
    if not stripped:
        return ""
    # 环境变量前缀 FOO=bar cmd → 跳到第一个非 KEY= 值 token
    parts = stripped.split()
    idx = 0
    while idx < len(parts) - 1 and "=" in parts[idx] and not parts[idx].startswith(("'", '"')):
        idx += 1
    return parts[idx].strip("'\"")


def _extract_inline_commands(segment: str) -> List[CommandSegment]:
    """提取段内 inline 子命令（$( )、反引号）——有痕迹即上报整段。

    保守实现：不做递归展开，把 $(…) / `…` 的内层文本作为 quoted 段返回，
    外层段本身也保留。审批侧对 quoted 段同样要求白名单命中。
    """
    out: List[CommandSegment] = []
    text = segment
    i = 0
    n = len(text)
    while i < n:
        if text[i : i + 2] == "$(":
            depth = 1
            j = i + 2
            while j < n and depth:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                j += 1
            inner = text[i + 2 : j - 1] if depth == 0 else text[i + 2 : j]
            if inner.strip():
                segs = _split_top_level(inner, "&|;")
                for k, s in enumerate(segs):
                    if s.strip():
                        out.append(
                            CommandSegment(
                                text=s.strip(),
                                head=_first_word(s),
                                connector="$(" if k == 0 else "inline",
                                quoted=True,
                            )
                        )
            i = j
            continue
        if text[i] == "`":
            j = text.find("`", i + 1)
            inner = text[i + 1 : j] if j > 0 else text[i + 1 :]
            if inner.strip():
                out.append(
                    CommandSegment(
                        text=inner.strip(), head=_first_word(inner), connector="`", quoted=True
                    )
                )
            i = (j + 1) if j > 0 else n
            continue
        i += 1
    return out


def parse_command_segments(command: str) -> List[CommandSegment]:
    """把 shell 命令解析为候选段（pipeline/&&/||/;/inline 全拆开）。

    单次字符级扫描：切段同时记录连接符（&&/||/;/|，引号内不切）。
    inline 提取段（$()/反引号）跟随其宿主段之后。

    Returns:
        至少一段（空命令 → 空列表）。段顺序与原文一致。
    """
    if not command or not command.strip():
        return []

    # 一遍扫描：引号感知，遇顶层分隔符序列即切段并记录完整连接符
    parts: List[tuple] = []  # (segment_text, connector_before)
    buf: List[str] = []
    quote: Optional[str] = None
    esc = False
    pending_conn = ""
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if esc:
            buf.append(ch)
            esc = False
            i += 1
            continue
        if ch == "\\" and quote != "'":
            buf.append(ch)
            esc = True
            i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in "&|;":
            # 连续分隔符序列是一个连接符（&& / || / ; / | 混写按原文记录）
            j = i
            while j < n and command[j] in "&|;":
                j += 1
            parts.append(("".join(buf), pending_conn))
            pending_conn = command[i:j]
            buf = []
            i = j
            continue
        buf.append(ch)
        i += 1
    parts.append(("".join(buf), pending_conn))

    out: List[CommandSegment] = []
    for seg_text, conn in parts:
        seg_text = seg_text.strip()
        if not seg_text:
            continue
        out.append(CommandSegment(text=seg_text, head=_first_word(seg_text), connector=conn))
        out.extend(_extract_inline_commands(seg_text))

    return out
