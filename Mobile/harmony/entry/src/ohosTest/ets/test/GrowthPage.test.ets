// GrowthPage 成长记录页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：GrowthViewHelper 视图模型行为（维度颜色映射、维度图标映射、维度中文标签、
//           等级格式化、经验进度计算、里程碑数文案及边界场景）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 GrowthPage.ets 导出的 GrowthViewHelper 静态方法进行验证，
//       覆盖页面 getDimensionColor / getDimensionIcon / getDimensionLabel / formatLevel /
//       calculateProgressToNext / getMilestoneCount 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { GrowthViewHelper } from '../../../../main/ets/pages/GrowthPage';

export default function growthPageTest() {
  describe('GrowthPage', () => {
    // ========== 切片1: getDimensionColor - knowledge → info ==========

    it('dimension_color_knowledge_returns_info', 0, () => {
      expect(GrowthViewHelper.getDimensionColor('knowledge')).assertEqual('info');
    });

    // ========== 切片2: getDimensionColor - skill → primary ==========

    it('dimension_color_skill_returns_primary', 0, () => {
      expect(GrowthViewHelper.getDimensionColor('skill')).assertEqual('primary');
    });

    // ========== 切片3: getDimensionColor - emotion → warning ==========

    it('dimension_color_emotion_returns_warning', 0, () => {
      expect(GrowthViewHelper.getDimensionColor('emotion')).assertEqual('warning');
    });

    // ========== 切片4: getDimensionColor - social → success ==========

    it('dimension_color_social_returns_success', 0, () => {
      expect(GrowthViewHelper.getDimensionColor('social')).assertEqual('success');
    });

    // ========== 切片5: getDimensionColor - meta → text_secondary ==========

    it('dimension_color_meta_returns_text_secondary', 0, () => {
      expect(GrowthViewHelper.getDimensionColor('meta')).assertEqual('text_secondary');
    });

    // ========== 切片6: getDimensionIcon - knowledge → 📚 ==========

    it('dimension_icon_knowledge_returns_book_emoji', 0, () => {
      expect(GrowthViewHelper.getDimensionIcon('knowledge')).assertEqual('📚');
    });

    // ========== 切片7: getDimensionIcon - skill → 🛠️ ==========

    it('dimension_icon_skill_returns_tools_emoji', 0, () => {
      expect(GrowthViewHelper.getDimensionIcon('skill')).assertEqual('🛠️');
    });

    // ========== 切片8: getDimensionIcon - emotion → 😊 ==========

    it('dimension_icon_emotion_returns_smile_emoji', 0, () => {
      expect(GrowthViewHelper.getDimensionIcon('emotion')).assertEqual('😊');
    });

    // ========== 切片9: getDimensionIcon - social → 🤝 ==========

    it('dimension_icon_social_returns_handshake_emoji', 0, () => {
      expect(GrowthViewHelper.getDimensionIcon('social')).assertEqual('🤝');
    });

    // ========== 切片10: getDimensionIcon - meta → 🧠 ==========

    it('dimension_icon_meta_returns_brain_emoji', 0, () => {
      expect(GrowthViewHelper.getDimensionIcon('meta')).assertEqual('🧠');
    });

    // ========== 切片11: getDimensionLabel - knowledge → 知识 ==========

    it('dimension_label_knowledge_returns_zhishi', 0, () => {
      expect(GrowthViewHelper.getDimensionLabel('knowledge')).assertEqual('知识');
    });

    // ========== 切片12: getDimensionLabel - meta → 元认知 ==========

    it('dimension_label_meta_returns_metacognition', 0, () => {
      expect(GrowthViewHelper.getDimensionLabel('meta')).assertEqual('元认知');
    });

    // ========== 切片13: formatLevel - n → "Lv.n" ==========

    it('format_level_returns_lv_n', 0, () => {
      expect(GrowthViewHelper.formatLevel(5)).assertEqual('Lv.5');
    });

    // ========== 切片14: formatLevel - 0 → "Lv.0" ==========

    it('format_level_zero_returns_lv_0', 0, () => {
      expect(GrowthViewHelper.formatLevel(0)).assertEqual('Lv.0');
    });

    // ========== 切片15: calculateProgressToNext - 正常计算（experience/threshold）==========

    it('progress_to_next_normal_returns_fraction', 0, () => {
      expect(GrowthViewHelper.calculateProgressToNext(50, 100)).assertEqual(0.5);
    });

    // ========== 切片16: calculateProgressToNext - 阈值 ≤0 返回 0 ==========

    it('progress_to_next_threshold_zero_returns_zero', 0, () => {
      expect(GrowthViewHelper.calculateProgressToNext(50, 0)).assertEqual(0);
    });

    // ========== 切片17: calculateProgressToNext - 阈值负数返回 0 ==========

    it('progress_to_next_threshold_negative_returns_zero', 0, () => {
      expect(GrowthViewHelper.calculateProgressToNext(50, -10)).assertEqual(0);
    });

    // ========== 切片18: calculateProgressToNext - 经验超过阈值封顶 1 ==========

    it('progress_to_next_over_threshold_returns_one', 0, () => {
      expect(GrowthViewHelper.calculateProgressToNext(150, 100)).assertEqual(1);
    });

    // ========== 切片19: calculateProgressToNext - 经验为 0 返回 0 ==========

    it('progress_to_next_experience_zero_returns_zero', 0, () => {
      expect(GrowthViewHelper.calculateProgressToNext(0, 100)).assertEqual(0);
    });

    // ========== 切片20: getMilestoneCount - 0 → "无里程碑" ==========

    it('milestone_count_zero_returns_empty_text', 0, () => {
      expect(GrowthViewHelper.getMilestoneCount(0)).assertEqual('无里程碑');
    });

    // ========== 切片21: getMilestoneCount - 正数 → "里程碑 n 项" ==========

    it('milestone_count_positive_returns_count_text', 0, () => {
      expect(GrowthViewHelper.getMilestoneCount(3)).assertEqual('里程碑 3 项');
    });
  });
}
