// NotificationPage 通知页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：NotificationViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 NotificationPage 导出的 NotificationViewHelper 静态方法进行验证，
//       覆盖页面 getTypeColor / getTypeIcon / getTypeLabel / getReadStatusColor /
//       formatCreatedAt / truncateTitle 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'warning'/'error'/
//   'success'/'text_secondary'），不加 'status_' 前缀，与 TaskPage/ProjectPage 现有模式一致。
import { describe, it, expect } from '@ohos/hypium';
import { NotificationViewHelper } from '../../../../main/ets/pages/NotificationPage';
import { NotificationType } from '../../../../main/ets/libs/types';

export default function notificationPageTest() {
  describe('NotificationPage', () => {
    // ========== 切片1: getTypeColor - info → info ==========

    it('type_color_info_returns_info', 0, () => {
      expect(NotificationViewHelper.getTypeColor('info' as NotificationType)).assertEqual('info');
    });

    // ========== 切片2: getTypeColor - success → success ==========

    it('type_color_success_returns_success', 0, () => {
      expect(NotificationViewHelper.getTypeColor('success' as NotificationType)).assertEqual('success');
    });

    // ========== 切片3: getTypeColor - warning → warning ==========

    it('type_color_warning_returns_warning', 0, () => {
      expect(NotificationViewHelper.getTypeColor('warning' as NotificationType)).assertEqual('warning');
    });

    // ========== 切片4: getTypeColor - error → error ==========

    it('type_color_error_returns_error', 0, () => {
      expect(NotificationViewHelper.getTypeColor('error' as NotificationType)).assertEqual('error');
    });

    // ========== 切片5: getTypeIcon - info → ℹ️ ==========

    it('type_icon_info_returns_info_emoji', 0, () => {
      expect(NotificationViewHelper.getTypeIcon('info' as NotificationType)).assertEqual('ℹ️');
    });

    // ========== 切片6: getTypeIcon - success → ✅ ==========

    it('type_icon_success_returns_check_emoji', 0, () => {
      expect(NotificationViewHelper.getTypeIcon('success' as NotificationType)).assertEqual('✅');
    });

    // ========== 切片7: getTypeIcon - warning → ⚠️ ==========

    it('type_icon_warning_returns_warning_emoji', 0, () => {
      expect(NotificationViewHelper.getTypeIcon('warning' as NotificationType)).assertEqual('⚠️');
    });

    // ========== 切片8: getTypeIcon - error → ❌ ==========

    it('type_icon_error_returns_cross_emoji', 0, () => {
      expect(NotificationViewHelper.getTypeIcon('error' as NotificationType)).assertEqual('❌');
    });

    // ========== 切片9: getTypeLabel - info → 信息 ==========

    it('type_label_info_returns_xinxi', 0, () => {
      expect(NotificationViewHelper.getTypeLabel('info' as NotificationType)).assertEqual('信息');
    });

    // ========== 切片10: getTypeLabel - success → 成功 ==========

    it('type_label_success_returns_chenggong', 0, () => {
      expect(NotificationViewHelper.getTypeLabel('success' as NotificationType)).assertEqual('成功');
    });

    // ========== 切片11: getTypeLabel - warning → 警告 ==========

    it('type_label_warning_returns_jinggao', 0, () => {
      expect(NotificationViewHelper.getTypeLabel('warning' as NotificationType)).assertEqual('警告');
    });

    // ========== 切片12: getTypeLabel - error → 错误 ==========

    it('type_label_error_returns_cuowu', 0, () => {
      expect(NotificationViewHelper.getTypeLabel('error' as NotificationType)).assertEqual('错误');
    });

    // ========== 切片13: getReadStatusColor - 未读 → error（红点） ==========

    it('read_status_color_unread_returns_error', 0, () => {
      expect(NotificationViewHelper.getReadStatusColor(false)).assertEqual('error');
    });

    // ========== 切片14: getReadStatusColor - 已读 → text_secondary ==========

    it('read_status_color_read_returns_text_secondary', 0, () => {
      expect(NotificationViewHelper.getReadStatusColor(true)).assertEqual('text_secondary');
    });

    // ========== 切片15: formatCreatedAt - 1分钟内 → "1分钟前" ==========

    it('format_created_at_within_one_minute', 0, () => {
      // 当前时间减 30 秒
      const ts = new Date(Date.now() - 30 * 1000).toISOString();
      const result = NotificationViewHelper.formatCreatedAt(ts);
      expect(result).assertEqual('1分钟前');
    });

    // ========== 切片16: formatCreatedAt - 几分钟前 ==========

    it('format_created_at_minutes_ago', 0, () => {
      // 当前时间减 5 分钟
      const ts = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      const result = NotificationViewHelper.formatCreatedAt(ts);
      expect(result).assertEqual('5分钟前');
    });

    // ========== 切片17: formatCreatedAt - 几小时前 ==========

    it('format_created_at_hours_ago', 0, () => {
      // 当前时间减 3 小时
      const ts = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
      const result = NotificationViewHelper.formatCreatedAt(ts);
      expect(result).assertEqual('3小时前');
    });

    // ========== 切片18: formatCreatedAt - 几天前 ==========

    it('format_created_at_days_ago', 0, () => {
      // 当前时间减 2 天
      const ts = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
      const result = NotificationViewHelper.formatCreatedAt(ts);
      expect(result).assertEqual('2天前');
    });

    // ========== 切片19: formatCreatedAt - 超过 7 天 → YYYY-MM-DD ==========

    it('format_created_at_over_week_returns_yyyy_mm_dd', 0, () => {
      // 当前时间减 30 天
      const ts = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
      const result = NotificationViewHelper.formatCreatedAt(ts);
      expect(result.length).assertEqual(10);
      expect(result.charAt(4)).assertEqual('-');
      expect(result.charAt(7)).assertEqual('-');
    });

    // ========== 切片20: formatCreatedAt - undefined → '-' ==========

    it('format_created_at_undefined_returns_dash', 0, () => {
      expect(NotificationViewHelper.formatCreatedAt(undefined)).assertEqual('-');
    });

    // ========== 切片21: formatCreatedAt - 空字符串 → '-' ==========

    it('format_created_at_empty_returns_dash', 0, () => {
      expect(NotificationViewHelper.formatCreatedAt('')).assertEqual('-');
    });

    // ========== 切片22: formatCreatedAt - 无效日期 → '-' ==========

    it('format_created_at_invalid_returns_dash', 0, () => {
      expect(NotificationViewHelper.formatCreatedAt('not-a-date')).assertEqual('-');
    });

    // ========== 切片23: truncateTitle - 未超长原样返回 ==========

    it('truncate_title_under_max_returns_original', 0, () => {
      const title = '系统通知';
      expect(NotificationViewHelper.truncateTitle(title, 100)).assertEqual(title);
    });

    // ========== 切片24: truncateTitle - 超长截断加省略号 ==========

    it('truncate_title_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(60);
      const result = NotificationViewHelper.truncateTitle(long, 30);
      expect(result.length).assertEqual(33);
      expect(result.substring(30)).assertEqual('...');
    });

    // ========== 切片25: truncateTitle - 默认 maxLen（100） ==========

    it('truncate_title_default_max_len', 0, () => {
      const long = 't'.repeat(120);
      const result = NotificationViewHelper.truncateTitle(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });
  });
}
