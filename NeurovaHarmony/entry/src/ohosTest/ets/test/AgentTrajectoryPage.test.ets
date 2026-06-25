// AgentTrajectoryPage 轨迹点页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：TrajectoryViewHelper 视图模型行为契约（动作图标映射、动作标签映射、步骤格式化、
//           奖励值格式化、观察摘要截断、时间戳格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentTrajectoryPage.ets 导出的 TrajectoryViewHelper 静态方法进行验证，
//       覆盖页面 getActionIcon / getActionLabel / formatStep / formatReward /
//       truncateObservation / formatTimestamp 共 6 个核心视图逻辑方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，返回 emoji 或字符串，便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { TrajectoryViewHelper } from '../../../../main/ets/pages/AgentTrajectoryPage';

export default function agentTrajectoryPageTest() {
  describe('AgentTrajectoryPage', () => {
    // ========== 切片1: getActionIcon - click → 👆 ==========

    it('action_icon_click_returns_point', 0, () => {
      expect(TrajectoryViewHelper.getActionIcon('click')).assertEqual('👆');
    });

    // ========== 切片2: getActionIcon - type → ⌨️ ==========

    it('action_icon_type_returns_keyboard', 0, () => {
      expect(TrajectoryViewHelper.getActionIcon('type')).assertEqual('⌨️');
    });

    // ========== 切片3: getActionIcon - think → 💭 ==========

    it('action_icon_think_returns_think_bubble', 0, () => {
      expect(TrajectoryViewHelper.getActionIcon('think')).assertEqual('💭');
    });

    // ========== 切片4: getActionIcon - unknown action → ❓ ==========

    it('action_icon_unknown_returns_question', 0, () => {
      expect(TrajectoryViewHelper.getActionIcon('fly')).assertEqual('❓');
    });

    // ========== 切片5: getActionLabel - click → 点击 ==========

    it('action_label_click_returns_chinese', 0, () => {
      expect(TrajectoryViewHelper.getActionLabel('click')).assertEqual('点击');
    });

    // ========== 切片6: getActionLabel - speak → 说话 ==========

    it('action_label_speak_returns_chinese', 0, () => {
      expect(TrajectoryViewHelper.getActionLabel('speak')).assertEqual('说话');
    });

    // ========== 切片7: getActionLabel - unknown → 未知 ==========

    it('action_label_unknown_returns_unknown', 0, () => {
      expect(TrajectoryViewHelper.getActionLabel('dance')).assertEqual('未知');
    });

    // ========== 切片8: formatStep - 5 → "步骤 5" ==========

    it('format_step_returns_step_n', 0, () => {
      expect(TrajectoryViewHelper.formatStep(5)).assertEqual('步骤 5');
    });

    // ========== 切片9: formatReward - undefined → "—" ==========

    it('format_reward_undefined_returns_dash', 0, () => {
      expect(TrajectoryViewHelper.formatReward(undefined)).assertEqual('—');
    });

    // ========== 切片10: formatReward - 正数 → "+n.nn" ==========

    it('format_reward_positive_returns_plus', 0, () => {
      expect(TrajectoryViewHelper.formatReward(1.5)).assertEqual('+1.50');
    });

    // ========== 切片11: formatReward - 负数 → "n.nn"（保留负号） ==========

    it('format_reward_negative_returns_negative', 0, () => {
      expect(TrajectoryViewHelper.formatReward(-0.75)).assertEqual('-0.75');
    });

    // ========== 切片12: formatReward - 0 → "0.00" ==========

    it('format_reward_zero_returns_zero', 0, () => {
      expect(TrajectoryViewHelper.formatReward(0)).assertEqual('0.00');
    });

    // ========== 切片13: truncateObservation - 超长截断加省略号 ==========

    it('truncate_observation_over_limit_appends_ellipsis', 0, () => {
      const long = 'a'.repeat(200);
      const result = TrajectoryViewHelper.truncateObservation(long, 100);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });

    // ========== 切片14: truncateObservation - 未超长原样返回 ==========

    it('truncate_observation_within_limit_returns_original', 0, () => {
      const short = 'a'.repeat(50);
      const result = TrajectoryViewHelper.truncateObservation(short, 100);
      expect(result).assertEqual(short);
    });

    // ========== 切片15: truncateObservation - 默认 maxLen=150 ==========

    it('truncate_obsation_default_maxlen_150', 0, () => {
      const long = 'a'.repeat(200);
      const result = TrajectoryViewHelper.truncateObservation(long);
      expect(result.length).assertEqual(153);
    });

    // ========== 切片16: formatTimestamp - 有效 ISO 字符串 → YYYY-MM-DD HH:mm:ss ==========

    it('format_timestamp_valid_iso_returns_full', 0, () => {
      // 使用固定时间戳避免时区差异：2024-01-15T10:30:45
      const result = TrajectoryViewHelper.formatTimestamp('2024-01-15T10:30:45');
      // 校验格式：4 位年-2 月-2 日 空格 2 时:2 分:2 秒
      expect(result.length).assertEqual(19);
      expect(result.substring(4, 5)).assertEqual('-');
      expect(result.substring(7, 8)).assertEqual('-');
      expect(result.substring(10, 11)).assertEqual(' ');
      expect(result.substring(13, 14)).assertEqual(':');
      expect(result.substring(16, 17)).assertEqual(':');
    });

    // ========== 切片17: formatTimestamp - 空字符串回退 "未知" ==========

    it('format_timestamp_empty_returns_unknown', 0, () => {
      expect(TrajectoryViewHelper.formatTimestamp('')).assertEqual('未知');
    });
  });
}
