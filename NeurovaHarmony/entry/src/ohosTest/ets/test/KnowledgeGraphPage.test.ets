// KnowledgeGraphPage 知识图谱页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：KnowledgeGraphViewHelper 视图模型行为（节点类型颜色映射、节点类型图标映射、
//           节点类型中文标签、平均权重计算、关联边查找）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 KnowledgeGraphPage.ets 导出的 KnowledgeGraphViewHelper
//       静态方法进行验证，覆盖页面 getNodeTypeColor / getNodeTypeIcon / getNodeTypeLabel /
//       calculateAvgWeight / findRelatedEdges 的核心视图逻辑，并包含边界场景。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { KnowledgeGraphViewHelper } from '../../../../main/ets/pages/KnowledgeGraphPage';
import { KnowledgeNode, KnowledgeEdge } from '../../../../main/ets/libs/types';

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

    // ========== 切片4: getNodeTypeColor - fact → primary ==========

    it('node_type_color_fact_returns_primary', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeColor('fact')).assertEqual('primary');
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

    // ========== 切片8: getNodeTypeIcon - fact → 📌 ==========

    it('node_type_icon_fact_returns_pin', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeIcon('fact')).assertEqual('📌');
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

    // ========== 切片12: getNodeTypeLabel - fact → 事实 ==========

    it('node_type_label_fact_returns_chinese', 0, () => {
      expect(KnowledgeGraphViewHelper.getNodeTypeLabel('fact')).assertEqual('事实');
    });

    // ========== 切片13: calculateAvgWeight - 正常求平均 ==========

    it('calculate_avg_weight_basic', 0, () => {
      const nodes: KnowledgeNode[] = [
        { id: 'n1', agentId: 'a1', label: 'A', type: 'concept', weight: 0.5 },
        { id: 'n2', agentId: 'a1', label: 'B', type: 'entity', weight: 0.3 },
        { id: 'n3', agentId: 'a1', label: 'C', type: 'event', weight: 0.4 },
      ];
      // (0.5 + 0.3 + 0.4) / 3 = 0.4
      expect(KnowledgeGraphViewHelper.calculateAvgWeight(nodes)).assertEqual(0.4);
    });

    // ========== 切片14: calculateAvgWeight - 空数组 → 0 ==========

    it('calculate_avg_weight_empty_returns_zero', 0, () => {
      expect(KnowledgeGraphViewHelper.calculateAvgWeight([])).assertEqual(0);
    });

    // ========== 切片15: calculateAvgWeight - 无 weight 视为 0 ==========

    it('calculate_avg_weight_no_weight_treats_as_zero', 0, () => {
      const nodes: KnowledgeNode[] = [
        { id: 'n1', agentId: 'a1', label: 'A', type: 'concept', weight: 0.6 },
        { id: 'n2', agentId: 'a1', label: 'B', type: 'entity' },  // 无 weight
      ];
      // (0.6 + 0) / 2 = 0.3
      expect(KnowledgeGraphViewHelper.calculateAvgWeight(nodes)).assertEqual(0.3);
    });

    // ========== 切片16: findRelatedEdges - 同时匹配 source 与 target ==========

    it('find_related_edges_returns_incoming_and_outgoing', 0, () => {
      const edges: KnowledgeEdge[] = [
        { id: 'e1', source: 'n1', target: 'n2', relation: 'r1' },
        { id: 'e2', source: 'n3', target: 'n1', relation: 'r2' },
        { id: 'e3', source: 'n2', target: 'n3', relation: 'r3' },  // 不关联 n1
      ];
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', edges);
      expect(result.length).assertEqual(2);
      expect(result[0].id).assertEqual('e1');
      expect(result[1].id).assertEqual('e2');
    });

    // ========== 切片17: findRelatedEdges - 无匹配返回空数组 ==========

    it('find_related_edges_no_match_returns_empty', 0, () => {
      const edges: KnowledgeEdge[] = [
        { id: 'e1', source: 'n2', target: 'n3', relation: 'r1' },
      ];
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', edges);
      expect(result.length).assertEqual(0);
    });

    // ========== 切片18: findRelatedEdges - 空 edges 数组 ==========

    it('find_related_edges_empty_edges_returns_empty', 0, () => {
      const result = KnowledgeGraphViewHelper.findRelatedEdges('n1', []);
      expect(result.length).assertEqual(0);
    });
  });
}
