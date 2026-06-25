// AgentPersonalityPage 个性配置页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentPersonalityViewHelper 视图模型行为（5 维度颜色映射、图标映射、中文标签、
//           百分比格式化、脏数据比较、维度描述文案生成及边界场景）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentPersonalityPage.ets 导出的 AgentPersonalityViewHelper 静态方法进行验证，
//       覆盖页面 getDimensionIcon / getDimensionLabel / getDimensionColor / formatPercent /
//       isDirty / buildDescription 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentPersonalityViewHelper } from '../../../../main/ets/pages/AgentPersonalityPage';
import { Personality } from '../../../../main/ets/libs/types';

export default function agentPersonalityPageTest() {
  describe('AgentPersonalityPage', () => {
    // ========== 切片1: getDimensionIcon - openness → 🎨 ==========

    it('dimension_icon_openness_returns_palette_emoji', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionIcon('openness')).assertEqual('🎨');
    });

    // ========== 切片2: getDimensionIcon - conscientiousness → 📋 ==========

    it('dimension_icon_conscientiousness_returns_clipboard_emoji', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionIcon('conscientiousness')).assertEqual('📋');
    });

    // ========== 切片3: getDimensionIcon - extraversion → 🎉 ==========

    it('dimension_icon_extraversion_returns_party_emoji', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionIcon('extraversion')).assertEqual('🎉');
    });

    // ========== 切片4: getDimensionIcon - agreeableness → 🤝 ==========

    it('dimension_icon_agreeableness_returns_handshake_emoji', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionIcon('agreeableness')).assertEqual('🤝');
    });

    // ========== 切片5: getDimensionIcon - neuroticism → 🌪️ ==========

    it('dimension_icon_neuroticism_returns_tornado_emoji', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionIcon('neuroticism')).assertEqual('🌪️');
    });

    // ========== 切片6: getDimensionLabel - openness → 开放性 ==========

    it('dimension_label_openness_returns_kaifangxing', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionLabel('openness')).assertEqual('开放性');
    });

    // ========== 切片7: getDimensionLabel - conscientiousness → 尽责性 ==========

    it('dimension_label_conscientiousness_returns_jinzexing', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionLabel('conscientiousness')).assertEqual('尽责性');
    });

    // ========== 切片8: getDimensionLabel - extraversion → 外向性 ==========

    it('dimension_label_extraversion_returns_waixiangxing', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionLabel('extraversion')).assertEqual('外向性');
    });

    // ========== 切片9: getDimensionLabel - agreeableness → 宜人性 ==========

    it('dimension_label_agreeableness_returns_yirenxing', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionLabel('agreeableness')).assertEqual('宜人性');
    });

    // ========== 切片10: getDimensionLabel - neuroticism → 神经质 ==========

    it('dimension_label_neuroticism_returns_shenjingzhi', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionLabel('neuroticism')).assertEqual('神经质');
    });

    // ========== 切片11: getDimensionColor - openness → info ==========

    it('dimension_color_openness_returns_info', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionColor('openness')).assertEqual('info');
    });

    // ========== 切片12: getDimensionColor - conscientiousness → primary ==========

    it('dimension_color_conscientiousness_returns_primary', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionColor('conscientiousness')).assertEqual('primary');
    });

    // ========== 切片13: getDimensionColor - extraversion → warning ==========

    it('dimension_color_extraversion_returns_warning', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionColor('extraversion')).assertEqual('warning');
    });

    // ========== 切片14: getDimensionColor - agreeableness → success ==========

    it('dimension_color_agreeableness_returns_success', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionColor('agreeableness')).assertEqual('success');
    });

    // ========== 切片15: getDimensionColor - neuroticism → error ==========

    it('dimension_color_neuroticism_returns_error', 0, () => {
      expect(AgentPersonalityViewHelper.getDimensionColor('neuroticism')).assertEqual('error');
    });

    // ========== 切片16: formatPercent - 0.5 → "50%" ==========

    it('format_percent_half_returns_50_percent', 0, () => {
      expect(AgentPersonalityViewHelper.formatPercent(0.5)).assertEqual('50%');
    });

    // ========== 切片17: formatPercent - 1 → "100%" ==========

    it('format_percent_full_returns_100_percent', 0, () => {
      expect(AgentPersonalityViewHelper.formatPercent(1)).assertEqual('100%');
    });

    // ========== 切片18: formatPercent - 0 → "0%" ==========

    it('format_percent_zero_returns_0_percent', 0, () => {
      expect(AgentPersonalityViewHelper.formatPercent(0)).assertEqual('0%');
    });

    // ========== 切片19: isDirty - 所有维度相同返回 false ==========

    it('is_dirty_all_same_returns_false', 0, () => {
      const p: Personality = makePersonality(0.5, 0.6, 0.7, 0.8, 0.4);
      expect(AgentPersonalityViewHelper.isDirty(p, p)).assertFalse();
    });

    // ========== 切片20: isDirty - openness 不同返回 true ==========

    it('is_dirty_openness_changed_returns_true', 0, () => {
      const original = makePersonality(0.5, 0.6, 0.7, 0.8, 0.4);
      const current = makePersonality(0.9, 0.6, 0.7, 0.8, 0.4);
      expect(AgentPersonalityViewHelper.isDirty(current, original)).assertTrue();
    });

    // ========== 切片21: isDirty - neuroticism 不同返回 true ==========

    it('is_dirty_neuroticism_changed_returns_true', 0, () => {
      const original = makePersonality(0.5, 0.6, 0.7, 0.8, 0.4);
      const current = makePersonality(0.5, 0.6, 0.7, 0.8, 0.2);
      expect(AgentPersonalityViewHelper.isDirty(current, original)).assertTrue();
    });

    // ========== 切片22: isDirty - 中间维度 conscientiousness 不同返回 true ==========

    it('is_dirty_conscientiousness_changed_returns_true', 0, () => {
      const original = makePersonality(0.5, 0.6, 0.7, 0.8, 0.4);
      const current = makePersonality(0.5, 0.3, 0.7, 0.8, 0.4);
      expect(AgentPersonalityViewHelper.isDirty(current, original)).assertTrue();
    });

    // ========== buildDescription: 5 维度 × 3 档（低/中/高）共 15 种组合 ==========

    // ========== 切片23: buildDescription - openness 低（0.0-0.33） ==========

    it('build_description_openness_low_returns_traditional_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.2);
      expect(text).assertEqual('开放性低：偏向传统与保守');
    });

    // ========== 切片24: buildDescription - openness 中（0.34-0.66） ==========

    it('build_description_openness_mid_returns_balanced_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.5);
      expect(text).assertEqual('开放性中：在传统与创新间平衡');
    });

    // ========== 切片25: buildDescription - openness 高（0.67-1.0） ==========

    it('build_description_openness_high_returns_creative_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.9);
      expect(text).assertEqual('开放性高：富有想象力与创新精神');
    });

    // ========== 切片26: buildDescription - conscientiousness 低 ==========

    it('build_description_conscientiousness_low_returns_flexible_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('conscientiousness', 0.1);
      expect(text).assertEqual('尽责性低：灵活随性，不喜约束');
    });

    // ========== 切片27: buildDescription - conscientiousness 中 ==========

    it('build_description_conscientiousness_mid_returns_balanced_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('conscientiousness', 0.5);
      expect(text).assertEqual('尽责性中：在自律与灵活间平衡');
    });

    // ========== 切片28: buildDescription - conscientiousness 高 ==========

    it('build_description_conscientiousness_high_returns_disciplined_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('conscientiousness', 0.8);
      expect(text).assertEqual('尽责性高：自律严谨，目标明确');
    });

    // ========== 切片29: buildDescription - extraversion 低 ==========

    it('build_description_extraversion_low_returns_introverted_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('extraversion', 0.2);
      expect(text).assertEqual('外向性低：偏内向，喜静独处');
    });

    // ========== 切片30: buildDescription - extraversion 中 ==========

    it('build_description_extraversion_mid_returns_balanced_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('extraversion', 0.5);
      expect(text).assertEqual('外向性中：内外向平衡');
    });

    // ========== 切片31: buildDescription - extraversion 高 ==========

    it('build_description_extraversion_high_returns_outgoing_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('extraversion', 0.9);
      expect(text).assertEqual('外向性高：热情开朗，善于社交');
    });

    // ========== 切片32: buildDescription - agreeableness 低 ==========

    it('build_description_agreeableness_low_returns_critical_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('agreeableness', 0.1);
      expect(text).assertEqual('宜人性低：批判性强，坚持立场');
    });

    // ========== 切片33: buildDescription - agreeableness 中 ==========

    it('build_description_agreeableness_mid_returns_balanced_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('agreeableness', 0.5);
      expect(text).assertEqual('宜人性中：在合作与坚持间平衡');
    });

    // ========== 切片34: buildDescription - agreeableness 高 ==========

    it('build_description_agreeableness_high_returns_friendly_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('agreeableness', 0.8);
      expect(text).assertEqual('宜人性高：友善合作，乐于助人');
    });

    // ========== 切片35: buildDescription - neuroticism 低 ==========

    it('build_description_neuroticism_low_returns_stable_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('neuroticism', 0.2);
      expect(text).assertEqual('神经质低：情绪稳定，从容镇定');
    });

    // ========== 切片36: buildDescription - neuroticism 中 ==========

    it('build_description_neuroticism_mid_returns_balanced_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('neuroticism', 0.5);
      expect(text).assertEqual('神经质中：情绪波动适中');
    });

    // ========== 切片37: buildDescription - neuroticism 高 ==========

    it('build_description_neuroticism_high_returns_sensitive_text', 0, () => {
      const text = AgentPersonalityViewHelper.buildDescription('neuroticism', 0.9);
      expect(text).assertEqual('神经质高：情绪敏感，易感压力');
    });

    // ========== 切片38: buildDescription - 边界值 0.33 应归类为低 ==========

    it('build_description_boundary_033_classified_as_low', 0, () => {
      // 0.33 在 ≤0.33 区间，归类为低
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.33);
      expect(text).assertEqual('开放性低：偏向传统与保守');
    });

    // ========== 切片39: buildDescription - 边界值 0.34 应归类为中 ==========

    it('build_description_boundary_034_classified_as_mid', 0, () => {
      // 0.34 在 0.34-0.66 区间，归类为中
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.34);
      expect(text).assertEqual('开放性中：在传统与创新间平衡');
    });

    // ========== 切片40: buildDescription - 边界值 0.67 应归类为高 ==========

    it('build_description_boundary_067_classified_as_high', 0, () => {
      // 0.67 在 ≥0.67 区间，归类为高
      const text = AgentPersonalityViewHelper.buildDescription('openness', 0.67);
      expect(text).assertEqual('开放性高：富有想象力与创新精神');
    });
  });
}

/** 测试辅助：构造一个 Personality 对象（5 维度 + 必填字段） */
function makePersonality(
  openness: number,
  conscientiousness: number,
  extraversion: number,
  agreeableness: number,
  neuroticism: number,
): Personality {
  return {
    agentId: 'a1',
    openness,
    conscientiousness,
    extraversion,
    agreeableness,
    neuroticism,
    updatedAt: '',
  };
}
