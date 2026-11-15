# -*- coding: utf-8 -*-
"""B13（对照改进追问批）：抽屉相关性门槛刻度重标定——同质池动态收紧。

实测依据（本批 B10 探针，真嵌入面 bge-small-zh）：同质技术池上
0.65 绝对门槛**无区分力**——9/9 条目（含与输入无关的条目）全部过门槛
（无关对实测 0.741-0.756，相关对 0.856）。固定绝对门槛在异质池与
同质池之间无法两全。

契约（向量刻度可用、候选 ≥4、need 非空时启用；关键词降级路径不启用）：
1. 同质池（候选分差 ≤ 0.15）：门槛收紧到 max(绝对门槛, 最优分-带宽
   （0.08，env 可调）)——无关噪声带被滤掉，最优簇保留；
2. 异质池（分差 > 0.15）：维持绝对门槛（多簇真相关不误杀）；
3. 最优条目永不被动态门槛滤掉（保底）；
4. 读数：dynamic_floor 应用情况进抽屉读数；
5. 开关 NEUROVA_DRAW_DYNAMIC_FLOOR=0 关闭。
"""
import os
import sys
from typing import Dict, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


class ScriptedVectorStore:
    """文本**全等**路由的确定性向量替身（真契约：encode/encode_batch）。

    全等路由（非子串）：need 文本与条目文本各自独立钉向量，互不串扰。
    """

    def __init__(self, text_vectors: Dict[str, List[float]], default: List[float]):
        self._text_vectors = dict(text_vectors)
        self._default = list(default)

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


def _drawer(store) -> SemanticMatchDrawer:
    drawer = SemanticMatchDrawer(max_tokens=10 ** 6)
    drawer._vector_store = store
    return drawer


# need 与三候选的 matchScore 目标（(cos+1)/2 刻度）：0.85 / 0.74 / 0.72
# → 分差 0.13 ≤ 0.15（同质池）；动态门槛 = 0.85-0.08 = 0.77 →
# 固件(0.74)/缓存(0.72)被滤，仅数据库迁移保留。
NEED_TEXT = "数据库迁移要注意什么"
_HOMO_VECTORS = {
    NEED_TEXT: [1.0, 0.0, 0.0],
    "数据库迁移要分批执行避免锁表": [0.7, 0.714, 0.0],
    "固件升级前必须先备份配置": [0.48, 0.877, 0.0],
    "缓存淘汰策略采用 LRU 算法实现": [0.44, 0.78, 0.445],
}


class TestDynamicFloor:
    def test_homogeneous_pool_tightens_to_best_band(self, monkeypatch):
        """同质池：门槛收紧到 最优分-0.08——无关噪声带被滤掉。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        store = ScriptedVectorStore(_HOMO_VECTORS, default=[0.0, 0.0, 1.0])
        drawer = _drawer(store)
        drops = [
            _drop("数据库迁移要分批执行避免锁表"),
            _drop("固件升级前必须先备份配置"),
            _drop("缓存淘汰策略采用 LRU 算法实现"),
        ]
        result = drawer.draw(drops, need=NEED_TEXT)
        contents = [d.content for d in result]
        assert any("数据库迁移" in c for c in contents), "最优相关条目必须保留"
        assert not any("固件升级" in c for c in contents), (
            "同质池噪声带（0.74）应被动态门槛滤掉"
        )
        assert not any("缓存淘汰" in c for c in contents)

    def test_diverse_pool_no_overkill(self, monkeypatch):
        """异质池（多簇真相关，分差 0.29）：动态门槛不得误杀。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        store = ScriptedVectorStore({
            NEED_TEXT: [1.0, 0.0, 0.0],
            "数据库迁移要分批执行避免锁表": [0.9, 0.436, 0.0],
            "缓存淘汰策略采用 LRU 算法实现": [0.5, 0.866, 0.0],
            "固件升级前必须先备份配置": [0.32, 0.947, 0.2],
        }, default=[0.0, 0.0, 1.0])
        drawer = _drawer(store)
        drops = [
            _drop("数据库迁移要分批执行避免锁表"),
            _drop("缓存淘汰策略采用 LRU 算法实现"),
            _drop("固件升级前必须先备份配置"),
        ]
        result = drawer.draw(drops, need=NEED_TEXT)
        contents = [d.content for d in result]
        assert len(contents) == 3, f"异质池不得误杀：{contents}"

    def test_best_item_never_filtered(self, monkeypatch):
        """最优条目永不被动态门槛滤掉（保底）。"""
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        store = ScriptedVectorStore(_HOMO_VECTORS, default=[0.0, 0.0, 1.0])
        drawer = _drawer(store)
        drops = [_drop("数据库迁移要分批执行避免锁表"), _drop("固件升级前必须先备份配置")]
        result = drawer.draw(drops, need=NEED_TEXT)
        assert any("数据库迁移" in d.content for d in result)

    def test_kill_switch(self, monkeypatch):
        """开关关闭：同质池回到绝对门槛行为（噪声带不滤）。"""
        monkeypatch.setenv("NEUROVA_DRAW_DYNAMIC_FLOOR", "0")
        store = ScriptedVectorStore(_HOMO_VECTORS, default=[0.0, 0.0, 1.0])
        drawer = _drawer(store)
        drops = [
            _drop("数据库迁移要分批执行避免锁表"),
            _drop("固件升级前必须先备份配置"),
        ]
        result = drawer.draw(drops, need=NEED_TEXT)
        assert len(result) == 2, "开关关闭：动态门槛不生效"

    def test_readout_records_dynamic_floor(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_DRAW_DYNAMIC_FLOOR", raising=False)
        store = ScriptedVectorStore(_HOMO_VECTORS, default=[0.0, 0.0, 1.0])
        drawer = _drawer(store)
        drops = [
            _drop("数据库迁移要分批执行避免锁表"),
            _drop("固件升级前必须先备份配置"),
            _drop("缓存淘汰策略采用 LRU 算法实现"),
        ]
        drawer.draw(drops, need=NEED_TEXT)
        readouts = drawer.readouts()
        assert readouts["dynamic_floor_applied"] == 1
        assert readouts["last_dynamic_floor"] == pytest.approx(0.85 - 0.08, abs=1e-3)
