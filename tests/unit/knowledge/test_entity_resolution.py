"""P1-1 图谱实体消解（Utopia 对标落地清单，0005/adjudication 裁剪版）。

契约（docs/Neurova_Utopia代码级对比_2026-09-04.md §2.4/§4 P1-1）：

resolution.pair_key：
- 裁决缓存键与节点 ID 无关：sha256(label 小写|类型|描述摘要)，双方排序后哈希——
  重传文档/重建图不重复付费（同名对换序同键）。

KnowledgeGraphManager.merge_nodes（原语，可回滚）：
- source 并入 target：source 的边全部改挂 target，source 打 merged_into 指向
  target 并从所有索引/查询消失（失败方向：漏过滤=合并节点不可见，而非脏节点混入）；
- 合并日志 entity_merges 记录被移动的边与 source 画像快照，undo_merge 按名单原路
  读回（不多不少——此前已删的边不在名单，不会被误救）；
- merged_into 非空的节点不出现在 get_graph/search_nodes/get_stats 计数。

EntityResolver（三段式）：
- 第一段精确召回：label 小写精确相同的未合并节点对 → 灰区；
- 第二段相似度：difflib ratio ≥0.85 的跨名对 → 灰区（宁分勿合）；
- 第三段 LLM 裁决（可注入 llm_call，缺省 None）：
  - 缓存命中 → 直接用缓存裁决，不调 LLM；
  - 高置信 same（≥0.8）→ 自动合并（记录 merge 日志）；
  - 高置信 different（≥0.8）→ 自动保持分开（关闭灰区对）；
  - 低置信/无 LLM → 转人工队列（human_reviews），裁决任务失败不影响图谱读写；
- resolve_human：人工裁决 merged/kept，走同一 merge 原语；
- 全程异常不向上传播（消解是后台增强，失败只少一个合并）。
"""

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    NodeType,
    RelationType,
)
from neurova.knowledge.resolution import EntityResolver, pair_key


@pytest.fixture
def graph(tmp_path):
    return KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))


@pytest.fixture
def resolver(graph, tmp_path):
    return EntityResolver(graph, storage_dir=str(tmp_path / "kg"))


def _node(graph, label, ntype=NodeType.CONCEPT, description=""):
    return graph.add_node(
        label=label, node_type=ntype, properties={"description": description} if description else {}
    )


class TestPairKey:
    def test_id_independent_and_order_free(self, graph):
        a1 = _node(graph, "张三")
        a2 = _node(graph, "张三")
        b1 = _node(graph, "张三")
        b2 = _node(graph, "张三")
        # 同一对名字无论用哪些节点实例、谁先谁后，键一致
        assert pair_key(a1, a2) == pair_key(a2, a1)
        assert pair_key(a1, a2) == pair_key(b1, b2)

    def test_different_label_different_key(self, graph):
        a = _node(graph, "张三")
        b = _node(graph, "李四")
        assert pair_key(a, b) != pair_key(_node(graph, "张三"), _node(graph, "王五"))


class TestMergeNodes:
    def test_merge_moves_edges_and_hides_source(self, graph):
        src = _node(graph, "OpenAI 公司")
        dst = _node(graph, "OpenAI")
        other = _node(graph, "GPT")
        graph.add_edge(source_id=src.node_id, target_id=other.node_id, relation_type=RelationType.RELATED_TO)

        ok = graph.merge_nodes(src.node_id, dst.node_id, reason="auto|test")
        assert ok is True
        # source 从查询/统计消失
        assert graph.get_node(src.node_id) is None
        assert graph.search_nodes("OpenAI 公司") == []
        # 边改挂 target
        edges = graph.get_edges_between(dst.node_id, other.node_id)
        assert len(edges) == 1

    def test_merge_log_enables_undo(self, graph):
        src = _node(graph, "微软")
        dst = _node(graph, "Microsoft")
        other = _node(graph, "Windows")
        e1 = graph.add_edge(source_id=src.node_id, target_id=other.node_id, relation_type=RelationType.USED_BY)
        e2 = graph.add_edge(source_id=other.node_id, target_id=dst.node_id, relation_type=RelationType.RELATED_TO)

        ok = graph.merge_nodes(src.node_id, dst.node_id, reason="human|test")
        assert ok is True
        # undo 精确回滚：source 复活、边按名单改回
        assert graph.undo_merge(src.node_id) is True
        assert graph.get_node(src.node_id) is not None
        assert graph.get_node(src.node_id).label == "微软"
        assert graph.get_edges_between(src.node_id, other.node_id)
        assert graph.get_edges_between(other.node_id, dst.node_id)
        # undo 后 merge 日志清掉，不能重复 undo
        assert graph.undo_merge(src.node_id) is False

    def test_merge_missing_node_returns_false(self, graph):
        a = _node(graph, "存在")
        assert graph.merge_nodes(a.node_id, "no-such") is False
        assert graph.merge_nodes("no-such", a.node_id) is False

    def test_merged_node_invisible_but_persisted(self, tmp_path, graph):
        src = _node(graph, "旧名")
        dst = _node(graph, "新名")
        graph.merge_nodes(src.node_id, dst.node_id, reason="auto|test")

        # 重启（重新加载）后仍不可见（墓碑持久化）
        g2 = KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))
        assert g2.get_node(src.node_id) is None
        # undo_merge 在新实例上仍可用（日志持久化）
        assert g2.undo_merge(src.node_id) is True
        assert g2.get_node(src.node_id) is not None


