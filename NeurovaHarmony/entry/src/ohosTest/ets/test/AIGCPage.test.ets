// AIGCPage AIGC 任务页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AIGCViewHelper 视图模型行为（任务类型颜色映射、类型图标、类型文案、
//           状态颜色、状态图标、状态文案、prompt 截断、时长格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AIGCPage.ets 导出的 AIGCViewHelper 静态方法进行验证，
//       覆盖页面 getTypeColor / getTypeIcon / getTypeLabel / getStatusColor /
//       getStatusIcon / getStatusLabel / truncatePrompt / formatDuration 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AIGCViewHelper } from '../../../../main/ets/pages/AIGCPage';

export default function aigcPageTest() {
  describe('AIGCPage', () => {
    // ========== 切片1: getTypeColor - text → info ==========

    it('type_color_text_returns_info', 0, () => {
      expect(AIGCViewHelper.getTypeColor('text')).assertEqual('info');
    });

    // ========== 切片2: getTypeColor - image → primary ==========

    it('type_color_image_returns_primary', 0, () => {
      expect(AIGCViewHelper.getTypeColor('image')).assertEqual('primary');
    });

    // ========== 切片3: getTypeColor - audio → warning ==========

    it('type_color_audio_returns_warning', 0, () => {
      expect(AIGCViewHelper.getTypeColor('audio')).assertEqual('warning');
    });

    // ========== 切片4: getTypeColor - video → error ==========

    it('type_color_video_returns_error', 0, () => {
      expect(AIGCViewHelper.getTypeColor('video')).assertEqual('error');
    });

    // ========== 切片5: getTypeIcon - text → 📝 ==========

    it('type_icon_text_returns_pencil', 0, () => {
      expect(AIGCViewHelper.getTypeIcon('text')).assertEqual('📝');
    });

    // ========== 切片6: getTypeIcon - image → 🖼️ ==========

    it('type_icon_image_returns_picture', 0, () => {
      expect(AIGCViewHelper.getTypeIcon('image')).assertEqual('🖼️');
    });

    // ========== 切片7: getTypeIcon - audio → 🎵 ==========

    it('type_icon_audio_returns_music', 0, () => {
      expect(AIGCViewHelper.getTypeIcon('audio')).assertEqual('🎵');
    });

    // ========== 切片8: getTypeIcon - video → 🎬 ==========

    it('type_icon_video_returns_clapper', 0, () => {
      expect(AIGCViewHelper.getTypeIcon('video')).assertEqual('🎬');
    });

    // ========== 切片9: getTypeLabel - text → 文本 ==========

    it('type_label_text_returns_文本', 0, () => {
      expect(AIGCViewHelper.getTypeLabel('text')).assertEqual('文本');
    });

    // ========== 切片10: getTypeLabel - image → 图像 ==========

    it('type_label_image_returns_图像', 0, () => {
      expect(AIGCViewHelper.getTypeLabel('image')).assertEqual('图像');
    });

    // ========== 切片11: getStatusColor - queued → warning ==========

    it('status_color_queued_returns_warning', 0, () => {
      expect(AIGCViewHelper.getStatusColor('queued')).assertEqual('warning');
    });

    // ========== 切片12: getStatusColor - processing → info ==========

    it('status_color_processing_returns_info', 0, () => {
      expect(AIGCViewHelper.getStatusColor('processing')).assertEqual('info');
    });

    // ========== 切片13: getStatusColor - succeeded → success ==========

    it('status_color_succeeded_returns_success', 0, () => {
      expect(AIGCViewHelper.getStatusColor('succeeded')).assertEqual('success');
    });

    // ========== 切片14: getStatusColor - failed → error ==========

    it('status_color_failed_returns_error', 0, () => {
      expect(AIGCViewHelper.getStatusColor('failed')).assertEqual('error');
    });

    // ========== 切片15: getStatusIcon - queued → ⏳ ==========

    it('status_icon_queued_returns_hourglass', 0, () => {
      expect(AIGCViewHelper.getStatusIcon('queued')).assertEqual('⏳');
    });

    // ========== 切片16: getStatusIcon - processing → ⚡ ==========

    it('status_icon_processing_returns_bolt', 0, () => {
      expect(AIGCViewHelper.getStatusIcon('processing')).assertEqual('⚡');
    });

    // ========== 切片17: getStatusIcon - succeeded → ✅ ==========

    it('status_icon_succeeded_returns_check', 0, () => {
      expect(AIGCViewHelper.getStatusIcon('succeeded')).assertEqual('✅');
    });

    // ========== 切片18: getStatusIcon - failed → ❌ ==========

    it('status_icon_failed_returns_cross', 0, () => {
      expect(AIGCViewHelper.getStatusIcon('failed')).assertEqual('❌');
    });

    // ========== 切片19: getStatusLabel - queued → 排队中 ==========

    it('status_label_queued_returns_queuing', 0, () => {
      expect(AIGCViewHelper.getStatusLabel('queued')).assertEqual('排队中');
    });

    // ========== 切片20: getStatusLabel - processing → 处理中 ==========

    it('status_label_processing_returns_processing', 0, () => {
      expect(AIGCViewHelper.getStatusLabel('processing')).assertEqual('处理中');
    });

    // ========== 切片21: getStatusLabel - succeeded → 已完成 ==========

    it('status_label_succeeded_returns_completed', 0, () => {
      expect(AIGCViewHelper.getStatusLabel('succeeded')).assertEqual('已完成');
    });

    // ========== 切片22: getStatusLabel - failed → 失败 ==========

    it('status_label_failed_returns_failed', 0, () => {
      expect(AIGCViewHelper.getStatusLabel('failed')).assertEqual('失败');
    });

    // ========== 切片23: truncatePrompt - 默认 maxLen=100 ==========

    it('truncate_prompt_default_100', 0, () => {
      const s = 'a'.repeat(150);
      const result = AIGCViewHelper.truncatePrompt(s);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });

    // ========== 切片24: truncatePrompt - 自定义 maxLen ==========

    it('truncate_prompt_custom_maxLen', 0, () => {
      const s = 'abcdefg';
      const result = AIGCViewHelper.truncatePrompt(s, 5);
      expect(result).assertEqual('abcde...');
    });

    // ========== 切片25: formatDuration - 无 finishedAt → "—" ==========

    it('format_duration_no_finish_returns_dash', 0, () => {
      const result = AIGCViewHelper.formatDuration('2025-01-01T10:00:00Z', undefined);
      expect(result).assertEqual('—');
    });

    // ========== 切片26: formatDuration - 短时 → "n.nn s" ==========

    it('format_duration_short_returns_seconds', 0, () => {
      // 1500ms → "1.50 s"
      const start = '2025-01-01T10:00:00.000Z';
      const end = '2025-01-01T10:00:01.500Z';
      const result = AIGCViewHelper.formatDuration(start, end);
      expect(result).assertEqual('1.50 s');
    });

    // ========== 切片27: formatDuration - 长时 → "M:SS" ==========

    it('format_duration_long_returns_m_ss', 0, () => {
      // 65 秒 → "1:05"
      const start = '2025-01-01T10:00:00.000Z';
      const end = '2025-01-01T10:01:05.000Z';
      const result = AIGCViewHelper.formatDuration(start, end);
      expect(result).assertEqual('1:05');
    });
  });
}
