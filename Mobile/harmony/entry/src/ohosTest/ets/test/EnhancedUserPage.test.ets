// EnhancedUserPage 增强用户管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：EnhancedUserViewHelper 视图模型行为（启用状态颜色/图标/标签、
//           角色颜色、角色标签、最近登录时间格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 EnhancedUserPage.ets 导出的 EnhancedUserViewHelper 静态方法进行验证。
//       P1-33 接线真实 API（/v1/enhanced-users，UserOut 投影）后，视图模型与后端
//       字段对齐：active 布尔启用态替代虚构的 online/idle/dnd/offline 状态机，
//       2FA/登录次数等后端没有的字段随 mock 一并退役；未知角色原样展示。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { EnhancedUserViewHelper } from '../../../main/ets/pages/EnhancedUserPage';

export default function enhancedUserPageTest() {
  describe('EnhancedUserPage', () => {
    // ========== 切片1: getActiveColor - true → success ==========

    it('active_color_true_returns_success', 0, () => {
      expect(EnhancedUserViewHelper.getActiveColor(true)).assertEqual('success');
    });

    // ========== 切片2: getActiveColor - false → text_secondary ==========

    it('active_color_false_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getActiveColor(false)).assertEqual('text_secondary');
    });

    // ========== 切片3: getActiveIcon - true → 🟢 ==========

    it('active_icon_true_returns_green_circle', 0, () => {
      expect(EnhancedUserViewHelper.getActiveIcon(true)).assertEqual('🟢');
    });

    // ========== 切片4: getActiveIcon - false → ⚪ ==========

    it('active_icon_false_returns_white_circle', 0, () => {
      expect(EnhancedUserViewHelper.getActiveIcon(false)).assertEqual('⚪');
    });

    // ========== 切片5: getActiveLabel - true → 启用 ==========

    it('active_label_true_returns_启用', 0, () => {
      expect(EnhancedUserViewHelper.getActiveLabel(true)).assertEqual('启用');
    });

    // ========== 切片6: getActiveLabel - false → 禁用 ==========

    it('active_label_false_returns_禁用', 0, () => {
      expect(EnhancedUserViewHelper.getActiveLabel(false)).assertEqual('禁用');
    });

    // ========== 切片7: getRoleColor - admin → error ==========

    it('role_color_admin_returns_error', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('admin')).assertEqual('error');
    });

    // ========== 切片8: getRoleColor - developer → primary ==========

    it('role_color_developer_returns_primary', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('developer')).assertEqual('primary');
    });

    // ========== 切片9: getRoleColor - operator → info ==========

    it('role_color_operator_returns_info', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('operator')).assertEqual('info');
    });

    // ========== 切片10: getRoleColor - viewer → text_secondary ==========

    it('role_color_viewer_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('viewer')).assertEqual('text_secondary');
    });

    // ========== 切片11: getRoleColor - guest → warning ==========

    it('role_color_guest_returns_warning', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('guest')).assertEqual('warning');
    });

    // ========== 切片12: getRoleColor - 未知角色 → text_secondary ==========

    it('role_color_unknown_returns_text_secondary', 0, () => {
      expect(EnhancedUserViewHelper.getRoleColor('maintainer')).assertEqual('text_secondary');
    });

    // ========== 切片13: getRoleLabel - admin → 管理员 ==========

    it('role_label_admin_returns_管理员', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('admin')).assertEqual('管理员');
    });

    // ========== 切片14: getRoleLabel - developer → 开发者 ==========

    it('role_label_developer_returns_开发者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('developer')).assertEqual('开发者');
    });

    // ========== 切片15: getRoleLabel - operator → 运营者 ==========

    it('role_label_operator_returns_运营者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('operator')).assertEqual('运营者');
    });

    // ========== 切片16: getRoleLabel - viewer → 查看者 ==========

    it('role_label_viewer_returns_查看者', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('viewer')).assertEqual('查看者');
    });

    // ========== 切片17: getRoleLabel - guest → 访客 ==========

    it('role_label_guest_returns_访客', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('guest')).assertEqual('访客');
    });

    // ========== 切片18: getRoleLabel - 未知角色 → 原样展示 ==========

    it('role_label_unknown_returns_raw_role', 0, () => {
      expect(EnhancedUserViewHelper.getRoleLabel('maintainer')).assertEqual('maintainer');
    });

    // ========== 切片19: formatLastActive - undefined → 从未登录 ==========

    it('last_active_undefined_returns_从未登录', 0, () => {
      expect(EnhancedUserViewHelper.formatLastActive(undefined)).assertEqual('从未登录');
    });

    // ========== 切片20: formatLastActive - 无效时间 → 从未登录 ==========

    it('last_active_invalid_returns_从未登录', 0, () => {
      expect(EnhancedUserViewHelper.formatLastActive('invalid-date')).assertEqual('从未登录');
    });

    // ========== 切片21: formatLastActive - 5 分钟前 → "5 分钟前" ==========

    it('last_active_minutes_ago_returns_X分钟前', 0, () => {
      const ts = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('5 分钟前');
    });

    // ========== 切片22: formatLastActive - 3 小时前 → "3 小时前" ==========

    it('last_active_hours_ago_returns_X小时前', 0, () => {
      const ts = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('3 小时前');
    });

    // ========== 切片23: formatLastActive - 5 天前 → "5 天前" ==========

    it('last_active_days_ago_returns_X天前', 0, () => {
      const ts = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString();
      expect(EnhancedUserViewHelper.formatLastActive(ts)).assertEqual('5 天前');
    });
  });
}