class TestEntityResolver:
    def test_exact_label_dupes_go_grey_zone(self, graph, resolver):
        a = _node(graph, "量子比特")
        b = _node(graph, "量子比特")
        c = _node(graph, "完全无关")
        result = resolver.find_candidates()
        assert len(result["grey"]) == 1
        pair = result["grey"][0]
        assert {a.node_id, b.node_id} == {pair["left_id"], pair["right_id"]}

    def test_similar_labels_detected(self, graph, resolver):
        _node(graph, "腾讯控股有限公司")
        _node(graph, "腾讯控股有限责任公司")  # ratio ≈ 0.89 ≥ 0.85
        result = resolver.find_candidates()
        assert len(result["grey"]) == 1

    def test_below_threshold_not_proposed(self, graph, resolver):
        _node(graph, "机器学习算法")
        _node(graph, "机器学算法习")  # ratio ≈ 0.83 < 0.85，宁分勿合
        result = resolver.find_candidates()
        assert result["grey"] == []

    def test_verdict_cache_hit_skips_llm(self, graph, resolver):
        a = _node(graph, "缓存命中实体")
        b = _node(graph, "缓存命中实体")
        calls = {"n": 0}

        def llm(prompt):
            calls["n"] += 1
            return json.dumps({"verdict": "same", "confidence": 0.9})

        resolver.run_adjudication(llm_call=llm)
        assert calls["n"] == 1
        # 二次运行：缓存命中，LLM 零调用
        resolver.run_adjudication(llm_call=llm)
        assert calls["n"] == 1

    def test_high_confidence_same_auto_merges(self, graph, resolver):
        a = _node(graph, "高置信同体")
        b = _node(graph, "高置信同体")
        resolver.run_adjudication(
            llm_call=lambda p: json.dumps({"verdict": "same", "confidence": 0.95})
        )
        # b 并入 a（合并方向稳定：按 node_id 排序，target 取较小者）
        assert graph.get_node(a.node_id) is None or graph.get_node(b.node_id) is None
        survivors = [n for n in graph.search_nodes("高置信同体") if n.node_id in (a.node_id, b.node_id)]
        assert len(survivors) == 1

    def test_high_confidence_different_keeps_apart(self, graph, resolver):
        a = _node(graph, "同名不同体甲")
        b = _node(graph, "同名不同体甲")
        resolver.run_adjudication(
            llm_call=lambda p: json.dumps({"verdict": "different", "confidence": 0.9})
        )
        # 两个都活着，灰区对关闭
        assert len(graph.search_nodes("同名不同体甲")) == 2
        assert resolver.find_candidates()["grey"] == []

    def test_no_llm_escalates_to_human(self, graph, resolver):
        a = _node(graph, "待人工裁决")
        b = _node(graph, "待人工裁决")
        result = resolver.run_adjudication(llm_call=None)
        assert result["escalated"] == 1
        reviews = resolver.list_human_reviews()
        assert len(reviews) == 1
        assert reviews[0]["status"] == "pending"
        assert {a.node_id, b.node_id} == {reviews[0]["left_id"], reviews[0]["right_id"]}
        # 图不受影响：两个节点都还在
        assert len(graph.search_nodes("待人工裁决")) == 2

    def test_llm_failure_escalates_not_raises(self, graph, resolver):
        _node(graph, "异常转人工")
        _node(graph, "异常转人工")

        def boom(prompt):
            raise RuntimeError("llm down")

        result = resolver.run_adjudication(llm_call=boom)
        assert result["escalated"] == 1
        assert len(resolver.list_human_reviews()) == 1

    def test_malformed_llm_output_escalates(self, graph, resolver):
        _node(graph, "畸形输出")
        _node(graph, "畸形输出")
        result = resolver.run_adjudication(llm_call=lambda p: "不是 JSON")
        assert result["escalated"] == 1

    def test_human_resolve_merged_uses_merge_primitive(self, graph, resolver):
        a = _node(graph, "人工裁合并")
        b = _node(graph, "人工裁合并")
        resolver.run_adjudication(llm_call=None)
        review = resolver.list_human_reviews()[0]

        assert resolver.resolve_human(review["review_id"], "merged", decided_by="admin") is True
        assert len(graph.search_nodes("人工裁合并")) == 1
        assert resolver.list_human_reviews() == []

    def test_human_resolve_kept_closes_review(self, graph, resolver):
        _node(graph, "人工裁分开")
        _node(graph, "人工裁分开")
        resolver.run_adjudication(llm_call=None)
        review = resolver.list_human_reviews()[0]

        assert resolver.resolve_human(review["review_id"], "kept", decided_by="admin") is True
        assert len(graph.search_nodes("人工裁分开")) == 2
        assert resolver.list_human_reviews() == []

    def test_resolved_reviews_queryable(self, graph, resolver):
        _node(graph, "裁决历史查询")
        _node(graph, "裁决历史查询")
        resolver.run_adjudication(llm_call=None)
        review = resolver.list_human_reviews()[0]
        resolver.resolve_human(review["review_id"], "kept", decided_by="admin1")

        done = resolver.list_human_reviews(status="resolved")
        assert len(done) == 1
        assert done[0]["resolved_by"] == "admin1"

    def test_merged_pairs_not_reproposed(self, graph, resolver):
        """已合并的节点对不重新进灰区（merged_into 过滤）。"""
        a = _node(graph, "合并后不再提")
        b = _node(graph, "合并后不再提")
        resolver.run_adjudication(
            llm_call=lambda p: json.dumps({"verdict": "same", "confidence": 0.95})
        )
        assert resolver.find_candidates()["grey"] == []


