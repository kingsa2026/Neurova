// HealthPage 系统健康页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：HealthViewHelper 视图模型行为（状态颜色映射、分数颜色映射、延迟颜色映射、相对时间格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 HealthPage.ets 导出的 HealthViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getScoreColor / getLatencyColor / formatRelativeTime 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { HealthViewHelper } from '../../../../main/ets/pages/HealthPage';

export default function healthPageTest() {
  describe('HealthPage', () => {
    // ========== 切片1: getStatusColor - healthy → success ==========

    it('status_color_healthy_returns_success', 0, () => {
      expect(HealthViewHelper.getStatusColor('healthy')).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - degraded → warning ==========

    it('status_color_degraded_returns_warning', 0, () => {
      expect(HealthViewHelper.getStatusColor('degraded')).assertEqual('warning');
    });

    // ========== 切片3: getStatusColor - down → error ==========

    it('status_color_down_returns_error', 0, () => {
      expect(HealthViewHelper.getStatusColor('down')).assertEqual('error');
    });

    // ========== 切片4: getStatusColor - unknown → text_disabled ==========

    it('status_color_unknown_returns_text_disabled', 0, () => {
      expect(HealthViewHelper.getStatusColor('unknown')).assertEqual('text_disabled');
    });

    // ========== 切片5: getScoreColor - ≥80 → success ==========

    it('score_color_high_returns_success', 0, () => {
      expect(HealthViewHelper.getScoreColor(80)).assertEqual('success');
    });

    // ========== 切片6: getScoreColor - 50-79 → warning ==========

    it('score_color_medium_returns_warning', 0, () => {
      expect(HealthViewHelper.getScoreColor(60)).assertEqual('warning');
    });

    // ========== 切片7: getScoreColor - <50 → error ==========

    it('score_color_low_returns_error', 0, () => {
      expect(HealthViewHelper.getScoreColor(30)).assertEqual('error');
    });

    // ========== 切片8: getLatencyColor - <100ms → success ==========

    it('latency_color_fast_returns_success', 0, () => {
      expect(HealthViewHelper.getLatencyColor(50)).assertEqual('success');
    });

    // ========== 切片9: getLatencyColor - 100-500ms → warning ==========

    it('latency_color_medium_returns_warning', 0, () => {
      expect(HealthViewHelper.getLatencyColor(200)).assertEqual('warning');
    });

    // ========== 切片10: getLatencyColor - >500ms → error ==========

    it('latency_color_slow_returns_error', 0, () => {
      expect(HealthViewHelper.getLatencyColor(800)).assertEqual('error');
    });

    // ========== 切片11: getLatencyColor - undefined → text_disabled ==========

    it('latency_color_undefined_returns_disabled', 0, () => {
      expect(HealthViewHelper.getLatencyColor(undefined)).assertEqual('text_disabled');
    });

    // ========== 切片12: formatRelativeTime - <60s → "刚刚" ==========

    it('format_relative_time_seconds_returns_just_now', 0, () => {
      const now = Date.now();
      expect(HealthViewHelper.formatRelativeTime(now)).assertEqual('刚刚');
    });

    // ========== 切片13: formatRelativeTime - <60min → "X 分钟前" ==========

    it('format_relative_time_minutes_returns_x_minutes_ago', 0, () => {
      const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
      expect(HealthViewHelper.formatRelativeTime(fiveMinutesAgo)).assertEqual('5 分钟前');
    });

    // ========== 切片14: formatRelativeTime - <24h → "X 小时前" ==========

    it('format_relative_time_hours_returns_x_hours_ago', 0, () => {
      const threeHoursAgo = Date.now() - 3 * 60 * 60 * 1000;
      expect(HealthViewHelper.formatRelativeTime(threeHoursAgo)).assertEqual('3 小时前');
    });
  });
}
