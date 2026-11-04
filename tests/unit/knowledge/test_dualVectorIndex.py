# -*- coding: utf-8 -*-
"""C4 红灯：双向量索引（heading+content，SAG 对比候选 C4，2026-11-05）。

对照点（SAG 对比 §2.1/§6.2）：对方每 chunk 双向量（title_vector 1.0 /
content_vector 0.95）并行召回——标题命中的精确实体不被正文长文本稀释。
本仓现状：单向量（embeddingText=title+content 合成文本单点）。

契约：
- `NEUROVA_KB_DUAL_VECTOR` 门控，默认 off＝旧行为逐位（记录无 heading_vector）
- on：ensure 记录加 heading_vector（=encode(title)）；search 融合分
  max(cos_title, 0.95·cos_content)——标题命中排序高于等量正文命中
- on：旧分片记录缺 heading_vector 时按需补算（自愈，一次性）
- on：ANN 旁路（融合分与 ANN 单向量空间不相容，走全量余弦并如实降级）
"""
from __future__ import annotations

import json

import pytest

from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.vector_index import KnowledgeVectorIndex

ENV = "NEUROVA_KB_DUAL_VECTOR"
ALICE = {"user_id": "1", "username": "a", "role": "user", "neuser_id": "1"}
AGENT = "dual-vec"


class StubEngine:
    """确定性 embedding 桩（与 test_knowledge_vector_index 同款词袋 one-hot）。"""

    VOCAB = ["quantum", "rust", "async", "cookie", "recipe", "travel", "sales", "plan"]

    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


@pytest.fixture()
def repo(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    yield repo


def _entry(repo, kid, title, content):
    repo.create_knowledge(AGENT, title, content, knowledge_id=kid, owner_user_id="1")


def _records(idx, user):
    data = json.loads(idx._file_for(user).read_text(encoding="utf-8"))
    return data["vectors"]


def test_dualVectorOff_defaultRecordShape(monkeypatch, tmp_path, repo):
    """默认关闸：记录形状逐位等于旧行为（无 heading_vector 键）。"""
    monkeypatch.delenv(ENV, raising=False)
    _entry(repo, "k1", "sales", "travel")
    idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
    result = idx.ensure_indexed(repo, ALICE)
    assert result["computed"] == 1
    rec = _records(idx, ALICE)["k1"]
    assert "heading_vector" not in rec, "关闸态不得写入 heading_vector"
    assert rec["vector"] == StubEngine().encode("sales\ntravel")


def test_dualVectorOn_writesBothVectors(monkeypatch, tmp_path, repo):
    """开闸：主向量保持 embeddingText 单点，heading_vector 独立成列。"""
    monkeypatch.setenv(ENV, "on")
    _entry(repo, "k1", "sales", "travel")
    idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
    idx.ensure_indexed(repo, ALICE)
    rec = _records(idx, ALICE)["k1"]
    assert rec["vector"] == StubEngine().encode("sales\ntravel"), "主向量单点纪律不破"
    assert rec["heading_vector"] == StubEngine().encode("sales")


def test_dualVectorOn_titleOutranksContent(monkeypatch, tmp_path, repo):
    """开闸：融合分下标题命中排序高于等量正文命中（单向量下两者并列）。"""
    monkeypatch.setenv(ENV, "on")
    _entry(repo, "k1", "sales", "cookie")   # 标题命中查询
    _entry(repo, "k2", "beta", "sales")     # 仅正文命中查询
    idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
    idx.ensure_indexed(repo, ALICE)
    hits = idx.search("sales plan", ALICE, top_k=2)
    byId = {h["id"]: h for h in hits}
    assert byId["k1"]["score"] > byId["k2"]["score"], (
        "标题命中必须排在正文命中之前（融合分 max(cos_title, 0.95·cos_content)）"
    )


def test_dualVectorOn_legacyRecordHeals(monkeypatch, tmp_path, repo):
    """开闸：旧分片（单向量形状、指纹未变）按需补算 heading_vector。"""
    _entry(repo, "k1", "sales", "travel")
    monkeypatch.delenv(ENV, raising=False)
    old = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
    old.ensure_indexed(repo, ALICE)
    assert "heading_vector" not in _records(old, ALICE)["k1"]

    monkeypatch.setenv(ENV, "on")
    new = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine())
    result = new.ensure_indexed(repo, ALICE)
    assert result["computed"] >= 1, "缺 heading_vector 的旧记录必须补算（自愈一次）"
    assert _records(new, ALICE)["k1"]["heading_vector"] == StubEngine().encode("sales")


def test_dualVectorOn_annBypassed(monkeypatch, tmp_path, repo):
    """开闸：ANN 旁路（融合分与单向量 ANN 空间不相容）——build 零调用。"""
    monkeypatch.setenv(ENV, "on")
    _entry(repo, "k1", "sales", "travel")

    builds: list = []

    class CountingBackend:
        def build(self, vectors):
            builds.append(vectors)
            return object()

        def search(self, handle, qv, top_k):
            return []

    idx = KnowledgeVectorIndex(
        str(tmp_path / "vec"), engine=StubEngine(), annBackend=CountingBackend(),
        annMinRecordCount=0,
    )
    idx.ensure_indexed(repo, ALICE)
    idx.search("sales", ALICE, top_k=2)
    assert builds == [], "双向量检索必须旁路 ANN（全量余弦）"
