// AnalyticsPage 数据分析页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AnalyticsViewHelper 视图模型行为（指标颜色/标签映射、粒度标签、
//           值格式化、趋势计算、最大点查找、按粒度时间戳格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AnalyticsPage.ets 导出的 AnalyticsViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AnalyticsViewHelper } from '../../../../main/ets/pages/AnalyticsPage';
import { AnalyticsPoint, AnalyticsGranularity } from '../../../../main/ets/libs/types';

export default function analyticsPageTest() {
  describe('AnalyticsPage', () => {
    // ========== 切片1: getMetricColor - messages_count → primary ==========

    it('metric_color_messages_returns_primary', 0, () => {
      expect(AnalyticsViewHelper.getMetricColor('messages_count')).assertEqual('primary');
    });

    // ========== 切片2: getMetricColor - token_usage → warning ==========

    it('metric_color_tokens_returns_warning', 0, () => {
      expect(AnalyticsViewHelper.getMetricColor('token_usage')).assertEqual('warning');
    });

    // ========== 切片3: getMetricColor - active_users → success ==========

    it('metric_color_active_users_returns_success', 0, () => {
      expect(AnalyticsViewHelper.getMetricColor('active_users')).assertEqual('success');
    });

    // ========== 切片4: getMetricColor - 未知指标 → info ==========

    it('metric_color_unknown_returns_info', 0, () => {
      expect(AnalyticsViewHelper.getMetricColor('unknown_metric')).assertEqual('info');
    });

    // ========== 切片5: getMetricLabel - messages_count → 消息数 ==========

    it('metric_label_messages_returns_消息数', 0, () => {
      expect(AnalyticsViewHelper.getMetricLabel('messages_count')).assertEqual('消息数');
    });

    // ========== 切片6: getMetricLabel - token_usage → Token 使用量 ==========

    it('metric_label_tokens_returns_Token使用量', 0, () => {
      expect(AnalyticsViewHelper.getMetricLabel('token_usage')).assertEqual('Token 使用量');
    });

    // ========== 切片7: getMetricLabel - active_users → 活跃用户 ==========

    it('metric_label_active_users_returns_活跃用户', 0, () => {
      expect(AnalyticsViewHelper.getMetricLabel('active_users')).assertEqual('活跃用户');
    });

    // ========== 切片8: getGranularityLabel - minute → 分钟 ==========

    it('granularity_label_minute_returns_分钟', 0, () => {
      expect(AnalyticsViewHelper.getGranularityLabel('minute')).assertEqual('分钟');
    });

    // ========== 切片9: getGranularityLabel - hour → 小时 ==========

    it('granularity_label_hour_returns_小时', 0, () => {
      expect(AnalyticsViewHelper.getGranularityLabel('hour')).assertEqual('小时');
    });

    // ========== 切片10: getGranularityLabel - day → 天 ==========

    it('granularity_label_day_returns_天', 0, () => {
      expect(AnalyticsViewHelper.getGranularityLabel('day')).assertEqual('天');
    });

    // ========== 切片11: getGranularityLabel - week → 周 ==========

    it('granularity_label_week_returns_周', 0, () => {
      expect(AnalyticsViewHelper.getGranularityLabel('week')).assertEqual('周');
    });

    // ========== 切片12: getGranularityLabel - month → 月 ==========

    it('granularity_label_month_returns_月', 0, () => {
      expect(AnalyticsViewHelper.getGranularityLabel('month')).assertEqual('月');
    });

    // ========== 切片13: formatValue - 整数 + 单位 ==========

    it('format_value_integer', 0, () => {
      expect(AnalyticsViewHelper.formatValue(100, '条')).assertEqual('100 条');
    });

    // ========== 切片14: formatValue - 小数 + 单位 ==========

    it('format_value_decimal', 0, () => {
      expect(AnalyticsViewHelper.formatValue(3.14, 'K')).assertEqual('3.14 K');
    });

    // ========== 切片15: calculateTrend - 上升 ==========

    it('calculate_trend_up', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 10 },
        { timestamp: '2025-03-02T00:00:00Z', value: 20 },
      ];
      // (20 - 10) / 10 * 100 = 100%
      expect(AnalyticsViewHelper.calculateTrend(points)).assertEqual('↑100%');
    });

    // ========== 切片16: calculateTrend - 下降 ==========

    it('calculate_trend_down', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 20 },
        { timestamp: '2025-03-02T00:00:00Z', value: 10 },
      ];
      // (10 - 20) / 20 * 100 = -50%, 取绝对值 → '↓50%'
      expect(AnalyticsViewHelper.calculateTrend(points)).assertEqual('↓50%');
    });

    // ========== 切片17: calculateTrend - 持平 ==========

    it('calculate_trend_flat', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 15 },
        { timestamp: '2025-03-02T00:00:00Z', value: 15 },
      ];
      expect(AnalyticsViewHelper.calculateTrend(points)).assertEqual('持平');
    });

    // ========== 切片18: calculateTrend - 单点 → '持平' ==========

    it('calculate_trend_single_point_returns_flat', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 10 },
      ];
      expect(AnalyticsViewHelper.calculateTrend(points)).assertEqual('持平');
    });

    // ========== 切片19: calculateTrend - 空数组 → '持平' ==========

    it('calculate_trend_empty_returns_flat', 0, () => {
      expect(AnalyticsViewHelper.calculateTrend([])).assertEqual('持平');
    });

    // ========== 切片20: getMaxPoint - 多点返回最大 ==========

    it('get_max_point_multiple', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 10 },
        { timestamp: '2025-03-02T00:00:00Z', value: 50 },
        { timestamp: '2025-03-03T00:00:00Z', value: 30 },
      ];
      const max = AnalyticsViewHelper.getMaxPoint(points);
      expect(max !== null).assertTrue();
      expect(max!.value).assertEqual(50);
    });

    // ========== 切片21: getMaxPoint - 单点 ==========

    it('get_max_point_single', 0, () => {
      const points: AnalyticsPoint[] = [
        { timestamp: '2025-03-01T00:00:00Z', value: 42 },
      ];
      const max = AnalyticsViewHelper.getMaxPoint(points);
      expect(max !== null).assertTrue();
      expect(max!.value).assertEqual(42);
    });

    // ========== 切片22: getMaxPoint - 空数组 → null ==========

    it('get_max_point_empty_returns_null', 0, () => {
      const max = AnalyticsViewHelper.getMaxPoint([]);
      expect(max).assertNull();
    });

    // ========== 切片23: formatPointTimestamp - minute 粒度 ==========

    it('format_point_ts_minute', 0, () => {
      const ts = '2025-03-01T10:30:45Z';
      const result = AnalyticsViewHelper.formatPointTimestamp(ts, 'minute');
      // minute 粒度: YYYY-MM-DD HH:mm (无秒)
      const pattern = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/;
      expect(pattern.test(result)).assertTrue();
    });

    // ========== 切片24: formatPointTimestamp - hour 粒度 ==========

    it('format_point_ts_hour', 0, () => {
      const ts = '2025-03-01T10:30:45Z';
      const result = AnalyticsViewHelper.formatPointTimestamp(ts, 'hour');
      // hour 粒度: YYYY-MM-DD HH:00
      const pattern = /^\d{4}-\d{2}-\d{2} \d{2}:00$/;
      expect(pattern.test(result)).assertTrue();
    });

    // ========== 切片25: formatPointTimestamp - day 粒度 ==========

    it('format_point_ts_day', 0, () => {
      const ts = '2025-03-01T10:30:45Z';
      const result = AnalyticsViewHelper.formatPointTimestamp(ts, 'day');
      // day 粒度: YYYY-MM-DD
      const pattern = /^\d{4}-\d{2}-\d{2}$/;
      expect(pattern.test(result)).assertTrue();
    });

    // ========== 切片26: formatPointTimestamp - month 粒度 ==========

    it('format_point_ts_month', 0, () => {
      const ts = '2025-03-01T10:30:45Z';
      const result = AnalyticsViewHelper.formatPointTimestamp(ts, 'month');
      // month 粒度: YYYY-MM
      const pattern = /^\d{4}-\d{2}$/;
      expect(pattern.test(result)).assertTrue();
    });

    // ========== 切片27: formatPointTimestamp - week 粒度 ==========

    it('format_point_ts_week', 0, () => {
      const ts = '2025-03-01T10:30:45Z';
      const result = AnalyticsViewHelper.formatPointTimestamp(ts, 'week');
      // week 粒度: YYYY-MM-DD (与 day 相同)
      const pattern = /^\d{4}-\d{2}-\d{2}$/;
      expect(pattern.test(result)).assertTrue();
    });
  });
}
