// AgentMediaPage 媒体资产页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentMediaViewHelper 视图模型行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 AgentMediaPage 导出的 AgentMediaViewHelper 静态方法进行验证，
//       覆盖媒体类型颜色映射、类型图标映射、类型标签映射、文件大小格式化、时长格式化 5 个方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，返回颜色 token 名（如 'primary'）而非已解析
// 颜色值，便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentMediaViewHelper } from '../../../../main/ets/pages/AgentMediaPage';
import { MediaAssetType } from '../../../../main/ets/libs/types';

export default function agentMediaPageTest() {
  describe('AgentMediaPage', () => {
    // ========== 切片 1: getTypeColor - image → primary ==========

    it('type_color_image_returns_primary', 0, () => {
      expect(AgentMediaViewHelper.getTypeColor('image' as MediaAssetType)).assertEqual('primary');
    });

    // ========== 切片 2: getTypeColor - audio → info ==========

    it('type_color_audio_returns_info', 0, () => {
      expect(AgentMediaViewHelper.getTypeColor('audio' as MediaAssetType)).assertEqual('info');
    });

    // ========== 切片 3: getTypeColor - video → warning ==========

    it('type_color_video_returns_warning', 0, () => {
      expect(AgentMediaViewHelper.getTypeColor('video' as MediaAssetType)).assertEqual('warning');
    });

    // ========== 切片 4: getTypeColor - document → success ==========

    it('type_color_document_returns_success', 0, () => {
      expect(AgentMediaViewHelper.getTypeColor('document' as MediaAssetType)).assertEqual('success');
    });

    // ========== 切片 5: getTypeIcon - 四种类型对应 emoji ==========

    it('type_icon_returns_emoji', 0, () => {
      expect(AgentMediaViewHelper.getTypeIcon('image' as MediaAssetType)).assertEqual('🖼️');
      expect(AgentMediaViewHelper.getTypeIcon('audio' as MediaAssetType)).assertEqual('🎵');
      expect(AgentMediaViewHelper.getTypeIcon('video' as MediaAssetType)).assertEqual('🎬');
      expect(AgentMediaViewHelper.getTypeIcon('document' as MediaAssetType)).assertEqual('📄');
    });

    // ========== 切片 6: getTypeLabel - 四种类型对应中文 ==========

    it('type_label_returns_chinese', 0, () => {
      expect(AgentMediaViewHelper.getTypeLabel('image' as MediaAssetType)).assertEqual('图片');
      expect(AgentMediaViewHelper.getTypeLabel('audio' as MediaAssetType)).assertEqual('音频');
      expect(AgentMediaViewHelper.getTypeLabel('video' as MediaAssetType)).assertEqual('视频');
      expect(AgentMediaViewHelper.getTypeLabel('document' as MediaAssetType)).assertEqual('文档');
    });

    // ========== 切片 7: formatFileSize - KB/MB 单位阶梯（与 AgentFilePage 一致） ==========

    it('format_file_size_kb_mb', 0, () => {
      expect(AgentMediaViewHelper.formatFileSize(1024)).assertEqual('1.0 KB');
      expect(AgentMediaViewHelper.formatFileSize(1048576)).assertEqual('1.0 MB');
      expect(AgentMediaViewHelper.formatFileSize(512)).assertEqual('512 B');
      expect(AgentMediaViewHelper.formatFileSize(0)).assertEqual('—');
    });

    // ========== 切片 8: formatDuration - 分钟格式（< 1 小时） ==========

    it('format_duration_minutes', 0, () => {
      // 60 秒 → "1:00"（M:SS 格式）
      expect(AgentMediaViewHelper.formatDuration(60)).assertEqual('1:00');
      // 125 秒 → 2 分 5 秒 → "2:05"
      expect(AgentMediaViewHelper.formatDuration(125)).assertEqual('2:05');
      // 0 秒 → "0:00"
      expect(AgentMediaViewHelper.formatDuration(0)).assertEqual('0:00');
    });

    // ========== 切片 9: formatDuration - 小时格式（≥ 1 小时） ==========

    it('format_duration_hours', 0, () => {
      // 3600 秒 = 1 小时 → "1:00:00"（H:MM:SS 格式）
      expect(AgentMediaViewHelper.formatDuration(3600)).assertEqual('1:00:00');
      // 3661 秒 = 1:01:01
      expect(AgentMediaViewHelper.formatDuration(3661)).assertEqual('1:01:01');
      // 7200 秒 = 2 小时 → "2:00:00"
      expect(AgentMediaViewHelper.formatDuration(7200)).assertEqual('2:00:00');
    });

    // ========== 切片 10: formatDuration - undefined → "—" ==========

    it('format_duration_undefined_returns_dash', 0, () => {
      expect(AgentMediaViewHelper.formatDuration(undefined)).assertEqual('—');
    });
  });
}
