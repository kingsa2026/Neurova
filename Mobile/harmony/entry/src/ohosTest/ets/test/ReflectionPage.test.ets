// ReflectionPage 反思记录页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ReflectionViewHelper 视图模型行为（洞察数文案、改进项数文案、内容截断、
//           触发原因截断、相对时间格式化的今天/昨天/本周/其他边界场景）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ReflectionPage.ets 导出的 ReflectionViewHelper 静态方法进行验证，
//       覆盖页面 getInsightCount / getImprovementCount / truncateContent / truncateTrigger /
//       formatRelativeTime 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ReflectionViewHelper } from '../../../../main/ets/pages/ReflectionPage';

export default function reflectionPageTest() {
  describe('ReflectionPage', () => {
    // ========== 切片1: getInsightCount - 0 → "无洞察" ==========

    it('insight_count_zero_returns_empty_text', 0, () => {
      expect(ReflectionViewHelper.getInsightCount(0)).assertEqual('无洞察');
    });

    // ========== 切片2: getInsightCount - 正数 → "洞察 n 条" ==========

    it('insight_count_positive_returns_count_text', 0, () => {
      expect(ReflectionViewHelper.getInsightCount(3)).assertEqual('洞察 3 条');
    });

    // ========== 切片3: getImprovementCount - 0 → "无改进" ==========

    it('improvement_count_zero_returns_empty_text', 0, () => {
      expect(ReflectionViewHelper.getImprovementCount(0)).assertEqual('无改进');
    });

    // ========== 切片4: getImprovementCount - 正数 → "改进 n 项" ==========

    it('improvement_count_positive_returns_count_text', 0, () => {
      expect(ReflectionViewHelper.getImprovementCount(2)).assertEqual('改进 2 项');
    });

    // ========== 切片5: truncateContent - 默认 150 截断加省略号 ==========

    it('truncate_content_default_150_truncates', 0, () => {
      const long = 'a'.repeat(200);
      const result = ReflectionViewHelper.truncateContent(long);
      expect(result.length).assertEqual(153);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片6: truncateContent - 自定义长度 ==========

    it('truncate_content_custom_length_truncates', 0, () => {
      const long = 'b'.repeat(100);
      const result = ReflectionViewHelper.truncateContent(long, 50);
      expect(result.length).assertEqual(53);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片7: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      expect(ReflectionViewHelper.truncateContent('short text')).assertEqual('short text');
    });

    // ========== 切片8: truncateTrigger - 默认 60 截断 ==========

    it('truncate_trigger_default_60_truncates', 0, () => {
      const long = 'x'.repeat(100);
      const result = ReflectionViewHelper.truncateTrigger(long);
      expect(result.length).assertEqual(63);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片9: formatRelativeTime - 今天 → "今天 HH:mm" ==========

    it('format_relative_time_today_returns_today_prefix', 0, () => {
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 30);
      const result = ReflectionViewHelper.formatRelativeTime(today.toISOString());
      expect(result).assertEqual('今天 14:30');
    });

    // ========== 切片10: formatRelativeTime - 昨天 → "昨天 HH:mm" ==========

    it('format_relative_time_yesterday_returns_yesterday_prefix', 0, () => {
      const now = new Date();
      const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 9, 15);
      const result = ReflectionViewHelper.formatRelativeTime(yesterday.toISOString());
      expect(result).assertEqual('昨天 09:15');
    });

    // ========== 切片11: formatRelativeTime - 本周（非今昨）→ "周X HH:mm" ==========

    it('format_relative_time_this_week_returns_weekday_prefix', 0, () => {
      const now = new Date();
      const threeDaysAgo = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 3, 10, 0);
      const result = ReflectionViewHelper.formatRelativeTime(threeDaysAgo.toISOString());
      expect(result.startsWith('周')).assertTrue();
      expect(result.endsWith(' 10:00')).assertTrue();
    });

    // ========== 切片12: formatRelativeTime - 超过一周 → "YYYY-MM-DD" ==========

    it('format_relative_time_older_returns_date_only', 0, () => {
      const old = new Date(2020, 0, 15, 12, 0);
      const result = ReflectionViewHelper.formatRelativeTime(old.toISOString());
      expect(result).assertEqual('2020-01-15');
    });

    // ========== 切片13: formatRelativeTime - 空值 → "未知" ==========

    it('format_relative_time_empty_returns_unknown', 0, () => {
      expect(ReflectionViewHelper.formatRelativeTime('')).assertEqual('未知');
    });

    // ========== 切片14: formatRelativeTime - 无效日期 → "未知" ==========

    it('format_relative_time_invalid_returns_unknown', 0, () => {
      expect(ReflectionViewHelper.formatRelativeTime('not-a-date')).assertEqual('未知');
    });
  });
}
