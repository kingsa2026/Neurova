"""确定性实体消解 · 候选分块（工单 006，设计文档 §5 段2）。

分块的唯一目的是不再做全对遍历：只在同类型 + 同前缀 / 同词集（可选同音）
的桶内配对。整段零模型调用，同输入必得同输出。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Tuple

_NORMALIZE_STRIP = re.compile(r"[\W_]+", re.UNICODE)
_TOKEN_SPLIT = re.compile(r"[\s/、,，.;。;|]+", re.UNICODE)


def normalizeLabel(label: str) -> str:
    return _NORMALIZE_STRIP.sub("", unicodedata.normalize("NFKC", str(label or "")).casefold())


def _soundex(token: str) -> str:
    """最简 Soundex——给拼音/拼写变体一个同桶机会。仅需稳定，不需语言学到位的分块。"""
    codes = {
        "b": "1", "f": "1", "p": "1", "v": "1",
        "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
        "d": "3", "t": "3",
        "l": "4",
        "m": "5", "n": "5",
        "r": "6",
    }
    cleaned = re.sub(r"[^a-z]", "", token.lower())
    if not cleaned:
        return ""
    out = [cleaned[0]]
    for ch in cleaned[1:]:
        code = codes.get(ch, "")
        if code and (not out or out[-1] != code):
            out.append(code)
    return "".join(out)[:4]


class EntityBlockingResolver:
    """把"该比的成对"缩到桶内，其余一概不比。"""

    def __init__(
        self,
        blockingKeys: Tuple[str, ...] = ("prefix", "token", "phonetic"),
        prefixLength: int = 4,
    ) -> None:
        self._blockingKeys = blockingKeys
        self._prefixLength = prefixLength

    def candidatePairs(self, entities: Iterable[Dict[str, Any]]) -> List[Tuple[str, str]]:
        buckets: Dict[Tuple[str, str, str], List[str]] = {}
        material: List[Dict[str, Any]] = []
        for entity in entities:
            key = str(entity.get("key", ""))
            if not key:
                raise ValueError("分块输入实体缺少 key 字段，无法产出可重放配对")
            material.append(entity)

        for entity in material:
            normalized = normalizeLabel(entity.get("label", ""))
            tokens = sorted({
                t for t in _TOKEN_SPLIT.split(str(entity.get("label", "") or "").strip().casefold()) if t
            })
            blockKeys = self._keysFor(entity, normalized, tokens)
            for bucketKey in blockKeys:
                buckets.setdefault(bucketKey, []).append(str(entity["key"]))

        pairs = set()
        for members in buckets.values():
            ordered = sorted(set(members))
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    pairs.add((left, right))
        return sorted(pairs)

    def _keysFor(
        self, entity: Dict[str, Any], normalized: str, tokens: List[str]
    ) -> List[Tuple[str, str, str]]:
        etype = str(entity.get("type", "") or "")
        keys: List[Tuple[str, str, str]] = []
        for kind in self._blockingKeys:
            if kind == "prefix":
                if normalized:
                    keys.append(("prefix", etype, normalized[: self._prefixLength]))
            elif kind == "token":
                if tokens:
                    keys.append(("token", etype, "|".join(tokens)))
            elif kind == "phonetic":
                for token in tokens:
                    code = _soundex(token)
                    if code:
                        keys.append(("phonetic", etype, code))
            else:
                raise ValueError("未知分块键: %r（可用: prefix / token / phonetic）" % kind)
        if not keys:
            keys.append(("singleton", etype, str(entity.get("key", ""))))
        return keys
