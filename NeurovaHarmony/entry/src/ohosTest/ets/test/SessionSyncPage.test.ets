// SessionSyncPage 会话同步页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：SessionSyncViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 SessionSyncPage 导出的 SessionSyncViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       formatMessageCount / formatRelativeTime 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
// 时间相关测试：在测试内部以 Date.now() 为基准计算时间戳，保证与实现侧 Date.now() 一致。
import { describe, it, expect } from '@ohos/hypium';
import { SessionSyncViewHelper } from '../../../../main/ets/pages/SessionSyncPage';

export default function sessionSyncPageTest() {
  describe('SessionSyncPage', () => {
    // ========== 切片1: getStatusColor - synced → status_success ==========

    it('status_color_synced_returns_status_success', 0, () => {
      expect(SessionSyncViewHelper.getStatusColor('synced')).assertEqual('status_success');
    });

    // ========== 切片2: getStatusColor - partial → status_warning ==========

    it('status_color_partial_returns_status_warning', 0, () => {
      expect(SessionSyncViewHelper.getStatusColor('partial')).assertEqual('status_warning');
    });

    // ========== 切片3: getStatusColor - failed → status_error ==========

    it('status_color_failed_returns_status_error', 0, () => {
      expect(SessionSyncViewHelper.getStatusColor('failed')).assertEqual('status_error');
    });

    // ========== 切片4: getStatusIcon - synced → ✅ ==========

    it('status_icon_synced_returns_check_emoji', 0, () => {
      expect(SessionSyncViewHelper.getStatusIcon('synced')).assertEqual('✅');
    });

    // ========== 切片5: getStatusIcon - partial → ⚠️ ==========

    it('status_icon_partial_returns_warning_emoji', 0, () => {
      expect(SessionSyncViewHelper.getStatusIcon('partial')).assertEqual('⚠️');
    });

    // ========== 切片6: getStatusIcon - failed → ❌ ==========

    it('status_icon_failed_returns_cross_emoji', 0, () => {
      expect(SessionSyncViewHelper.getStatusIcon('failed')).assertEqual('❌');
    });

    // ========== 切片7: getStatusLabel - synced → 已同步 ==========

    it('status_label_synced_returns_synced_text', 0, () => {
      expect(SessionSyncViewHelper.getStatusLabel('synced')).assertEqual('已同步');
    });

    // ========== 切片8: getStatusLabel - partial → 部分同步 ==========

    it('status_label_partial_returns_partial_text', 0, () => {
      expect(SessionSyncViewHelper.getStatusLabel('partial')).assertEqual('部分同步');
    });

    // ========== 切片9: getStatusLabel - failed → 同步失败 ==========

    it('status_label_failed_returns_failed_text', 0, () => {
      expect(SessionSyncViewHelper.getStatusLabel('failed')).assertEqual('同步失败');
    });

    // ========== 切片10: formatMessageCount - 0 → 无消息 ==========

    it('format_message_count_zero_returns_empty', 0, () => {
      expect(SessionSyncViewHelper.formatMessageCount(0)).assertEqual('无消息');
    });

    // ========== 切片11: formatMessageCount - 1 → 1条 ==========

    it('format_message_count_one_returns_one_msg', 0, () => {
      expect(SessionSyncViewHelper.formatMessageCount(1)).assertEqual('1条');
    });

    // ========== 切片12: formatMessageCount - 999 → 999条 ==========

    it('format_message_count_999_returns_999', 0, () => {
      expect(SessionSyncViewHelper.formatMessageCount(999)).assertEqual('999条');
    });

    // ========== 切片13: formatMessageCount - 1000 → 999+条 ==========

    it('format_message_count_1000_returns_999_plus', 0, () => {
      expect(SessionSyncViewHelper.formatMessageCount(1000)).assertEqual('999+条');
    });

    // ========== 切片14: formatMessageCount - 5000 → 999+条（封顶） ==========

    it('format_message_count_5000_capped_to_999_plus', 0, () => {
      expect(SessionSyncViewHelper.formatMessageCount(5000)).assertEqual('999+条');
    });

    // ========== 切片15: formatRelativeTime - 空字符串 → - ==========

    it('format_relative_time_empty_returns_dash', 0, () => {
      expect(SessionSyncViewHelper.formatRelativeTime('')).assertEqual('-');
    });

    // ========== 切片16: formatRelativeTime - 无效字符串 → - ==========

    it('format_relative_time_invalid_returns_dash', 0, () => {
      expect(SessionSyncViewHelper.formatRelativeTime('not-a-date')).assertEqual('-');
    });

    // ========== 切片17: formatRelativeTime - 刚刚（5秒前） → 刚刚 ==========

    it('format_relative_time_just_now_returns_now', 0, () => {
      const now = Date.now();
      const ts = new Date(now - 5 * 1000).toISOString(); // 5 秒前
      expect(SessionSyncViewHelper.formatRelativeTime(ts)).assertEqual('刚刚');
    });

    // ========== 切片18: formatRelativeTime - 5分钟前 → 5分钟前 ==========

    it('format_relative_time_minutes_returns_minutes_ago', 0, () => {
      const now = Date.now();
      const ts = new Date(now - 5 * 60 * 1000).toISOString(); // 5 分钟前
      expect(SessionSyncViewHelper.formatRelativeTime(ts)).assertEqual('5分钟前');
    });

    // ========== 切片19: formatRelativeTime - 3小时前 → 3小时前 ==========

    it('format_relative_time_hours_returns_hours_ago', 0, () => {
      const now = Date.now();
      const ts = new Date(now - 3 * 3600 * 1000).toISOString(); // 3 小时前
      expect(SessionSyncViewHelper.formatRelativeTime(ts)).assertEqual('3小时前');
    });

    // ========== 切片20: formatRelativeTime - 2天前 → 2天前 ==========

    it('format_relative_time_days_returns_days_ago', 0, () => {
      const now = Date.now();
      const ts = new Date(now - 2 * 86400 * 1000).toISOString(); // 2 天前
      expect(SessionSyncViewHelper.formatRelativeTime(ts)).assertEqual('2天前');
    });
  });
}