class TestClosedLoopReview:
    """P1-1 闭环审查 WARN 补测：双向边合并、desc 漂移键、undo 现状优先。"""

    def test_merge_with_bidirectional_edges(self, graph):
        """src↔other 双向边 + src→src 自环合并：无重复边、无丢失。"""
        src = _node(graph, "甲公司")
        dst = _node(graph, "甲Corp")
        other = _node(graph, "某部门")
        graph.add_edge(source_id=src.node_id, target_id=other.node_id, relation_type=RelationType.RELATED_TO)
        graph.add_edge(source_id=other.node_id, target_id=src.node_id, relation_type=RelationType.RELATED_TO)
        graph.add_edge(source_id=src.node_id, target_id=src.node_id, relation_type=RelationType.RELATED_TO)  # 自环

        assert graph.merge_nodes(src.node_id, dst.node_id, reason="test") is True
        # dst↔other 双向仍在（各一条）
        assert len(graph.get_edges_between(dst.node_id, other.node_id)) == 1
        assert len(graph.get_edges_between(other.node_id, dst.node_id)) == 1
        # 自环被摘除（dst 上不存在 src→src 复制品）
        self_loops = [
            e for e in graph._edges.values()
            if e.source_id == dst.node_id and e.target_id == dst.node_id
        ]
        assert self_loops == []
        # undo：双向边翻回原端点，自环原路放回 src
        assert graph.undo_merge(src.node_id) is True
        assert len(graph.get_edges_between(src.node_id, other.node_id)) == 1
        assert len(graph.get_edges_between(other.node_id, src.node_id)) == 1
        assert any(
            e.source_id == src.node_id and e.target_id == src.node_id
            for e in graph._edges.values()
        )

    def test_pair_key_changes_when_description_changes(self, graph):
        """契约澄清：pair_key 的稳定性以 label+别名+类型不变为前提，
        description 参与签名（跨对撞名时用 top_facts 区分是 Utopia 原意）——
        重传不改 desc 不重复付费，改了 desc 视为新证据重新裁决。"""
        a1 = _node(graph, "同名实体", description="旧描述")
        a2 = _node(graph, "同名实体", description="旧描述")
        k1 = pair_key(a1, a2)
        a3 = _node(graph, "同名实体", description="全新完全不同的描述文本")
        k2 = pair_key(_node(graph, "同名实体", description="旧描述"), a3)
        assert k1 != k2

    def test_undo_after_third_party_edge_deletion(self, graph):
        """undo 现状优先：合并后边被第三方删除，undo 不复活它。"""
        src = _node(graph, "被合并方")
        dst = _node(graph, "存活方")
        other = _node(graph, "第三方")
        edge = graph.add_edge(source_id=src.node_id, target_id=other.node_id, relation_type=RelationType.RELATED_TO)
        assert graph.merge_nodes(src.node_id, dst.node_id, reason="test") is True
        # 第三方删除这条（现挂在 dst 上）
        assert graph.delete_edge(edge.edge_id) is True
        assert graph.undo_merge(src.node_id) is True
        assert graph.get_node(src.node_id) is not None  # 节点复活
        assert graph.get_edges_between(src.node_id, other.node_id) == []  # 边不复活
