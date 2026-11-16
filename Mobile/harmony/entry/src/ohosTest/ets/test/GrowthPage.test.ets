// GrowthPage 成长画像页单元测试 - 真实契约版
//
// 测试范围：GrowthViewHelper 视图模型行为（百分比格式化、驱动力/风格/宪法类型/
//           反思类型中文映射、内容截断、秒级时间戳格式化及边界场景）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 GrowthPage.ets 导出的 GrowthViewHelper 静态方法进行验证，
//       覆盖页面 formatPercent / driveLabel / styleLabel / ruleTypeLabel /
//       reflectionTypeLabel / truncateContent / formatTimestamp 的核心视图逻辑。
import { describe, it, expect } from '@ohos/hypium';
import { GrowthViewHelper } from '../../../../main/ets/pages/GrowthPage';

export default function growthPageTest() {
  describe('GrowthPage', () => {
    // ========== 切片1: formatPercent - 0-1 → 百分比 ==========

    it('format_percent_normal_returns_rounded', 0, () => {
      expect(GrowthViewHelper.formatPercent(0.5)).assertEqual('50%');
      expect(GrowthViewHelper.formatPercent(0.724)).assertEqual('72%');
    });

    // ========== 切片2: formatPercent - 越界截断 ==========

    it('format_percent_out_of_range_clamps', 0, () => {
      expect(GrowthViewHelper.formatPercent(-0.2)).assertEqual('0%');
      expect(GrowthViewHelper.formatPercent(1.5)).assertEqual('100%');
    });

    // ========== 切片3: driveLabel - 已知驱动 → 中文，未知原样 ==========

    it('drive_label_known_returns_chinese', 0, () => {
      expect(GrowthViewHelper.driveLabel('curiosity')).assertEqual('好奇');
      expect(GrowthViewHelper.driveLabel('autonomy')).assertEqual('自主');
      expect(GrowthViewHelper.driveLabel('competence')).assertEqual('胜任');
      expect(GrowthViewHelper.driveLabel('relatedness')).assertEqual('联结');
    });

    it('drive_label_unknown_returns_raw', 0, () => {
      expect(GrowthViewHelper.driveLabel('novel_drive')).assertEqual('novel_drive');
    });

    // ========== 切片4: styleLabel - 已知风格 → 中文，未知原样 ==========

    it('style_label_known_returns_chinese', 0, () => {
      expect(GrowthViewHelper.styleLabel('balanced')).assertEqual('均衡');
      expect(GrowthViewHelper.styleLabel('analytical')).assertEqual('分析型');
      expect(GrowthViewHelper.styleLabel('empathetic')).assertEqual('共情');
    });

    it('style_label_unknown_returns_raw', 0, () => {
      expect(GrowthViewHelper.styleLabel('custom_style')).assertEqual('custom_style');
    });

    // ========== 切片5: ruleTypeLabel - 已知类型 → 中文，未知原样 ==========

    it('rule_type_label_known_returns_chinese', 0, () => {
      expect(GrowthViewHelper.ruleTypeLabel('behavior')).assertEqual('行为');
      expect(GrowthViewHelper.ruleTypeLabel('boundary')).assertEqual('边界');
      expect(GrowthViewHelper.ruleTypeLabel('value')).assertEqual('价值');
    });

    it('rule_type_label_unknown_returns_raw', 0, () => {
      expect(GrowthViewHelper.ruleTypeLabel('other')).assertEqual('other');
    });

    // ========== 切片6: reflectionTypeLabel - 已知类型 → 中文 ==========

    it('reflection_type_label_known_returns_chinese', 0, () => {
      expect(GrowthViewHelper.reflectionTypeLabel('performance')).assertEqual('性能反思');
      expect(GrowthViewHelper.reflectionTypeLabel('error')).assertEqual('错误反思');
    });

    // ========== 切片7: truncateContent - 默认 80 截断加省略号 ==========

    it('truncate_content_default_80_truncates', 0, () => {
      const long = 'a'.repeat(120);
      const result = GrowthViewHelper.truncateContent(long);
      expect(result.length).assertEqual(83);
      expect(result.endsWith('...')).assertTrue();
    });

    // ========== 切片8: truncateContent - 未超长原样返回 ==========

    it('truncate_content_short_returns_original', 0, () => {
      expect(GrowthViewHelper.truncateContent('short')).assertEqual('short');
    });

    // ========== 切片9: formatTimestamp - 秒级时间戳 → YYYY-MM-DD HH:mm ==========

    it('format_timestamp_seconds_returns_formatted', 0, () => {
      const d = new Date(2026, 0, 15, 9, 5);
      const ts = Math.floor(d.getTime() / 1000);
      expect(GrowthViewHelper.formatTimestamp(ts)).assertEqual('2026-01-15 09:05');
    });

    // ========== 切片10: formatTimestamp - 非正数 → "未知" ==========

    it('format_timestamp_non_positive_returns_unknown', 0, () => {
      expect(GrowthViewHelper.formatTimestamp(0)).assertEqual('未知');
      expect(GrowthViewHelper.formatTimestamp(-1)).assertEqual('未知');
    });
  });
}
