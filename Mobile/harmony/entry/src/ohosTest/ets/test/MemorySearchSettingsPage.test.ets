// MemorySearchSettingsPage 记忆搜索设置页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：MemorySearchSettingsViewHelper 视图模型行为（策略颜色、策略标签、topK 格式化、
//           minScore 颜色、minScore 格式化、过滤器格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 MemorySearchSettingsPage.ets 导出的 MemorySearchSettingsViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { MemorySearchSettingsViewHelper } from '../../../../main/ets/pages/MemorySearchSettingsPage';

export default function memorySearchSettingsPageTest() {
  describe('MemorySearchSettingsPage', () => {
    // ========== 切片1: getStrategyColor - semantic → primary ==========

    it('strategy_color_semantic_returns_primary', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyColor('semantic')).assertEqual('primary');
    });

    // ========== 切片2: getStrategyColor - keyword → info ==========

    it('strategy_color_keyword_returns_info', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyColor('keyword')).assertEqual('info');
    });

    // ========== 切片3: getStrategyColor - hybrid → success ==========

    it('strategy_color_hybrid_returns_success', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyColor('hybrid')).assertEqual('success');
    });

    // ========== 切片4: getStrategyColor - temporal → warning ==========

    it('strategy_color_temporal_returns_warning', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyColor('temporal')).assertEqual('warning');
    });

    // ========== 切片5: getStrategyLabel - semantic → 语义搜索 ==========

    it('strategy_label_semantic_returns_语义搜索', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyLabel('semantic')).assertEqual('语义搜索');
    });

    // ========== 切片6: getStrategyLabel - keyword → 关键词搜索 ==========

    it('strategy_label_keyword_returns_关键词搜索', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyLabel('keyword')).assertEqual('关键词搜索');
    });

    // ========== 切片7: getStrategyLabel - hybrid → 混合搜索 ==========

    it('strategy_label_hybrid_returns_混合搜索', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyLabel('hybrid')).assertEqual('混合搜索');
    });

    // ========== 切片8: getStrategyLabel - temporal → 时间搜索 ==========

    it('strategy_label_temporal_returns_时间搜索', 0, () => {
      expect(MemorySearchSettingsViewHelper.getStrategyLabel('temporal')).assertEqual('时间搜索');
    });

    // ========== 切片9: formatTopK - 5 → "5 条结果" ==========

    it('format_topK_5_returns_5条结果', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatTopK(5)).assertEqual('5 条结果');
    });

    // ========== 切片10: formatTopK - 0 → "0 条结果" ==========

    it('format_topK_0_returns_0条结果', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatTopK(0)).assertEqual('0 条结果');
    });

    // ========== 切片11: formatTopK - 100 → "100 条结果" ==========

    it('format_topK_100_returns_100条结果', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatTopK(100)).assertEqual('100 条结果');
    });

    // ========== 切片12: getMinScoreColor - < 0.3 → text_secondary ==========

    it('min_score_color_below_03_returns_text_secondary', 0, () => {
      expect(MemorySearchSettingsViewHelper.getMinScoreColor(0.1)).assertEqual('text_secondary');
    });

    // ========== 切片13: getMinScoreColor - 0.3 → info（下界） ==========

    it('min_score_color_03_returns_info', 0, () => {
      expect(MemorySearchSettingsViewHelper.getMinScoreColor(0.3)).assertEqual('info');
    });

    // ========== 切片14: getMinScoreColor - 0.5 → info（中段） ==========

    it('min_score_color_05_returns_info', 0, () => {
      expect(MemorySearchSettingsViewHelper.getMinScoreColor(0.5)).assertEqual('info');
    });

    // ========== 切片15: getMinScoreColor - 0.7 → info（上界） ==========

    it('min_score_color_07_returns_info', 0, () => {
      expect(MemorySearchSettingsViewHelper.getMinScoreColor(0.7)).assertEqual('info');
    });

    // ========== 切片16: getMinScoreColor - > 0.7 → success ==========

    it('min_score_color_above_07_returns_success', 0, () => {
      expect(MemorySearchSettingsViewHelper.getMinScoreColor(0.9)).assertEqual('success');
    });

    // ========== 切片17: formatMinScore - 0.5 → "0.5"（1 位小数） ==========

    it('format_min_score_05_returns_05', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatMinScore(0.5)).assertEqual('0.5');
    });

    // ========== 切片18: formatMinScore - 1 → "1.0"（1 位小数） ==========

    it('format_min_score_1_returns_10', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatMinScore(1)).assertEqual('1.0');
    });

    // ========== 切片19: formatMinScore - 0.3 → "0.3" ==========

    it('format_min_score_03_returns_03', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatMinScore(0.3)).assertEqual('0.3');
    });

    // ========== 切片20: formatFilters - undefined → "无过滤器" ==========

    it('format_filters_undefined_returns_无过滤器', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatFilters(undefined)).assertEqual('无过滤器');
    });

    // ========== 切片21: formatFilters - 有过滤器 → JSON 字符串 ==========

    it('format_filters_with_object_returns_json', 0, () => {
      const filters = { types: ['long_term', 'short_term'] };
      const result = MemorySearchSettingsViewHelper.formatFilters(filters);
      expect(result).assertEqual(JSON.stringify(filters));
    });

    // ========== 切片22: formatFilters - 空对象 → "{}" ==========

    it('format_filters_empty_object_returns_json', 0, () => {
      expect(MemorySearchSettingsViewHelper.formatFilters({})).assertEqual('{}');
    });

    // ========== 切片23: formatFilters - 带日期范围 → JSON 字符串 ==========

    it('format_filters_with_date_range_returns_json', 0, () => {
      const filters = {
        types: ['long_term'],
        tags: ['important'],
        dateRange: { start: '2025-01-01', end: '2025-06-01' },
      };
      const result = MemorySearchSettingsViewHelper.formatFilters(filters);
      expect(result).assertEqual(JSON.stringify(filters));
    });
  });
}
