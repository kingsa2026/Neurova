// AgentEmotionPage 情绪记录页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentEmotionViewHelper 视图模型行为（情绪类型颜色映射、图标映射、中文标签、
//           强度百分比格式化、触发原因截断及边界场景）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AgentEmotionPage.ets 导出的 AgentEmotionViewHelper 静态方法进行验证，
//       覆盖页面 getTypeColor / getTypeIcon / getTypeLabel / formatIntensity / truncateTrigger
//       的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentEmotionViewHelper } from '../../../../main/ets/pages/AgentEmotionPage';

export default function agentEmotionPageTest() {
  describe('AgentEmotionPage', () => {
    // ========== 切片1: getTypeColor - happy → success ==========

    it('type_color_happy_returns_success', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('happy')).assertEqual('success');
    });

    // ========== 切片2: getTypeColor - sad → info ==========

    it('type_color_sad_returns_info', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('sad')).assertEqual('info');
    });

    // ========== 切片3: getTypeColor - angry → error ==========

    it('type_color_angry_returns_error', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('angry')).assertEqual('error');
    });

    // ========== 切片4: getTypeColor - surprised → warning ==========

    it('type_color_surprised_returns_warning', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('surprised')).assertEqual('warning');
    });

    // ========== 切片5: getTypeColor - neutral → text_secondary ==========

    it('type_color_neutral_returns_text_secondary', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('neutral')).assertEqual('text_secondary');
    });

    // ========== 切片6: getTypeColor - fear → text_disabled ==========

    it('type_color_fear_returns_text_disabled', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('fear')).assertEqual('text_disabled');
    });

    // ========== 切片7: getTypeColor - disgust → text_secondary ==========

    it('type_color_disgust_returns_text_secondary', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('disgust')).assertEqual('text_secondary');
    });

    // ========== 切片8: getTypeColor - 未知类型 → text_disabled ==========

    it('type_color_unknown_returns_text_disabled', 0, () => {
      expect(AgentEmotionViewHelper.getTypeColor('unknown_type')).assertEqual('text_disabled');
    });

    // ========== 切片9: getTypeIcon - happy → 😊 ==========

    it('type_icon_happy_returns_smile_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('happy')).assertEqual('😊');
    });

    // ========== 切片10: getTypeIcon - sad → 😢 ==========

    it('type_icon_sad_returns_cry_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('sad')).assertEqual('😢');
    });

    // ========== 切片11: getTypeIcon - angry → 😠 ==========

    it('type_icon_angry_returns_angry_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('angry')).assertEqual('😠');
    });

    // ========== 切片12: getTypeIcon - surprised → 😮 ==========

    it('type_icon_surprised_returns_surprised_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('surprised')).assertEqual('😮');
    });

    // ========== 切片13: getTypeIcon - neutral → 😐 ==========

    it('type_icon_neutral_returns_neutral_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('neutral')).assertEqual('😐');
    });

    // ========== 切片14: getTypeIcon - fear → 😨 ==========

    it('type_icon_fear_returns_fear_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('fear')).assertEqual('😨');
    });

    // ========== 切片15: getTypeIcon - disgust → 🤢 ==========

    it('type_icon_disgust_returns_disgust_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('disgust')).assertEqual('🤢');
    });

    // ========== 切片16: getTypeIcon - 未知类型 → ❓ ==========

    it('type_icon_unknown_returns_question_emoji', 0, () => {
      expect(AgentEmotionViewHelper.getTypeIcon('unknown_type')).assertEqual('❓');
    });

    // ========== 切片17: getTypeLabel - happy → 开心 ==========

    it('type_label_happy_returns_kaixin', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('happy')).assertEqual('开心');
    });

    // ========== 切片18: getTypeLabel - sad → 难过 ==========

    it('type_label_sad_returns_nanguo', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('sad')).assertEqual('难过');
    });

    // ========== 切片19: getTypeLabel - angry → 愤怒 ==========

    it('type_label_angry_returns_fennu', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('angry')).assertEqual('愤怒');
    });

    // ========== 切片20: getTypeLabel - surprised → 惊讶 ==========

    it('type_label_surprised_returns_jingya', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('surprised')).assertEqual('惊讶');
    });

    // ========== 切片21: getTypeLabel - neutral → 平静 ==========

    it('type_label_neutral_returns_pingjing', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('neutral')).assertEqual('平静');
    });

    // ========== 切片22: getTypeLabel - fear → 恐惧 ==========

    it('type_label_fear_returns_kongju', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('fear')).assertEqual('恐惧');
    });

    // ========== 切片23: getTypeLabel - disgust → 厌恶 ==========

    it('type_label_disgust_returns_yanwu', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('disgust')).assertEqual('厌恶');
    });

    // ========== 切片24: getTypeLabel - 未知类型 → 未知 ==========

    it('type_label_unknown_returns_weizhi', 0, () => {
      expect(AgentEmotionViewHelper.getTypeLabel('unknown_type')).assertEqual('未知');
    });

    // ========== 切片25: formatIntensity - 0.5 → "50%" ==========

    it('format_intensity_half_returns_50_percent', 0, () => {
      expect(AgentEmotionViewHelper.formatIntensity(0.5)).assertEqual('50%');
    });

    // ========== 切片26: formatIntensity - 1 → "100%" ==========

    it('format_intensity_full_returns_100_percent', 0, () => {
      expect(AgentEmotionViewHelper.formatIntensity(1)).assertEqual('100%');
    });

    // ========== 切片27: formatIntensity - 0 → "0%" ==========

    it('format_intensity_zero_returns_0_percent', 0, () => {
      expect(AgentEmotionViewHelper.formatIntensity(0)).assertEqual('0%');
    });

    // ========== 切片28: formatIntensity - 0.333 → "33%"（四舍五入） ==========

    it('format_intensity_rounds_correctly', 0, () => {
      expect(AgentEmotionViewHelper.formatIntensity(0.333)).assertEqual('33%');
    });

    // ========== 切片29: truncateTrigger - undefined → "—" ==========

    it('truncate_trigger_undefined_returns_dash', 0, () => {
      expect(AgentEmotionViewHelper.truncateTrigger(undefined)).assertEqual('—');
    });

    // ========== 切片30: truncateTrigger - 空字符串 → "—" ==========

    it('truncate_trigger_empty_returns_dash', 0, () => {
      expect(AgentEmotionViewHelper.truncateTrigger('')).assertEqual('—');
    });

    // ========== 切片31: truncateTrigger - 未超长原样返回 ==========

    it('truncate_trigger_short_returns_original', 0, () => {
      const short = '收到用户问候';
      expect(AgentEmotionViewHelper.truncateTrigger(short)).assertEqual(short);
    });

    // ========== 切片32: truncateTrigger - 超长截断加省略号（默认 60） ==========

    it('truncate_trigger_over_default_max_truncates', 0, () => {
      const long = 'abcdefghij'.repeat(10); // 100 字符
      const result = AgentEmotionViewHelper.truncateTrigger(long);
      expect(result.length).assertEqual(63); // 60 + '...'
      expect(result.substring(60)).assertEqual('...');
    });

    // ========== 切片33: truncateTrigger - 自定义 maxLen ==========

    it('truncate_trigger_custom_max_len', 0, () => {
      const text = 'abcdefghij'.repeat(5); // 50 字符
      const result = AgentEmotionViewHelper.truncateTrigger(text, 20);
      expect(result.length).assertEqual(23); // 20 + '...'
      expect(result.substring(20)).assertEqual('...');
    });
  });
}
