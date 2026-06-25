// TeamPage 团队页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：TeamViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 TeamPage 导出的 TeamViewHelper 静态方法进行验证，
//       覆盖页面 getRoleColor / getRoleIcon / getRoleLabel /
//       formatMemberCount / formatRoleDistribution / truncateDescription 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { TeamViewHelper } from '../../../../main/ets/pages/TeamPage';
import { TeamRole } from '../../../../main/ets/libs/types';

export default function teamPageTest() {
  describe('TeamPage', () => {
    // ========== 切片1: getRoleColor - owner → primary ==========

    it('role_color_owner_returns_primary', 0, () => {
      expect(TeamViewHelper.getRoleColor('owner' as TeamRole)).assertEqual('primary');
    });

    // ========== 切片2: getRoleColor - admin → info ==========

    it('role_color_admin_returns_info', 0, () => {
      expect(TeamViewHelper.getRoleColor('admin' as TeamRole)).assertEqual('info');
    });

    // ========== 切片3: getRoleColor - member → success ==========

    it('role_color_member_returns_success', 0, () => {
      expect(TeamViewHelper.getRoleColor('member' as TeamRole)).assertEqual('success');
    });

    // ========== 切片4: getRoleColor - viewer → text_secondary ==========

    it('role_color_viewer_returns_text_secondary', 0, () => {
      expect(TeamViewHelper.getRoleColor('viewer' as TeamRole)).assertEqual('text_secondary');
    });

    // ========== 切片5: getRoleIcon - owner → 👑 ==========

    it('role_icon_owner_returns_crown_emoji', 0, () => {
      expect(TeamViewHelper.getRoleIcon('owner' as TeamRole)).assertEqual('👑');
    });

    // ========== 切片6: getRoleIcon - admin → 🛡️ ==========

    it('role_icon_admin_returns_shield_emoji', 0, () => {
      expect(TeamViewHelper.getRoleIcon('admin' as TeamRole)).assertEqual('🛡️');
    });

    // ========== 切片7: getRoleIcon - member → 👤 ==========

    it('role_icon_member_returns_user_emoji', 0, () => {
      expect(TeamViewHelper.getRoleIcon('member' as TeamRole)).assertEqual('👤');
    });

    // ========== 切片8: getRoleIcon - viewer → 👀 ==========

    it('role_icon_viewer_returns_eye_emoji', 0, () => {
      expect(TeamViewHelper.getRoleIcon('viewer' as TeamRole)).assertEqual('👀');
    });

    // ========== 切片9: getRoleLabel - owner → 所有者 ==========

    it('role_label_owner_returns_suoyouzhe', 0, () => {
      expect(TeamViewHelper.getRoleLabel('owner' as TeamRole)).assertEqual('所有者');
    });

    // ========== 切片10: getRoleLabel - admin → 管理员 ==========

    it('role_label_admin_returns_guanliyuan', 0, () => {
      expect(TeamViewHelper.getRoleLabel('admin' as TeamRole)).assertEqual('管理员');
    });

    // ========== 切片11: getRoleLabel - member → 成员 ==========

    it('role_label_member_returns_chengyuan', 0, () => {
      expect(TeamViewHelper.getRoleLabel('member' as TeamRole)).assertEqual('成员');
    });

    // ========== 切片12: getRoleLabel - viewer → 观察者 ==========

    it('role_label_viewer_returns_guanchazhe', 0, () => {
      expect(TeamViewHelper.getRoleLabel('viewer' as TeamRole)).assertEqual('观察者');
    });

    // ========== 切片13: formatMemberCount - 0 → "无成员" ==========

    it('format_member_count_zero_returns_empty', 0, () => {
      expect(TeamViewHelper.formatMemberCount(0)).assertEqual('无成员');
    });

    // ========== 切片14: formatMemberCount - 正数 → "成员 n 人" ==========

    it('format_member_count_positive_returns_count_text', 0, () => {
      expect(TeamViewHelper.formatMemberCount(7)).assertEqual('成员 7 人');
    });

    // ========== 切片15: formatRoleDistribution - 全角色分布 ==========

    it('format_role_distribution_all_roles', 0, () => {
      const members = [
        { userId: 'u1', role: 'owner' as TeamRole },
        { userId: 'u2', role: 'admin' as TeamRole },
        { userId: 'u3', role: 'admin' as TeamRole },
        { userId: 'u4', role: 'member' as TeamRole },
        { userId: 'u5', role: 'member' as TeamRole },
        { userId: 'u6', role: 'member' as TeamRole },
        { userId: 'u7', role: 'member' as TeamRole },
        { userId: 'u8', role: 'member' as TeamRole },
        { userId: 'u9', role: 'viewer' as TeamRole },
      ];
      // 1 owner · 2 admin · 5 member · 1 viewer
      const result = TeamViewHelper.formatRoleDistribution(members);
      expect(result).assertEqual('owner:1 · admin:2 · member:5 · viewer:1');
    });

    // ========== 切片16: formatRoleDistribution - 部分角色缺失（不显示） ==========

    it('format_role_distribution_partial_roles', 0, () => {
      const members = [
        { userId: 'u1', role: 'owner' as TeamRole },
        { userId: 'u2', role: 'member' as TeamRole },
        { userId: 'u3', role: 'member' as TeamRole },
      ];
      // 无 admin 和 viewer 角色 → 不显示
      const result = TeamViewHelper.formatRoleDistribution(members);
      expect(result).assertEqual('owner:1 · member:2');
    });

    // ========== 切片17: formatRoleDistribution - 空数组 → 空字符串 ==========

    it('format_role_distribution_empty_returns_empty_string', 0, () => {
      expect(TeamViewHelper.formatRoleDistribution([])).assertEqual('');
    });

    // ========== 切片18: truncateDescription - undefined → "—" ==========

    it('truncate_description_undefined_returns_dash', 0, () => {
      expect(TeamViewHelper.truncateDescription(undefined)).assertEqual('—');
    });

    // ========== 切片19: truncateDescription - 空字符串 → "—" ==========

    it('truncate_description_empty_returns_dash', 0, () => {
      expect(TeamViewHelper.truncateDescription('')).assertEqual('—');
    });

    // ========== 切片20: truncateDescription - 超长加省略号（默认 80） ==========

    it('truncate_description_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(100);
      const result = TeamViewHelper.truncateDescription(long);
      expect(result.length).assertEqual(83);
      expect(result.substring(80)).assertEqual('...');
    });

    // ========== 切片21: truncateDescription - 未超长原样返回 ==========

    it('truncate_description_under_max_returns_original', 0, () => {
      const short = '团队描述';
      expect(TeamViewHelper.truncateDescription(short, 80)).assertEqual('团队描述');
    });
  });
}
