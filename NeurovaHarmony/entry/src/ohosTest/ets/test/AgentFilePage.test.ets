// AgentFilePage 智能体文件页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AgentFileViewHelper 视图模型行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 AgentFilePage 导出的 AgentFileViewHelper 静态方法进行验证，
//       覆盖 mimeType 图标映射、mimeType 标签映射、文件大小格式化、时间格式化 4 个方法。
// 视图模型刻意设计为无 UI 依赖的纯函数，返回 emoji/中文标签/已格式化字符串，
// 便于测试与主题切换。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AgentFileViewHelper } from '../../../../main/ets/pages/AgentFilePage';

export default function agentFilePageTest() {
  describe('AgentFilePage', () => {
    // ========== 切片 1: getMimeTypeIcon - image/* → 🖼️ ==========

    it('mime_type_icon_image_returns_picture', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeIcon('image/png')).assertEqual('🖼️');
      expect(AgentFileViewHelper.getMimeTypeIcon('image/jpeg')).assertEqual('🖼️');
    });

    // ========== 切片 2: getMimeTypeIcon - video/* → 🎬 ==========

    it('mime_type_icon_video_returns_film', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeIcon('video/mp4')).assertEqual('🎬');
    });

    // ========== 切片 3: getMimeTypeIcon - audio/* → 🎵 ==========

    it('mime_type_icon_audio_returns_music', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeIcon('audio/mpeg')).assertEqual('🎵');
    });

    // ========== 切片 4: getMimeTypeIcon - application/pdf → 📄；application/zip → 🗜️；text/* → 📝 ==========

    it('mime_type_icon_pdf_zip_text', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeIcon('application/pdf')).assertEqual('📄');
      expect(AgentFileViewHelper.getMimeTypeIcon('application/zip')).assertEqual('🗜️');
      expect(AgentFileViewHelper.getMimeTypeIcon('text/plain')).assertEqual('📝');
    });

    // ========== 切片 5: getMimeTypeIcon - 未知类型 → 📁 ==========

    it('mime_type_icon_unknown_returns_folder', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeIcon('application/octet-stream')).assertEqual('📁');
      expect(AgentFileViewHelper.getMimeTypeIcon('')).assertEqual('📁');
    });

    // ========== 切片 6: getMimeTypeLabel - image/video/audio/pdf/text/zip/其他 ==========

    it('mime_type_label_returns_chinese', 0, () => {
      expect(AgentFileViewHelper.getMimeTypeLabel('image/png')).assertEqual('图片');
      expect(AgentFileViewHelper.getMimeTypeLabel('video/mp4')).assertEqual('视频');
      expect(AgentFileViewHelper.getMimeTypeLabel('audio/mpeg')).assertEqual('音频');
      expect(AgentFileViewHelper.getMimeTypeLabel('application/pdf')).assertEqual('PDF');
      expect(AgentFileViewHelper.getMimeTypeLabel('text/plain')).assertEqual('文本');
      expect(AgentFileViewHelper.getMimeTypeLabel('application/zip')).assertEqual('压缩包');
      expect(AgentFileViewHelper.getMimeTypeLabel('application/octet-stream')).assertEqual('文件');
    });

    // ========== 切片 7: formatFileSize - KB/MB 单位阶梯 ==========

    it('format_file_size_kb_mb', 0, () => {
      // 1024 字节 → "1.0 KB"
      expect(AgentFileViewHelper.formatFileSize(1024)).assertEqual('1.0 KB');
      // 1 MB → "1.0 MB"
      expect(AgentFileViewHelper.formatFileSize(1048576)).assertEqual('1.0 MB');
      // 小于 1 KB → 字节数 + " B"
      expect(AgentFileViewHelper.formatFileSize(512)).assertEqual('512 B');
    });

    // ========== 切片 8: formatFileSize - 0 → "—" ==========

    it('format_file_size_zero_returns_dash', 0, () => {
      expect(AgentFileViewHelper.formatFileSize(0)).assertEqual('—');
    });

    // ========== 切片 9: formatTime - 有效 ISO → "YYYY-MM-DD HH:mm" ==========

    it('format_time_valid_iso', 0, () => {
      // 使用固定时间戳避免时区差异：2024-01-15T10:30:00Z
      const result = AgentFileViewHelper.formatTime('2024-01-15T10:30:00Z');
      // 验证格式正确（长度 16），年份为 2024
      expect(result.length).assertEqual(16);
      expect(result.substring(0, 4)).assertEqual('2024');
      // 包含日期分隔符
      expect(result.substring(4, 5)).assertEqual('-');
      expect(result.substring(10, 11)).assertEqual(' ');
      expect(result.substring(13, 14)).assertEqual(':');
    });

    // ========== 切片 10: formatTime - 空值/无效值 → "未知" ==========

    it('format_time_empty_or_invalid_returns_unknown', 0, () => {
      expect(AgentFileViewHelper.formatTime(undefined)).assertEqual('未知');
      expect(AgentFileViewHelper.formatTime('')).assertEqual('未知');
      expect(AgentFileViewHelper.formatTime('not-a-date')).assertEqual('未知');
    });
  });
}
