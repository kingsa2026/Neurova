# -*- coding: utf-8 -*-
"""B13 追加：嵌入模型刻度表——换嵌入模型后门槛自动重适配。

实测依据（B10/B13 探针，真嵌入面 bge-small-zh-v1.5）：0.65 门槛是按该
模型校准的（无关基线 ~0.61-0.63、相关 ≥0.64）；同质技术池上无区分力
（9/9 全过）。换嵌入模型后分数刻度整体漂移，固定 0.65 即失效。

契约：
1. 刻度表按嵌入模型指纹（backend:model）给基础门槛；bge 现值 0.65 保持；
2. 换模型（指纹变化）→ 门槛自动取新模型的表值（自动重适配）；
3. 表外模型：默认 0.65 + 在线基线自适应（多次 draw 后按实测无关基线
   上浮门槛——自校准）；
4. 显式门槛覆盖（近轮通道 0.75）与模型刻度取 max（模型刻度只抬升、
   不降低显式值）；
5. 开关 NEUROVA_DRAW_DYNAMIC_FLOOR=0 时全部回退固定 0.65。
"""
import os
import sys
from typing import Dict, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


class ScriptedVectorStore:
    """文本全等路由 + 可编程指纹的确定性向量替身（真契约 encode/encode_batch）。"""

    def __init__(self, text_vectors: Dict[str, List[float]], default: List[float],
                 fingerprint: str = "onnx:BAAI/bge-small-zh-v1.5"):
        self._text_vectors = dict(text_vectors)
        self._default = list(default)
        self._fingerprint = fingerprint

    def _cacheFingerprint(self) -> str:
        return self._fingerprint

    def _vec(self, text: str) -> List[float]:
        if text in self._text_vectors:
            return list(self._text_vectors[text])
        return list(self._default)

    def encode(self, text: str) -> List[float]:
        return self._vec(text)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]


def _drop(content: str) -> ContextInput:
    return ContextInput(source=ContextSource.MEMORY, content=content, priority=60, tokens=50)


def _drawer(fingerprint: str) -> SemanticMatchDrawer:
    drawer = SemanticMatchDrawer(max_tokens=10 ** 6)
    drawer._vector_store = ScriptedVectorStore(HOMO_VECTORS, [0.0, 0.0, 1.0], fingerprint)
    return drawer


# need 与候选的 matchScore 目标（(cos+1)/2 刻度）：0.85/0.74/0.72
# → 分差 0.13（同质池）。向量按 cos 反推（need=[1,0,0]）。
HOMO_NEED = "数据库迁移要注意什么"
HOMO_VECTORS = {
    HOMO_NEED: [1.0, 0.0, 0.0],
    "数据库迁移要分批执行避免锁表": [0.7, 0.714, 0.0],
    "固件升级前必须先备份配置": [0.48, 0.877, 0.0],
    "缓存淘汰策略采用 LRU 算法实现": [0.44, 0.78, 0.445],
}
_HOMO_DROPS = [
    _drop("数据库迁移要分批执行避免锁表"),
    _drop("固件升级前必须先备份配置"),
    _drop("缓存淘汰策略采用 LRU 算法实现"),
]


class TestCalibrationTable:
    def test_bge_floor_preserved(self, monkeypatch):
        """bge-small-zh 的刻度保持 0.65（现存校准不回退）。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        drawer = _drawer("onnx:BAAI/bge-small-zh-v1.5")
        assert drawer._baseFloorForKey("onnx:BAAI/bge-small-zh-v1.5") == 0.65

    def test_model_change_readapts(self, monkeypatch):
        """换嵌入模型（指纹变化）→ 门槛自动取新模型的表值。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        monkeypatch.setitem(
            SemanticMatchDrawer._EMBEDDING_MODEL_FLOORS, "onnx:other-embedder-v2", 0.75
        )
        drawer = _drawer("onnx:other-embedder-v2")
        assert drawer._baseFloorForKey("onnx:other-embedder-v2") == 0.75, (
            "刻度表中的其他嵌入模型应取其表值"
        )

    def test_unknown_model_uses_default(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        drawer = _drawer("onnx:never-seen")
        assert drawer._baseFloorForKey("onnx:never-seen") == 0.65


class TestOnlineBaseline:
    def test_baseline_rises_floor_for_unknown_model(self, monkeypatch):
        """表外模型：多次 draw 后按实测无关基线上浮门槛（自校准）。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        # 基线采样用 min(候选分)：同质池 min≈0.72 → 基线 EWMA≈0.72 →
        # 门槛 = max(0.65, 0.72+0.04)=0.76 → 0.72/0.74 的噪声候选被滤。
        drawer = _drawer("onnx:never-seen")
        for _ in range(6):
            drawer.draw(_HOMO_DROPS, need=HOMO_NEED)
        floor = drawer._baseFloorForKey("onnx:never-seen")
        assert floor >= 0.75, f"在线基线应上浮门槛：{floor}"
        result = drawer.draw(_HOMO_DROPS, need=HOMO_NEED)
        assert [d.content for d in result] == [_HOMO_DROPS[0].content], (
            "门槛上浮后应只保留最优相关条目"
        )

    def test_baseline_per_model_isolated(self, monkeypatch):
        """基线按模型分桶：换模型后基线从新模型的数据重新积累。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        drawer = _drawer("onnx:model-a")
        for _ in range(6):
            drawer.draw(_HOMO_DROPS, need=HOMO_NEED)
        # 换模型：新 key 的基线无数据 → 回落表值/默认
        assert drawer._baseFloorForKey("onnx:model-b") == 0.65
