// KnowledgeGraphPage 知识图谱页单元测试 - 真实契约版
//
// 测试范围：KnowledgeGraphViewHelper 视图模型行为（节点类型颜色/图标/中文标签映射、
//           关系类型中文标签、平均权重计算、关联边查找）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 KnowledgeGraphPage.ets 导出的 KnowledgeGraphViewHelper
//       静态方法进行验证，覆盖页面 getNodeTypeColor / getNodeTypeIcon / getNodeTypeLabel /
//       relationLabel / calculateAvgWeight / findRelatedEdges 的核心视图逻辑，并包含边界场景。
// 词汇说明：节点类型与后端 NodeType 枚举同源（concept/entity/event/memory）。
import { describe, it, expect } from '@ohos/hypium';
import { KnowledgeGraphViewHelper } from '../../../../main/ets/pages/KnowledgeGraphPage';
import { GraphNodeDto, GraphEdgeDto } from '../../../../main/ets/libs/api/modules/CognitionApi';

export default function knowledgeGraphPageTest() {
  describe('KnowledgeGraphPage', () => {
    // ========== 切片1: getNodeTypeColor - concept → info ==========

    it('node_type_color_concept_returns_info', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeColor('concept')).assertEqual('info');
    });

    // ========== 切片2: getNodeTypeColor - entity → success ==========

    it('node_type_color_entity_returns_success', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeColor('entity')).assertEqual('success');
    });

    // ========== 切片3: getNodeTypeColor - event → warning ==========

    it('node_type_color_event_returns_warning', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeColor('event')).assertEqual('warning');
    });

    // ========== 切片4: getNodeTypeColor - memory → primary ==========

    it('node_type_color_memory_returns_primary', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeColor('memory')).assertEqual('primary');
    });

    // ========== 切片5: getNodeTypeIcon - concept → 💡 ==========

    it('node_type_icon_concept_returns_bulb', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeIcon('concept')).assertEqual('💡');
    });

    // ========== 切片6: getNodeTypeIcon - entity → 🎯 ==========

    it('node_type_icon_entity_returns_target', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeIcon('entity')).assertEqual('🎯');
    });

    // ========== 切片7: getNodeTypeIcon - event → ⚡ ==========

    it('node_type_icon_event_returns_bolt', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeIcon('event')).assertEqual('⚡');
    });

    // ========== 切片8: getNodeTypeIcon - memory → 🧠 ==========

    it('node_type_icon_memory_returns_brain', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeIcon('memory')).assertEqual('🧠');
    });

    // ========== 切片9: getNodeTypeLabel - concept → 概念 ==========

    it('node_type_label_concept_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeLabel('concept')).assertEqual('概念');
    });

    // ========== 切片10: getNodeTypeLabel - entity → 实体 ==========

    it('node_type_label_entity_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeLabel('entity')).assertEqual('实体');
    });

    // ========== 切片11: getNodeTypeLabel - event → 事件 ==========

    it('node_type_label_event_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeLabel('event')).assertEqual('事件');
    });

    // ========== 切片12: getNodeTypeLabel - memory → 记忆 ==========

    it('node_type_label_memory_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeLabel('memory')).assertEqual('记忆');
    });

    // ========== 切片13: relationLabel - 已知关系 → 中文，未知原样 ==========

    it('relation_label_known_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.relationLabel('is_a')).assertEqual('是一种');
      expect(KnowledgeGraphViewHelper.relationLabel('causes')).assertEqual('导致');
      expect(KnowledgeGraphViewHelper.relationLabel('opposite_of')).assertEqual('相反');
    });

    it('relation_label_unknown_returns_raw', 0, () => {
      expect(KnowledgeGraphViewHelper.relationLabel('custom_rel')).assertEqual('custom_rel');
    });

    // ========== 切片14: calculateAvgWeight - 正常求平均 ==========

    it('calculate_avg_weight_basic', 0, () => {
      const nodes: GraphNodeDto[] = [
        { id: 'n1', label: 'A', type: 'concept', description: '', weight: 0.5, created_at: null },
        { id: 'n2', label: 'B', type: 'entity', description: '', weight: 0.3, created_at: null },
        { id: 'n3', label: 'C', type: 'event', description: '', weight: 0.4, created_at: null },
      ];
      // (0.5 + 0.3 + 0.4) / 3 = 0.4
      expect(KnowledgeGraphViewHelper.calculateAvgWeight(nodes)).assertEqual(0.4);
    });

    // ========== 切片15: calculateAvgWeight - 空数组 → 0 ==========

    it('calculate_avg_weight_empty_returns_zero', 0, () => {
      expect(KnowledgeGraphViewHelper.calculateAvgWeight([])).assertEqual(0);
    });

    // ========== 切片16: calculateAvgWeight - 零权重节点计入分母 ==========

    it('calculate_avg_weight_zero_weight_counts_in_denominator', 0, () => {
      const nodes: GraphNodeDto[] = [
        { id: 'n1', label: 'A', type: 'concept', description: '', weight: 0.6, created_at: null },
        { id: 'n2', label: 'B', type: 'entity', description: '', weight: 0, created_at: null },
      ];
      // (0.6 + 0) / 2 = 0.3
      expect(KnowledgeGraphViewHelper.calculateAvgWeight(nodes)).assertEqual(0.3);
    });

    // ========== 切片17: findRelatedEdges - 同时匹配 source 与 target ==========

    it('find_related_edges_returns_incoming_and_outgoing', 0, () => {
      const edges: GraphEdgeDto[] = [
        { source: 'n1', target: 'n2', relation: 'is_a', weight: 1 },
        { source: 'n3', target: 'n1', relation: 'causes', weight: 1 },
        { source: 'n2', target: 'n3', relation: 'related_to', weight: 1 },  // 不关联 n1
      ];
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', edges);
      expect(result.length).assertEqual(2);
      expect(result[0].relation).assertEqual('is_a');
      expect(result[1].relation).assertEqual('causes');
    });

    // ========== 切片18: findRelatedEdges - 无匹配返回空数组 ==========

    it('find_related_edges_no_match_returns_empty', 0, () => {
      const edges: GraphEdgeDto[] = [
        { source: 'n2', target: 'n3', relation: 'is_a', weight: 1 },
      ];
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', edges);
      expect(result.length).assertEqual(0);
    });

    // ========== 切片19: findRelatedEdges - 空 edges 数组 ==========

    it('find_related_edges_empty_edges_returns_empty', 0, () => {
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', []);
      expect(result.length).assertEqual(0);
    });
  });
}
