"""
Neurova Hebb 数据模型与存储模块

Neurova Hebb 是 LLM 中间推理过程的结构化表示。
NeuHebbMem 负责 Neurova Hebb 的持久化存储和检索。

模块深度: 小接口（store/retrieve/get_metadata），深实现（JSON持久化、索引管理、生命周期追踪）。
"""
from __future__ import annotations

import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────

@dataclass
class NeurovaHebb:
    """Neurova Hebb 单元 —— 一条结构化的 LLM 推理记忆。"""
    id: str = field(default_factory=lambda: f"hebb_{uuid.uuid4().hex[:12]}")
    content: str = ""                              # 总结后的知识内容
    embedding: Optional[List[float]] = None        # 向量嵌入
    question: str = ""                             # 原始预查询
    answer: str = ""                               # 原始答案
    source: str = "pre_query"                      # 来源类型
    document_id: str = ""                          # 关联文档 ID
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    verification_score: float = 0.0                # 验证得分 [0, 1]
    usage_count: int = 0                           # 被检索使用次数
    last_used: Optional[str] = None                # 最后使用时间
    metadata: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """更新使用计数和最后使用时间。"""
        self.usage_count += 1
        self.last_used = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NeurovaHebb":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class NeuHebbConfig:
    """Neurova Hebb 系统配置。"""
    enabled: bool = True
    chunk_num: int = 8
    recall_coe: int = 5
    sim_thre: float = 0.85
    neurova_hebbs_limit: int = 15
    pre_query_count: int = 5
    verification_enabled: bool = True
    persistence_path: str = "data/neurova_hebbs/"
    max_neurova_hebbs_per_document: int = 100
    embedding_model: str = "facebook/contriever"
    embedding_dimension: int = 768
    diversity_threshold: float = 0.85
    top_k: int = 5
    max_neurova_hebbs_per_query: int = 10
    llm_model: str = "auto"
    backend: str = "faiss"
    index_type: str = "IndexFlatL2"


# ── 存储模块 ──────────────────────────────────────────────────────────────────

class NeuHebbMem:
    """
    Neurova Hebb 持久化存储。

    接口极简：store / retrieve / get_all / get_metadata / delete。
    内部使用 JSON 文件持久化，支持按 document_id 分组管理。
    """

    def __init__(self, config: Optional[NeuHebbConfig] = None):
        self.config = config or NeuHebbConfig()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._storage_path = Path(self.config.persistence_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._load_data()

    # ── 公开接口 ──

    def store(self, document_id: str, neurova_hebbs: List[NeurovaHebb]) -> int:
        """
        存储 NeurovaHebb 列表到指定文档。

        Returns:
            实际存储的数量（超过限额的会被截断）。
        """
        if document_id not in self._data:
            self._data[document_id] = {
                "metadata": self._create_metadata(),
                "neurova_hebbs": [],
            }

        doc = self._data[document_id]
        limit = self.config.max_neurova_hebbs_per_document
        stored = 0

        for hebb in neurova_hebbs:
            if len(doc["neurova_hebbs"]) >= limit:
                logger.warning(
                    "Document %s reached Neurova Hebb limit (%d), truncating",
                    document_id, limit,
                )
                break
            doc["neurova_hebbs"].append(hebb.to_dict())
            stored += 1

        doc["metadata"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        doc["metadata"]["total_neurova_hebbs"] = len(doc["neurova_hebbs"])
        self._save_data()
        return stored

    def retrieve(self, document_id: str, neurova_hebb_ids: Optional[List[str]] = None) -> List[NeurovaHebb]:
        """
        检索指定文档的 NeurovaHebb。
        若提供 neurova_hebb_ids 则精确匹配，否则返回全部。
        """
        if document_id not in self._data:
            return []

        records = self._data[document_id]["neurova_hebbs"]

        if neurova_hebb_ids is not None:
            id_set = set(neurova_hebb_ids)
            records = [r for r in records if r["id"] in id_set]

        return [NeurovaHebb.from_dict(r) for r in records]

    def get_all(self) -> Dict[str, List[NeurovaHebb]]:
        """返回所有文档的 NeurovaHebb。"""
        result = {}
        for doc_id, doc in self._data.items():
            result[doc_id] = [NeurovaHebb.from_dict(r) for r in doc["neurova_hebbs"]]
        return result

    def get_metadata(self, document_id: str) -> Optional[Dict[str, Any]]:
        """获取文档级元数据。"""
        if document_id in self._data:
            return dict(self._data[document_id]["metadata"])
        return None

    def delete(self, document_id: str, neurova_hebb_ids: Optional[List[str]] = None) -> int:
        """
        删除 NeurovaHebb。
        若提供 neurova_hebb_ids 则删除指定条目，否则删除整个文档。
        Returns:
            删除的数量。
        """
        if document_id not in self._data:
            return 0

        if neurova_hebb_ids is None:
            count = len(self._data[document_id]["neurova_hebbs"])
            del self._data[document_id]
            self._save_data()
            return count

        id_set = set(neurova_hebb_ids)
        before = len(self._data[document_id]["neurova_hebbs"])
        self._data[document_id]["neurova_hebbs"] = [
            r for r in self._data[document_id]["neurova_hebbs"]
            if r["id"] not in id_set
        ]
        after = len(self._data[document_id]["neurova_hebbs"])
        self._data[document_id]["metadata"]["total_neurova_hebbs"] = after
        self._save_data()
        return before - after

    def count(self, document_id: Optional[str] = None) -> int:
        """返回 NeurovaHebb 总数。"""
        if document_id:
            if document_id in self._data:
                return len(self._data[document_id]["neurova_hebbs"])
            return 0
        return sum(len(d["neurova_hebbs"]) for d in self._data.values())

    # ── 内部实现 ──

    def _create_metadata(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "created_at": now,
            "updated_at": now,
            "total_neurova_hebbs": 0,
        }

    def _file_path(self) -> Path:
        return self._storage_path / "neurova_hebbs.json"

    def _load_data(self) -> None:
        path = self._file_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load NeurovaHebb data: %s", exc)
                self._data = {}

    def _save_data(self) -> None:
        path = self._file_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error("Failed to save NeurovaHebb data: %s", exc)
