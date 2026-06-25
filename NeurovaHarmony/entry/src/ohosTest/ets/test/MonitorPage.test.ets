// MonitorPage 监控指标页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：MonitorViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 MonitorPage 导出的 MonitorViewHelper 静态方法进行验证，
//       覆盖页面 formatMetricValue / formatTimestamp / getTagColor /
//       truncateMetricName / isStaleMetric 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { MonitorViewHelper } from '../../../../main/ets/pages/MonitorPage';

export default function monitorPageTest() {
  describe('MonitorPage', () => {
    // ========== 切片1: formatMetricValue - 数值+单位 ==========

    it('format_metric_value_with_unit_returns_value_and_unit', 0, () => {
      expect(MonitorViewHelper.formatMetricValue(42, '%')).assertEqual('42%');
    });

    // ========== 切片2: formatMetricValue - 单位为空字符串 ==========

    it('format_metric_value_empty_unit_returns_value_only', 0, () => {
      expect(MonitorViewHelper.formatMetricValue(42, '')).assertEqual('42');
    });

    // ========== 切片3: formatMetricValue - 小数数值 ==========

    it('format_metric_value_decimal_value_with_unit', 0, () => {
      expect(MonitorViewHelper.formatMetricValue(3.14, 'ratio')).assertEqual('3.14ratio');
    });

    // ========== 切片4: formatTimestamp - 标准 ISO 时间 → HH:mm:ss ==========

    it('format_timestamp_iso_returns_hms', 0, () => {
      // '2026-06-25T14:30:45.123Z' → '14:30:45'
      expect(MonitorViewHelper.formatTimestamp('2026-06-25T14:30:45.123Z')).assertEqual('14:30:45');
    });

    // ========== 切片5: formatTimestamp - 另一 ISO 时间 ==========

    it('format_timestamp_another_iso_returns_hms', 0, () => {
      expect(MonitorViewHelper.formatTimestamp('2026-01-01T08:05:09Z')).assertEqual('08:05:09');
    });

    // ========== 切片6: formatTimestamp - 空字符串 → '-' ==========

    it('format_timestamp_empty_returns_dash', 0, () => {
      expect(MonitorViewHelper.formatTimestamp('')).assertEqual('-');
    });

    // ========== 切片7: formatTimestamp - 非法时间 → '-' ==========

    it('format_timestamp_invalid_returns_dash', 0, () => {
      expect(MonitorViewHelper.formatTimestamp('not-a-timestamp')).assertEqual('-');
    });

    // ========== 切片8: getTagColor - 'cpu' 标签 ==========

    it('get_tag_color_cpu_returns_stable_token', 0, () => {
      // 同一 tagKey 多次调用必须返回同一 token（稳定映射）
      const a = MonitorViewHelper.getTagColor('cpu');
      const b = MonitorViewHelper.getTagColor('cpu');
      expect(a).assertEqual(b);
      // 返回的是 StyleManager token 名（非颜色值）
      expect(typeof a === 'string' && a.length > 0).assertTrue();
    });

    // ========== 切片9: getTagColor - 'memory' 标签 ==========

    it('get_tag_color_memory_returns_stable_token', 0, () => {
      const a = MonitorViewHelper.getTagColor('memory');
      const b = MonitorViewHelper.getTagColor('memory');
      expect(a).assertEqual(b);
      expect(typeof a === 'string' && a.length > 0).assertTrue();
    });

    // ========== 切片10: getTagColor - 不同 tagKey 可返回不同 token ==========

    it('get_tag_color_different_keys_may_differ', 0, () => {
      // 至少保证返回值合法；不同 tag 允许相同 token，但应稳定
      const cpuColor = MonitorViewHelper.getTagColor('cpu');
      const memColor = MonitorViewHelper.getTagColor('memory');
      const netColor = MonitorViewHelper.getTagColor('network');
      // 三者均为非空字符串
      expect(typeof cpuColor === 'string' && cpuColor.length > 0).assertTrue();
      expect(typeof memColor === 'string' && memColor.length > 0).assertTrue();
      expect(typeof netColor === 'string' && netColor.length > 0).assertTrue();
    });

    // ========== 切片11: getTagColor - 未知 tag 仍有默认 token ==========

    it('get_tag_color_unknown_returns_default_token', 0, () => {
      const color = MonitorViewHelper.getTagColor('totally-unknown-tag-xyz');
      expect(typeof color === 'string' && color.length > 0).assertTrue();
    });

    // ========== 切片12: truncateMetricName - 短名称原样返回 ==========

    it('truncate_metric_name_short_returns_original', 0, () => {
      expect(MonitorViewHelper.truncateMetricName('cpu', 16)).assertEqual('cpu');
    });

    // ========== 切片13: truncateMetricName - 等于最大长度原样返回 ==========

    it('truncate_metric_name_equal_length_returns_original', 0, () => {
      const name = 'abcdefghijklmnop'; // 16 字符
      expect(MonitorViewHelper.truncateMetricName(name, 16)).assertEqual(name);
    });

    // ========== 切片14: truncateMetricName - 超长截断加省略号 ==========

    it('truncate_metric_name_over_max_returns_ellipsis', 0, () => {
      const name = 'system.cpu.usage.percentage.total';
      const result = MonitorViewHelper.truncateMetricName(name, 16);
      expect(result.length).assertEqual(19); // 16 + '...'
      expect(result.substring(16)).assertEqual('...');
    });

    // ========== 切片15: isStaleMetric - 新鲜指标 → false ==========

    it('is_stale_metric_fresh_returns_false', 0, () => {
      // 当前时间作为 timestamp，阈值为 1 小时（3600000ms），差值为 0 → 不过期
      const now = new Date().toISOString();
      expect(MonitorViewHelper.isStaleMetric(now, 3600000)).assertFalse();
    });

    // ========== 切片16: isStaleMetric - 过期指标 → true ==========

    it('is_stale_metric_stale_returns_true', 0, () => {
      // 1 天前的时间戳，阈值为 1 小时 → 过期
      const oneDayAgo = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
      expect(MonitorViewHelper.isStaleMetric(oneDayAgo, 3600000)).assertTrue();
    });

    // ========== 切片17: isStaleMetric - 非法时间戳 → true（视为过期） ==========

    it('is_stale_metric_invalid_timestamp_returns_true', 0, () => {
      expect(MonitorViewHelper.isStaleMetric('not-a-timestamp', 1000)).assertTrue();
    });

    // ========== 切片18: isStaleMetric - 空时间戳 → true ==========

    it('is_stale_metric_empty_timestamp_returns_true', 0, () => {
      expect(MonitorViewHelper.isStaleMetric('', 1000)).assertTrue();
    });
  });
}
