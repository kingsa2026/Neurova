// ProjectPage 项目页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ProjectViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 ProjectPage 导出的 ProjectViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       formatMemberCount / formatDate / truncateDescription 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ProjectViewHelper } from '../../../../main/ets/pages/ProjectPage';
import { ProjectStatus } from '../../../../main/ets/libs/types';

export default function projectPageTest() {
  describe('ProjectPage', () => {
    // ========== 切片1: getStatusColor - planning → warning ==========

    it('status_color_planning_returns_warning', 0, () => {
      expect(ProjectViewHelper.getStatusColor('planning' as ProjectStatus)).assertEqual('warning');
    });

    // ========== 切片2: getStatusColor - active → success ==========

    it('status_color_active_returns_success', 0, () => {
      expect(ProjectViewHelper.getStatusColor('active' as ProjectStatus)).assertEqual('success');
    });

    // ========== 切片3: getStatusColor - paused → text_secondary ==========

    it('status_color_paused_returns_text_secondary', 0, () => {
      expect(ProjectViewHelper.getStatusColor('paused' as ProjectStatus)).assertEqual('text_secondary');
    });

    // ========== 切片4: getStatusColor - completed → info ==========

    it('status_color_completed_returns_info', 0, () => {
      expect(ProjectViewHelper.getStatusColor('completed' as ProjectStatus)).assertEqual('info');
    });

    // ========== 切片5: getStatusColor - archived → text_disabled ==========

    it('status_color_archived_returns_text_disabled', 0, () => {
      expect(ProjectViewHelper.getStatusColor('archived' as ProjectStatus)).assertEqual('text_disabled');
    });

    // ========== 切片6: getStatusIcon - planning → 📝 ==========

    it('status_icon_planning_returns_pencil_emoji', 0, () => {
      expect(ProjectViewHelper.getStatusIcon('planning' as ProjectStatus)).assertEqual('📝');
    });

    // ========== 切片7: getStatusIcon - active → ▶️ ==========

    it('status_icon_active_returns_play_emoji', 0, () => {
      expect(ProjectViewHelper.getStatusIcon('active' as ProjectStatus)).assertEqual('▶️');
    });

    // ========== 切片8: getStatusIcon - completed → ✅ ==========

    it('status_icon_completed_returns_check_emoji', 0, () => {
      expect(ProjectViewHelper.getStatusIcon('completed' as ProjectStatus)).assertEqual('✅');
    });

    // ========== 切片9: getStatusIcon - archived → 📦 ==========

    it('status_icon_archived_returns_box_emoji', 0, () => {
      expect(ProjectViewHelper.getStatusIcon('archived' as ProjectStatus)).assertEqual('📦');
    });

    // ========== 切片10: getStatusLabel - planning → 规划中 ==========

    it('status_label_planning_returns_guihua', 0, () => {
      expect(ProjectViewHelper.getStatusLabel('planning' as ProjectStatus)).assertEqual('规划中');
    });

    // ========== 切片11: getStatusLabel - active → 进行中 ==========

    it('status_label_active_returns_jinxingzhong', 0, () => {
      expect(ProjectViewHelper.getStatusLabel('active' as ProjectStatus)).assertEqual('进行中');
    });

    // ========== 切片12: getStatusLabel - completed → 已完成 ==========

    it('status_label_completed_returns_yiwancheng', 0, () => {
      expect(ProjectViewHelper.getStatusLabel('completed' as ProjectStatus)).assertEqual('已完成');
    });

    // ========== 切片13: formatMemberCount - 0 → "无成员" ==========

    it('format_member_count_zero_returns_empty', 0, () => {
      expect(ProjectViewHelper.formatMemberCount(0)).assertEqual('无成员');
    });

    // ========== 切片14: formatMemberCount - 正数 → "成员 n 人" ==========

    it('format_member_count_positive_returns_count_text', 0, () => {
      expect(ProjectViewHelper.formatMemberCount(5)).assertEqual('成员 5 人');
    });

    // ========== 切片15: formatDate - undefined → "—" ==========

    it('format_date_undefined_returns_dash', 0, () => {
      expect(ProjectViewHelper.formatDate(undefined)).assertEqual('—');
    });

    // ========== 切片16: formatDate - 空字符串 → "—" ==========

    it('format_date_empty_returns_dash', 0, () => {
      expect(ProjectViewHelper.formatDate('')).assertEqual('—');
    });

    // ========== 切片17: formatDate - ISO → YYYY-MM-DD ==========

    it('format_date_iso_returns_yyyy_mm_dd', 0, () => {
      // 2024-06-15T08:30:00Z → "2024-06-15"
      const result = ProjectViewHelper.formatDate('2024-06-15T08:30:00Z');
      expect(result.length).assertEqual(10);
      expect(result.startsWith('2024-06-15')).assertTrue();
    });

    // ========== 切片18: formatDate - 无效日期 → "—" ==========

    it('format_date_invalid_returns_dash', 0, () => {
      expect(ProjectViewHelper.formatDate('not-a-date')).assertEqual('—');
    });

    // ========== 切片19: truncateDescription - 超长加省略号（默认 100） ==========

    it('truncate_description_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(150);
      const result = ProjectViewHelper.truncateDescription(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });

    // ========== 切片20: truncateDescription - 自定义 maxLen ==========

    it('truncate_description_custom_max_len', 0, () => {
      const long = 'abcdefghij'.repeat(10);
      const result = ProjectViewHelper.truncateDescription(long, 50);
      expect(result.length).assertEqual(53);
      expect(result.substring(50)).assertEqual('...');
    });

    // ========== 切片21: truncateDescription - 未超长原样返回 ==========

    it('truncate_description_under_max_returns_original', 0, () => {
      const short = '简短描述';
      expect(ProjectViewHelper.truncateDescription(short, 100)).assertEqual('简短描述');
    });
  });
}
