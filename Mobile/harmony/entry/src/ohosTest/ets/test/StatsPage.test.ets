// StatsPage 统计指标页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：StatsViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 StatsPage 导出的 StatsViewHelper 静态方法进行验证，
//       覆盖页面 getPeriodLabel / getTrendColor / getTrendIcon /
//       formatTrend / formatValue / truncateLabel 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { StatsViewHelper } from '../../../../main/ets/pages/StatsPage';

export default function statsPageTest() {
  describe('StatsPage', () => {
    // ========== 切片1: getPeriodLabel - day → 今日 ==========

    it('period_label_day_returns_today', 0, () => {
      expect(StatsViewHelper.getPeriodLabel('day')).assertEqual('今日');
    });

    // ========== 切片2: getPeriodLabel - week → 本周 ==========

    it('period_label_week_returns_this_week', 0, () => {
      expect(StatsViewHelper.getPeriodLabel('week')).assertEqual('本周');
    });

    // ========== 切片3: getPeriodLabel - month → 本月 ==========

    it('period_label_month_returns_this_month', 0, () => {
      expect(StatsViewHelper.getPeriodLabel('month')).assertEqual('本月');
    });

    // ========== 切片4: getPeriodLabel - year → 全年 ==========

    it('period_label_year_returns_this_year', 0, () => {
      expect(StatsViewHelper.getPeriodLabel('year')).assertEqual('全年');
    });

    // ========== 切片5: getTrendColor - 正数 → status_success ==========

    it('trend_color_positive_returns_status_success', 0, () => {
      expect(StatsViewHelper.getTrendColor(12)).assertEqual('status_success');
    });

    // ========== 切片6: getTrendColor - 负数 → status_error ==========

    it('trend_color_negative_returns_status_error', 0, () => {
      expect(StatsViewHelper.getTrendColor(-5)).assertEqual('status_error');
    });

    // ========== 切片7: getTrendColor - 零 → text_secondary ==========

    it('trend_color_zero_returns_text_secondary', 0, () => {
      expect(StatsViewHelper.getTrendColor(0)).assertEqual('text_secondary');
    });

    // ========== 切片8: getTrendIcon - 正数 → ↑ ==========

    it('trend_icon_positive_returns_up_arrow', 0, () => {
      expect(StatsViewHelper.getTrendIcon(12)).assertEqual('↑');
    });

    // ========== 切片9: getTrendIcon - 负数 → ↓ ==========

    it('trend_icon_negative_returns_down_arrow', 0, () => {
      expect(StatsViewHelper.getTrendIcon(-5)).assertEqual('↓');
    });

    // ========== 切片10: getTrendIcon - 零 → → ==========

    it('trend_icon_zero_returns_right_arrow', 0, () => {
      expect(StatsViewHelper.getTrendIcon(0)).assertEqual('→');
    });

    // ========== 切片11: formatTrend - 正数 → +12% ==========

    it('format_trend_positive_returns_plus_prefixed', 0, () => {
      expect(StatsViewHelper.formatTrend(12)).assertEqual('+12%');
    });

    // ========== 切片12: formatTrend - 负数 → -5% ==========

    it('format_trend_negative_returns_minus_prefixed', 0, () => {
      expect(StatsViewHelper.formatTrend(-5)).assertEqual('-5%');
    });

    // ========== 切片13: formatTrend - 零 → 0% ==========

    it('format_trend_zero_returns_zero_percent', 0, () => {
      expect(StatsViewHelper.formatTrend(0)).assertEqual('0%');
    });

    // ========== 切片14: formatValue - 无单位 → 纯数值 ==========

    it('format_value_without_unit_returns_value_only', 0, () => {
      expect(StatsViewHelper.formatValue(128)).assertEqual('128');
    });

    // ========== 切片15: formatValue - 有单位 → 数值+单位 ==========

    it('format_value_with_unit_returns_value_and_unit', 0, () => {
      expect(StatsViewHelper.formatValue(128, '个')).assertEqual('128个');
    });

    // ========== 切片16: formatValue - 单位为空字符串 → 纯数值 ==========

    it('format_value_empty_unit_returns_value_only', 0, () => {
      expect(StatsViewHelper.formatValue(128, '')).assertEqual('128');
    });

    // ========== 切片17: truncateLabel - 短标签原样返回 ==========

    it('truncate_label_short_returns_original', 0, () => {
      expect(StatsViewHelper.truncateLabel('会话数', 16)).assertEqual('会话数');
    });

    // ========== 切片18: truncateLabel - 等于最大长度原样返回 ==========

    it('truncate_label_equal_length_returns_original', 0, () => {
      const label = 'abcdefghijklmnop'; // 16 字符
      expect(StatsViewHelper.truncateLabel(label, 16)).assertEqual(label);
    });

    // ========== 切片19: truncateLabel - 超长截断加省略号 ==========

    it('truncate_label_over_max_returns_ellipsis', 0, () => {
      const label = '这是一个非常长的统计指标标签需要被截断处理一下';
      const result = StatsViewHelper.truncateLabel(label, 16);
      expect(result.length).assertEqual(19); // 16 + '...'
      expect(result.substring(16)).assertEqual('...');
    });
  });
}
