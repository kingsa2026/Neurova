// EnhancedUserPage 增强用户管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：EnhancedUserViewHelper 视图模型行为（状态颜色、状态图标、状态标签、
//           角色颜色、角色标签、最后活动时间格式化、双因素认证颜色）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 EnhancedUserPage.ets 导出的 EnhancedUserViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { EnhancedUserViewHelper } from '../../../../main/ets/pages/EnhancedUserPage';

export default function enhancedUserPageTest() {
  describe('EnhancedUserPage', () => {
    // ========== 切片1: getStatusColor - online → success ==========

    it('status_color_online_returns_success', 0, () => {
      expect(EnhancedUserViewHelper.getStatusColor('online')).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - idle → warning ==========

    it('status_color_idle_returns_warning', 0, () => {
      expect(EnhancedUserViewHelper.getStatusColor('idle')).assertEqual('warning');
    });

    // ========== 切片3: getStatusColor - dnd → error ==========

    it('status_color_dnd_returns_error', 0, () => {
      expect(EnhancedUserViewHelper.getStatusColor('dnd')).assertEqual('error');
    });

    // ========== 切片4: getStatusColor - offline → text_secondary ==========

    it('status_color_offline_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getStatusColor('offline')).assertEqual('text_secondary');
    });

    // ========== 切片5: getStatusIcon - online → 🟢 ==========

    it('status_icon_online_returns_green_circle', 0, () => {
      expect(EnhancedUserViewHelper.getStatusIcon('online')).assertEqual('🟢');
    });

    // ========== 切片6: getStatusIcon - idle → 🟡 ==========

    it('status_icon_idle_returns_yellow_circle', 0, () => {
      expect(EnhancedUserViewHelper.getStatusIcon('idle')).assertEqual('🟡');
    });

    // ========== 切片7: getStatusIcon - dnd → 🔴 ==========

    it('status_icon_dnd_returns_red_circle', 0, () => {
      expect(EnhancedUserViewHelper.getStatusIcon('dnd')).assertEqual('🔴');
    });

    // ========== 切片8: getStatusIcon - offline → ⚪ ==========

    it('status_icon_offline_returns_white_circle', 0, () => {
      expect(EnhancedUserViewHelper.getStatusIcon('offline')).assertEqual('⚪');
    });

    // ========== 切片9: getStatusLabel - online → 在线 ==========

    it('status_label_online_returns_在线', 0, () => {
      expect(EnhancedUserViewHelper.getStatusLabel('online')).assertEqual('在线');
    });

    // ========== 切片10: getStatusLabel - idle → 空闲 ==========

    it('status_label_idle_returns_空闲', 0, () => {
      expect(EnhancedUserViewHelper.getStatusLabel('idle')).assertEqual('空闲');
    });

    // ========== 切片11: getStatusLabel - dnd → 勿扰 ==========

    it('status_label_dnd_returns_勿扰', 0, () => {
      expect(EnhancedUserViewHelper.getStatusLabel('dnd')).assertEqual('勿扰');
    });

    // ========== 切片12: getStatusLabel - offline → 离线 ==========

    it('status_label_offline_returns_离线', 0, () => {
      expect(EnhancedUserViewHelper.getStatusLabel('offline')).assertEqual('离线');
    });

    // ========== 切片13: getRoleColor - admin → error ==========

    it('role_color_admin_returns_error', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('admin')).assertEqual('error');
    });

    // ========== 切片14: getRoleColor - developer → primary ==========

    it('role_color_developer_returns_primary', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('developer')).assertEqual('primary');
    });

    // ========== 切片15: getRoleColor - operator → info ==========

    it('role_color_operator_returns_info', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('operator')).assertEqual('info');
    });

    // ========== 切片16: getRoleColor - viewer → text_secondary ==========

    it('role_color_viewer_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('viewer')).assertEqual('text_secondary');
    });

    // ========== 切片17: getRoleColor - guest → warning ==========

    it('role_color_guest_returns_warning', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('guest')).assertEqual('warning');
    });

    // ========== 切片18: getRoleLabel - admin → 管理员 ==========

    it('role_label_admin_returns_管理员', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('admin')).assertEqual('管理员');
    });

    // ========== 切片19: getRoleLabel - developer → 开发者 ==========

    it('role_label_developer_returns_开发者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('developer')).assertEqual('开发者');
    });

    // ========== 切片20: getRoleLabel - operator → 运营者 ==========

    it('role_label_operator_returns_运营者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('operator')).assertEqual('运营者');
    });

    // ========== 切片21: getRoleLabel - viewer → 查看者 ==========

    it('role_label_viewer_returns_查看者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('viewer')).assertEqual('查看者');
    });

    // ========== 切片22: getRoleLabel - guest → 访客 ==========

    it('role_label_guest_returns_访客', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('guest')).assertEqual('访客');
    });

    // ========== 切片23: formatLastActive - undefined → 从未活动 ==========

    it('last_active_undefined_returns_从未活动', 0, () => {
      expect(EnhancedUserViewHelper.formatLastActive(undefined)).assertEqual('从未活动');
    });

    // ========== 切片24: formatLastActive - 无效时间 → 从未活动 ==========

    it('last_active_invalid_returns_从未活动', 0, () => {
      expect(EnhancedUserViewHelper.formatLastActive('invalid-date')).assertEqual('从未活动');
    });

    // ========== 切片25: formatLastActive - 5 分钟前 → "5 分钟前" ==========

    it('last_active_minutes_ago_returns_X分钟前', 0, () => {
      const ts = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('5 分钟前');
    });

    // ========== 切片26: formatLastActive - 3 小时前 → "3 小时前" ==========

    it('last_active_hours_ago_returns_X小时前', 0, () => {
      const ts = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('3 小时前');
    });

    // ========== 切片27: formatLastActive - 5 天前 → "5 天前" ==========

    it('last_active_days_ago_returns_X天前', 0, () => {
      const ts = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('5 天前');
    });

    // ========== 切片28: getTwoFactorColor - true → success ==========

    it('two_factor_true_returns_success', 0, () => {
      expect(EnhancedUserViewHelper.getTwoFactorColor(true)).assertEqual('success');
    });

    // ========== 切片29: getTwoFactorColor - false → text_secondary ==========

    it('two_factor_false_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getTwoFactorColor(false)).assertEqual('text_secondary');
    });
  });
}
