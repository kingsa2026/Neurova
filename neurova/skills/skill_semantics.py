# -*- coding: utf-8 -*-
"""技能语义向量层（OpenSpace 对比 §2.4 施工项：检索阶梯的 embedding 档）。

底座复用本地 bge ONNX（neurova.embedding.get_embedding_engine，模型缺失/
初始化失败 → 全链路优雅降级为纯关键词档，零报错零阻断）。

缓存纪律（OpenSpace 的坑，对比报告点名）：缓存条目以**内容哈希**为键——
skill 文本（name+description+when_to_use）一变立即重编码，杜绝"原地改
SKILL.md 但向量陈旧"。引擎失败返回的零向量不入缓存、不参与排序。
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def skill_semantic_text(skill: Any) -> str:
    """编码口径：name + description + when_to_use（对齐 OpenSpace 12000 截断）。"""
    name = str(getattr(skill, "name", "") or "")
    desc = str(getattr(skill, "description", "") or "")
    cfg = getattr(skill, "config", None)
    when = str(cfg.get("when_to_use", "")) if isinstance(cfg, dict) else ""
    return f"{name}\n\n{desc}" + (f"\n\n{when}" if when else "")


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # 引擎输出已 L2 归一化


def is_zero_vector(vec: Optional[List[float]]) -> bool:
    return not vec or all(abs(x) < 1e-9 for x in vec)


class SkillVectorCache:
    """按 agent 隔离的技能向量缓存（JSON 持久化，内容哈希键）。"""

    def __init__(self, engine: Any = None, cache_file: Optional[Path] = None):
        """engine=None → 懒取全局单例（模型缺失时工厂返回 None，本类自动降级）。"""
        self.engine = engine
        self._engine_resolved = engine is not None
        self.cache_file = Path(cache_file) if cache_file else None
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}
        if self.cache_file and self.cache_file.exists():
            try:
                self._entries = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                self._entries = {}

    def _get_engine(self) -> Any:
        if self._engine_resolved:
            return self.engine
        self._engine_resolved = True
        try:
            from neurova.embedding import get_embedding_engine

            self.engine = get_embedding_engine()
            if self.engine is not None and not self.engine.is_initialized():
                self.engine.initialize_sync()
        except Exception as e:  # noqa: BLE001 - 语义档是增强，故障即降级关键词档
            logger.info("embedding 引擎不可用，技能检索降级关键词档: %s", e)
            self.engine = None
        return self.engine

    def vectors_for(self, skills: Dict[str, Any]) -> Dict[str, List[float]]:
        """{name: 向量}（仅返回可用向量；未命中编码失败的缺席）。"""
        if not skills:
            return {}
        eng = self._get_engine()
        if eng is None:
            return {}
        out: Dict[str, List[float]] = {}
        changed = False
        with self._lock:
            for name, skill in skills.items():
                text = skill_semantic_text(skill)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                entry = self._entries.get(name)
                if entry and entry.get("hash") == digest and not is_zero_vector(entry.get("vector")):
                    out[name] = entry["vector"]
                    continue
                try:
                    vec = eng.encode(text)
                except Exception as e:  # noqa: BLE001
                    logger.debug("技能 %s 向量编码失败: %s", name, e)
                    continue
                if is_zero_vector(vec):
                    continue  # 零向量=引擎失败，不入库不排序
                self._entries[name] = {"hash": digest, "vector": vec}
                changed = True
                out[name] = vec
            if changed:
                self._persist()
        return out

    def encode_query(self, query: str) -> Optional[List[float]]:
        eng = self._get_engine()
        if eng is None or not str(query or "").strip():
            return None
        try:
            vec = eng.encode(str(query))
        except Exception as e:  # noqa: BLE001
            logger.debug("查询向量编码失败: %s", e)
            return None
        return None if is_zero_vector(vec) else vec

    def _persist(self) -> None:
        if not self.cache_file:
            return
        try:
            import os

            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.cache_file)
        except Exception as e:  # noqa: BLE001 - 缓存持久化失败只丢缓存
            logger.debug("向量缓存落盘失败: %s", e)


def semantic_scores_for(
    cache: SkillVectorCache, query: str, skills: Dict[str, Any]
) -> Dict[str, float]:
    """{name: cosine(query, skill)}——关键词档之外的第二打分源。"""
    qvec = cache.encode_query(query)
    if qvec is None:
        return {}
    vecs = cache.vectors_for(skills)
    return {name: _cosine(qvec, vec) for name, vec in vecs.items()}
