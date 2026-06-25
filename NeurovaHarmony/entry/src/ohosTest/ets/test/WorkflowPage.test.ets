// WorkflowPage 工作流页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：WorkflowViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 WorkflowPage 导出的 WorkflowViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getStatusIcon / getStatusLabel /
//       formatNodeCount / formatVersion / truncateDescription 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { WorkflowViewHelper } from '../../../../main/ets/pages/WorkflowPage';
import { WorkflowStatus } from '../../../../main/ets/libs/types';

export default function workflowPageTest() {
  describe('WorkflowPage', () => {
    // ========== 切片1: getStatusColor - draft → warning ==========

    it('status_color_draft_returns_warning', 0, () => {
      expect(WorkflowViewHelper.getStatusColor('draft' as WorkflowStatus)).assertEqual('warning');
    });

    // ========== 切片2: getStatusColor - active → success ==========

    it('status_color_active_returns_success', 0, () => {
      expect(WorkflowViewHelper.getStatusColor('active' as WorkflowStatus)).assertEqual('success');
    });

    // ========== 切片3: getStatusColor - paused → text_secondary ==========

    it('status_color_paused_returns_text_secondary', 0, () => {
      expect(WorkflowViewHelper.getStatusColor('paused' as WorkflowStatus)).assertEqual('text_secondary');
    });

    // ========== 切片4: getStatusColor - archived → text_disabled ==========

    it('status_color_archived_returns_text_disabled', 0, () => {
      expect(WorkflowViewHelper.getStatusColor('archived' as WorkflowStatus)).assertEqual('text_disabled');
    });

    // ========== 切片5: getStatusIcon - draft → 📝 ==========

    it('status_icon_draft_returns_pencil_emoji', 0, () => {
      expect(WorkflowViewHelper.getStatusIcon('draft' as WorkflowStatus)).assertEqual('📝');
    });

    // ========== 切片6: getStatusIcon - active → ▶️ ==========

    it('status_icon_active_returns_play_emoji', 0, () => {
      expect(WorkflowViewHelper.getStatusIcon('active' as WorkflowStatus)).assertEqual('▶️');
    });

    // ========== 切片7: getStatusIcon - paused → ⏸️ ==========

    it('status_icon_paused_returns_pause_emoji', 0, () => {
      expect(WorkflowViewHelper.getStatusIcon('paused' as WorkflowStatus)).assertEqual('⏸️');
    });

    // ========== 切片8: getStatusIcon - archived → 📦 ==========

    it('status_icon_archived_returns_box_emoji', 0, () => {
      expect(WorkflowViewHelper.getStatusIcon('archived' as WorkflowStatus)).assertEqual('📦');
    });

    // ========== 切片9: getStatusLabel - draft → 草稿 ==========

    it('status_label_draft_returns_caogao', 0, () => {
      expect(WorkflowViewHelper.getStatusLabel('draft' as WorkflowStatus)).assertEqual('草稿');
    });

    // ========== 切片10: getStatusLabel - active → 运行中 ==========

    it('status_label_active_returns_running', 0, () => {
      expect(WorkflowViewHelper.getStatusLabel('active' as WorkflowStatus)).assertEqual('运行中');
    });

    // ========== 切片11: getStatusLabel - paused → 已暂停 ==========

    it('status_label_paused_returns_paused', 0, () => {
      expect(WorkflowViewHelper.getStatusLabel('paused' as WorkflowStatus)).assertEqual('已暂停');
    });

    // ========== 切片12: getStatusLabel - archived → 已归档 ==========

    it('status_label_archived_returns_archived', 0, () => {
      expect(WorkflowViewHelper.getStatusLabel('archived' as WorkflowStatus)).assertEqual('已归档');
    });

    // ========== 切片13: formatNodeCount - 0 → "无节点" ==========

    it('format_node_count_zero_returns_empty', 0, () => {
      expect(WorkflowViewHelper.formatNodeCount(0)).assertEqual('无节点');
    });

    // ========== 切片14: formatNodeCount - 正数 → "节点 n 个" ==========

    it('format_node_count_positive_returns_count_text', 0, () => {
      expect(WorkflowViewHelper.formatNodeCount(3)).assertEqual('节点 3 个');
    });

    // ========== 切片15: formatVersion - "1.2.0" → "v1.2.0" ==========

    it('format_version_returns_v_prefixed', 0, () => {
      expect(WorkflowViewHelper.formatVersion('1.2.0')).assertEqual('v1.2.0');
    });

    // ========== 切片16: truncateDescription - undefined → "—" ==========

    it('truncate_description_undefined_returns_dash', 0, () => {
      expect(WorkflowViewHelper.truncateDescription(undefined)).assertEqual('—');
    });

    // ========== 切片17: truncateDescription - 空字符串 → "—" ==========

    it('truncate_description_empty_returns_dash', 0, () => {
      expect(WorkflowViewHelper.truncateDescription('')).assertEqual('—');
    });

    // ========== 切片18: truncateDescription - 超长加省略号 ==========

    it('truncate_description_over_max_returns_ellipsis', 0, () => {
      const long = 'abcdefghijklmnopqrstuvwxyz'.repeat(10);
      const result = WorkflowViewHelper.truncateDescription(long, 80);
      expect(result.length).assertEqual(83);
      expect(result.substring(80)).assertEqual('...');
    });

    // ========== 切片19: truncateDescription - 未超长原样返回 ==========

    it('truncate_description_under_max_returns_original', 0, () => {
      const short = '简短描述';
      expect(WorkflowViewHelper.truncateDescription(short, 80)).assertEqual('简短描述');
    });

    // ========== 切片20: truncateDescription - 默认 maxLen 80 ==========

    it('truncate_description_default_max_len_80', 0, () => {
      const long = 'a'.repeat(100);
      const result = WorkflowViewHelper.truncateDescription(long);
      expect(result.length).assertEqual(83);
      expect(result.substring(80)).assertEqual('...');
    });
  });
}
