// CollaborationPage 协作概览页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：CollaborationViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 CollaborationPage 导出的 CollaborationViewHelper 静态方法进行验证，
//       覆盖页面 getModuleIcon / getModuleLabel / formatCount /
//       formatPendingTasks / getModuleColor 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { CollaborationViewHelper } from '../../../../main/ets/pages/CollaborationPage';
import { Task } from '../../../../main/ets/libs/types';

export default function collaborationPageTest() {
  describe('CollaborationPage', () => {
    // ========== 切片1: getModuleIcon - projects → 📁 ==========

    it('module_icon_projects_returns_folder_emoji', 0, () => {
      expect(CollaborationViewHelper.getModuleIcon('projects')).assertEqual('📁');
    });

    // ========== 切片2: getModuleIcon - teams → 👥 ==========

    it('module_icon_teams_returns_users_emoji', 0, () => {
      expect(CollaborationViewHelper.getModuleIcon('teams')).assertEqual('👥');
    });

    // ========== 切片3: getModuleIcon - tasks → ✅ ==========

    it('module_icon_tasks_returns_check_emoji', 0, () => {
      expect(CollaborationViewHelper.getModuleIcon('tasks')).assertEqual('✅');
    });

    // ========== 切片4: getModuleLabel - projects → 项目 ==========

    it('module_label_projects_returns_xiangmu', 0, () => {
      expect(CollaborationViewHelper.getModuleLabel('projects')).assertEqual('项目');
    });

    // ========== 切片5: getModuleLabel - teams → 团队 ==========

    it('module_label_teams_returns_tuandui', 0, () => {
      expect(CollaborationViewHelper.getModuleLabel('teams')).assertEqual('团队');
    });

    // ========== 切片6: getModuleLabel - tasks → 任务 ==========

    it('module_label_tasks_returns_renwu', 0, () => {
      expect(CollaborationViewHelper.getModuleLabel('tasks')).assertEqual('任务');
    });

    // ========== 切片7: formatCount - 0 → "无" ==========

    it('format_count_zero_returns_empty', 0, () => {
      expect(CollaborationViewHelper.formatCount(0)).assertEqual('无');
    });

    // ========== 切片8: formatCount - 正数 → 字符串 ==========

    it('format_count_positive_returns_string', 0, () => {
      expect(CollaborationViewHelper.formatCount(5)).assertEqual('5');
      expect(CollaborationViewHelper.formatCount(42)).assertEqual('42');
    });

    // ========== 切片9: formatPendingTasks - 统计 todo + in_progress ==========

    it('format_pending_tasks_counts_todo_and_in_progress', 0, () => {
      const tasks: Task[] = [
        {
          id: 't1', projectId: 'p1', title: 'A', description: '',
          status: 'todo', priority: 'low', tags: [], createdAt: '', updatedAt: '',
        },
        {
          id: 't2', projectId: 'p1', title: 'B', description: '',
          status: 'in_progress', priority: 'medium', tags: [], createdAt: '', updatedAt: '',
        },
        {
          id: 't3', projectId: 'p1', title: 'C', description: '',
          status: 'done', priority: 'high', tags: [], createdAt: '', updatedAt: '',
        },
        {
          id: 't4', projectId: 'p1', title: 'D', description: '',
          status: 'review', priority: 'urgent', tags: [], createdAt: '', updatedAt: '',
        },
        {
          id: 't5', projectId: 'p1', title: 'E', description: '',
          status: 'blocked', tags: [], priority: 'low', createdAt: '', updatedAt: '',
        },
      ];
      // todo + in_progress = 2 个
      expect(CollaborationViewHelper.formatPendingTasks(tasks)).assertEqual('2');
    });

    // ========== 切片10: formatPendingTasks - 空数组 → "0" ==========

    it('format_pending_tasks_empty_returns_zero', 0, () => {
      expect(CollaborationViewHelper.formatPendingTasks([])).assertEqual('0');
    });

    // ========== 切片11: getModuleColor - projects → primary ==========

    it('module_color_projects_returns_primary', 0, () => {
      expect(CollaborationViewHelper.getModuleColor('projects')).assertEqual('primary');
    });

    // ========== 切片12: getModuleColor - teams → info ==========

    it('module_color_teams_returns_info', 0, () => {
      expect(CollaborationViewHelper.getModuleColor('teams')).assertEqual('info');
    });

    // ========== 切片13: getModuleColor - tasks → warning ==========

    it('module_color_tasks_returns_warning', 0, () => {
      expect(CollaborationViewHelper.getModuleColor('tasks')).assertEqual('warning');
    });
  });
}
