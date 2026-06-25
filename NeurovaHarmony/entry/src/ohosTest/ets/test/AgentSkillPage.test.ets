// AgentSkillPage 智能体技能页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentSkillViewHelper 视图模型行为（状态颜色、状态图标、状态标签、
//           等级格式化、经验值格式化、经验值颜色、冷却倒计时格式化）。
// 说明：区别于 SkillPoolPage（技能池），AgentSkillPage 是绑定到具体 Agent 的技能实例管理；
//       @Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentSkillPage.ets 导出的 AgentSkillViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentSkillViewHelper } from '../../../../main/ets/pages/AgentSkillPage';

export default function agentSkillPageTest() {
  describe('AgentSkillPage', () => {
    // ========== 切片1: getStatusColor - equipped → info ==========

    it('status_color_equipped_returns_info', 0, () => {
      expect(AgentSkillViewHelper.getStatusColor('equipped')).assertEqual('info');
    });

    // ========== 切片2: getStatusColor - active → success ==========

    it('status_color_active_returns_success', 0, () => {
      expect(AgentSkillViewHelper.getStatusColor('active')).assertEqual('success');
    });

    // ========== 切片3: getStatusColor - cooldown → warning ==========

    it('status_color_cooldown_returns_warning', 0, () => {
      expect(AgentSkillViewHelper.getStatusColor('cooldown')).assertEqual('warning');
    });

    // ========== 切片4: getStatusColor - disabled → text_secondary ==========

    it('status_color_disabled_returns_text_secondary', 0, () => {
      expect(AgentSkillViewHelper.getStatusColor('disabled')).assertEqual('text_secondary');
    });

    // ========== 切片5: getStatusIcon - equipped → 📌 ==========

    it('status_icon_equipped_returns_pin', 0, () => {
      expect(AgentSkillViewHelper.getStatusIcon('equipped')).assertEqual('📌');
    });

    // ========== 切片6: getStatusIcon - active → ⚡ ==========

    it('status_icon_active_returns_lightning', 0, () => {
      expect(AgentSkillViewHelper.getStatusIcon('active')).assertEqual('⚡');
    });

    // ========== 切片7: getStatusIcon - cooldown → ⏳ ==========

    it('status_icon_cooldown_returns_hourglass', 0, () => {
      expect(AgentSkillViewHelper.getStatusIcon('cooldown')).assertEqual('⏳');
    });

    // ========== 切片8: getStatusIcon - disabled → 🚫 ==========

    it('status_icon_disabled_returns_prohibited', 0, () => {
      expect(AgentSkillViewHelper.getStatusIcon('disabled')).assertEqual('🚫');
    });

    // ========== 切片9: getStatusLabel - equipped → 已装备 ==========

    it('status_label_equipped_returns_已装备', 0, () => {
      expect(AgentSkillViewHelper.getStatusLabel('equipped')).assertEqual('已装备');
    });

    // ========== 切片10: getStatusLabel - active → 激活中 ==========

    it('status_label_active_returns_激活中', 0, () => {
      expect(AgentSkillViewHelper.getStatusLabel('active')).assertEqual('激活中');
    });

    // ========== 切片11: getStatusLabel - cooldown → 冷却中 ==========

    it('status_label_cooldown_returns_冷却中', 0, () => {
      expect(AgentSkillViewHelper.getStatusLabel('cooldown')).assertEqual('冷却中');
    });

    // ========== 切片12: getStatusLabel - disabled → 已禁用 ==========

    it('status_label_disabled_returns_已禁用', 0, () => {
      expect(AgentSkillViewHelper.getStatusLabel('disabled')).assertEqual('已禁用');
    });

    // ========== 切片13: formatLevel - 5 → Lv.5 ==========

    it('format_level_5_returns_Lv5', 0, () => {
      expect(AgentSkillViewHelper.formatLevel(5)).assertEqual('Lv.5');
    });

    // ========== 切片14: formatLevel - 1 → Lv.1 ==========

    it('format_level_1_returns_Lv1', 0, () => {
      expect(AgentSkillViewHelper.formatLevel(1)).assertEqual('Lv.1');
    });

    // ========== 切片15: formatLevel - 10 → Lv.10（边界，未超出） ==========

    it('format_level_10_returns_Lv10', 0, () => {
      expect(AgentSkillViewHelper.formatLevel(10)).assertEqual('Lv.10');
    });

    // ========== 切片16: formatLevel - 15 → Lv.MAX（超出 10） ==========

    it('format_level_15_returns_LvMAX', 0, () => {
      expect(AgentSkillViewHelper.formatLevel(15)).assertEqual('Lv.MAX');
    });

    // ========== 切片17: formatExperience - 50 → "50/100" ==========

    it('format_experience_50_returns_50_100', 0, () => {
      expect(AgentSkillViewHelper.formatExperience(50)).assertEqual('50/100');
    });

    // ========== 切片18: formatExperience - 0 → "0/100" ==========

    it('format_experience_0_returns_0_100', 0, () => {
      expect(AgentSkillViewHelper.formatExperience(0)).assertEqual('0/100');
    });

    // ========== 切片19: formatExperience - 100 → "100/100" ==========

    it('format_experience_100_returns_100_100', 0, () => {
      expect(AgentSkillViewHelper.formatExperience(100)).assertEqual('100/100');
    });

    // ========== 切片20: getExperienceColor - < 30 → text_secondary ==========

    it('exp_color_below_30_returns_text_secondary', 0, () => {
      expect(AgentSkillViewHelper.getExperienceColor(20)).assertEqual('text_secondary');
    });

    // ========== 切片21: getExperienceColor - 30 → info（下界） ==========

    it('exp_color_30_returns_info', 0, () => {
      expect(AgentSkillViewHelper.getExperienceColor(30)).assertEqual('info');
    });

    // ========== 切片22: getExperienceColor - 50 → info（中段） ==========

    it('exp_color_50_returns_info', 0, () => {
      expect(AgentSkillViewHelper.getExperienceColor(50)).assertEqual('info');
    });

    // ========== 切片23: getExperienceColor - 70 → info（上界） ==========

    it('exp_color_70_returns_info', 0, () => {
      expect(AgentSkillViewHelper.getExperienceColor(70)).assertEqual('info');
    });

    // ========== 切片24: getExperienceColor - > 70 → success ==========

    it('exp_color_above_70_returns_success', 0, () => {
      expect(AgentSkillViewHelper.getExperienceColor(85)).assertEqual('success');
    });

    // ========== 切片25: formatCooldown - undefined → "—" ==========

    it('format_cooldown_undefined_returns_dash', 0, () => {
      expect(AgentSkillViewHelper.formatCooldown(undefined)).assertEqual('—');
    });

    // ========== 切片26: formatCooldown - 已过期 → "就绪" ==========

    it('format_cooldown_past_returns_ready', 0, () => {
      const ts = new Date(Date.now() - 60 * 1000).toISOString();
      expect(AgentSkillViewHelper.formatCooldown(ts)).assertEqual('就绪');
    });

    // ========== 切片27: formatCooldown - 30 秒后 → "30 秒后" ==========

    it('format_cooldown_future_seconds_returns_X秒后', 0, () => {
      const ts = new Date(Date.now() + 30 * 1000).toISOString();
      expect(AgentSkillViewHelper.formatCooldown(ts)).assertEqual('30 秒后');
    });

    // ========== 切片28: formatCooldown - 5 分钟后 → "5 分钟后" ==========

    it('format_cooldown_future_minutes_returns_X分钟后', 0, () => {
      const ts = new Date(Date.now() + 5 * 60 * 1000).toISOString();
      expect(AgentSkillViewHelper.formatCooldown(ts)).assertEqual('5 分钟后');
    });
  });
}
