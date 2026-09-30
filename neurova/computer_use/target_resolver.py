"""语义目标解析：把"自然语言目标"落到当前快照事实的 (role, name) 候选上。

`smart-click` 这一类能力此前只有占位面。本模块是它的第一片实现，
刻意窄化：**只在已有快照事实里解析**（aria 树的 role + accessible name），
不猜 CSS 选择器、不引入跨快照句柄（那是 T-08 的 ref 寻址）。

三态结果（`resolved` / `ambiguous` / `unresolved`）是判据不是风格：
`get_by_role` 命中多个元素时 Playwright 抛 `strict mode violation`，而活体取证显示
重名组覆盖过半可交互行——"取第一个"在多数歧义场景会点错，点错比不点更坏。
"""

from __future__ import annotations

import typing
import unicodedata
from dataclasses import dataclass, field

# 目标里可能出现的角色说法（含中文惯用词）→ 快照 role
_ROLE_WORDS: typing.Dict[str, str] = {
    "link": "link", "链接": "link",
    "button": "button", "按钮": "button",
    "textbox": "textbox", "输入框": "textbox", "文本框": "textbox",
    "searchbox": "searchbox", "搜索框": "searchbox",
    "checkbox": "checkbox", "复选框": "checkbox",
    "combobox": "combobox", "下拉": "combobox",
    "tab": "tab", "标签页": "tab",
    "menuitem": "menuitem", "菜单项": "menuitem",
}


@dataclass(frozen=True)
class Candidate:
    """一个可交互事实：来自快照的 role + accessible name。"""

    role: str
    name: str


@dataclass
class Resolution:
    """解析结果。`candidate` 仅在 `resolved` 时有值——歧义绝不代模型挑。"""

    state: str
    candidate: typing.Optional[Candidate] = None
    candidates: typing.List[Candidate] = field(default_factory=list)
    matchedBy: str = ""


def normalizeTarget(value: typing.Any) -> str:
    """归一化：全角→半角（NFKC）、去首尾空白、折叠内部空白、大小写不敏感。

    不做词序变换：`提交订单` 与 `订单提交` 必须仍是两个说法，
    否则"唯一命中"是归一化造出来的假象。
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).casefold()


def _splitRoleWord(target: str, pool: typing.List[Candidate]) -> "tuple[str, typing.List[Candidate]]":
    """目标里带角色说法时缩范围：`链接 详情` → 只在 link 里找 `详情`。"""
    tokens = [t for t in normalizeTarget(target).split() if t]
    role = next((_ROLE_WORDS[t] for t in tokens if t in _ROLE_WORDS), None)
    if role is None:
        return target, pool
    narrowed = [c for c in pool if normalizeTarget(c.role) == role]
    if not narrowed:
        return target, pool
    rest = " ".join(t for t in tokens if _ROLE_WORDS.get(t) != role)
    return (rest or target), narrowed


def resolveTarget(target: str, pool: typing.List[Candidate]) -> Resolution:
    """把目标解析到候选集。先精确、再包含，两级都不唯一即报歧义。"""
    query, narrowed = _splitRoleWord(target, pool)
    q = normalizeTarget(query)
    if not q:
        return Resolution("unresolved", matchedBy="empty")

    exact = [c for c in narrowed if normalizeTarget(c.name) == q]
    if len(exact) == 1:
        return Resolution("resolved", candidate=exact[0], matchedBy="exact")
    if len(exact) > 1:
        return Resolution("ambiguous", candidates=exact, matchedBy="exact")

    partial = [c for c in narrowed if q in normalizeTarget(c.name)]
    if len(partial) == 1:
        return Resolution("resolved", candidate=partial[0], matchedBy="partial")
    if len(partial) > 1:
        return Resolution("ambiguous", candidates=partial, matchedBy="partial")
    return Resolution("unresolved", matchedBy="none")


__all__ = ["Candidate", "Resolution", "normalizeTarget", "resolveTarget"]
