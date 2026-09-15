# -*- coding: utf-8 -*-
"""技能语义向量层。

底座复用本地 bge ONNX（neurova.embedding.get_embedding_engine，模型缺失/
初始化失败 → 全链路优雅降级为纯关键词档，零报错零阻断）。

缓存纪律：缓存条目以**内容哈希**为键——
skill 文本（name+description+when_to_use）一变立即重编码，杜绝"原地改
SKILL.md 但向量陈旧"。引擎失败返回的零向量不入缓存、不参与排序。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MODEL_KEY = "bge-small-zh-v1.5"


def semantic_recall_enabled() -> bool:
    """语义档开关三级：env NEUROVA_SKILL_SEMANTIC 显式值 > app_settings
    advanced.skill_semantic_recall_enabled（默认开）> True；读取故障开。"""
    raw = os.environ.get("NEUROVA_SKILL_SEMANTIC", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        from neurova.core.app_settings import get_advanced_settings

        return bool(get_advanced_settings().get("skill_semantic_recall_enabled", True))
    except Exception:  # noqa: BLE001 - 设置故障保持开（降级安全在引擎侧）
        return True


def skill_semantic_text(skill: Any) -> str:
    """编码口径：name + description + when_to_use。"""
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
        # 显式注入 engine（测试/高级装配）不受开关摆布；懒解析路径才尊重
        # env/设置 kill-switch——保证单测永不加载 ONNX 模型（conftest 全局置 0）。
        if not semantic_recall_enabled():
            self.engine = None
            return None
        try:
            from neurova.tts.model_downloader import get_model_downloader

            # 召回热路径禁止触发模型下载（09-10 事故纪律延伸 + 测试网络隔离）：
            # 模型可用性只查询；缺失=降级关键词档，模型安装归模型管理/封包面。
            if not get_model_downloader().is_model_available(_MODEL_KEY):
                logger.info("嵌入模型未安装，技能检索使用关键词档")
                self.engine = None
                return None
        except Exception as e:  # noqa: BLE001 - 可用性探测失败按不可用处理
            logger.debug("嵌入模型可用性探测失败，降级关键词档: %s", e)
            self.engine = None
            return None
        try:
            from neurova.embedding import get_embedding_engine

            self.engine = get_embedding_engine()
            # is_initialized 是 property（mem_core/voice_engine 同读取式）——
            # 误当方法调用会抛 TypeError 并被静默吞成"降级关键词档"（live 走查抓出）
            if self.engine is not None and not getattr(self.engine, "is_initialized", False):
                self.engine.initialize_sync()
            if self.engine is not None and not getattr(self.engine, "is_initialized", False):
                self.engine = None
        except Exception as e:  # noqa: BLE001 - 语义档是增强，故障即降级
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
