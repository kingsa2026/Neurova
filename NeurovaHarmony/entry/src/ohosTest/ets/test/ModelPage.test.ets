// ModelPage 模型管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：ModelViewHelper 视图模型行为（Provider 状态颜色、健康状态图标、
//           模型类型图标、上下文窗口格式化）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 ModelPage.ets 导出的 ModelViewHelper 静态方法进行验证，
//       覆盖页面 getStatusColor / getHealthIcon / getModelTypeIcon / formatContextWindow
//       的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { ModelViewHelper } from '../../../../main/ets/pages/ModelPage';

export default function modelPageTest() {
  describe('ModelPage', () => {
    // ========== 切片1: getStatusColor - available → success ==========

    it('status_color_available_returns_success', 0, () => {
      expect(ModelViewHelper.getStatusColor('available')).assertEqual('success');
    });

    // ========== 切片2: getStatusColor - unavailable → text_disabled ==========

    it('status_color_unavailable_returns_text_disabled', 0, () => {
      expect(ModelViewHelper.getStatusColor('unavailable')).assertEqual('text_disabled');
    });

    // ========== 切片3: getStatusColor - not_configured → warning ==========

    it('status_color_not_configured_returns_warning', 0, () => {
      expect(ModelViewHelper.getStatusColor('not_configured')).assertEqual('warning');
    });

    // ========== 切片4: getStatusColor - not_ready → error ==========

    it('status_color_not_ready_returns_error', 0, () => {
      expect(ModelViewHelper.getStatusColor('not_ready')).assertEqual('error');
    });

    // ========== 切片5: getHealthIcon - healthy → ✅ ==========

    it('health_icon_healthy_returns_check', 0, () => {
      expect(ModelViewHelper.getHealthIcon('healthy')).assertEqual('✅');
    });

    // ========== 切片6: getHealthIcon - unhealthy → ⚠️ ==========

    it('health_icon_unhealthy_returns_warning', 0, () => {
      expect(ModelViewHelper.getHealthIcon('unhealthy')).assertEqual('⚠️');
    });

    // ========== 切片7: getHealthIcon - unknown → ❓ ==========

    it('health_icon_unknown_returns_question', 0, () => {
      expect(ModelViewHelper.getHealthIcon('unknown')).assertEqual('❓');
    });

    // ========== 切片8: getModelTypeIcon - text → 📝 ==========

    it('model_type_icon_text_returns_document', 0, () => {
      expect(ModelViewHelper.getModelTypeIcon('text')).assertEqual('📝');
    });

    // ========== 切片9: getModelTypeIcon - image → 🖼️ ==========

    it('model_type_icon_image_returns_picture', 0, () => {
      expect(ModelViewHelper.getModelTypeIcon('image')).assertEqual('🖼️');
    });

    // ========== 切片10: getModelTypeIcon - audio → 🎵 ==========

    it('model_type_icon_audio_returns_music', 0, () => {
      expect(ModelViewHelper.getModelTypeIcon('audio')).assertEqual('🎵');
    });

    // ========== 切片11: formatContextWindow - 8192→"8K", 16384→"16K", 1048576→"1M" ==========

    it('format_context_window_human_readable', 0, () => {
      expect(ModelViewHelper.formatContextWindow(8192)).assertEqual('8K');
      expect(ModelViewHelper.formatContextWindow(16384)).assertEqual('16K');
      expect(ModelViewHelper.formatContextWindow(1048576)).assertEqual('1M');
    });

    // ========== 切片12: formatContextWindow - 0 / undefined → "无限制" ==========

    it('format_context_window_zero_returns_unlimited', 0, () => {
      expect(ModelViewHelper.formatContextWindow(0)).assertEqual('无限制');
      expect(ModelViewHelper.formatContextWindow(undefined)).assertEqual('无限制');
    });
  });
}
