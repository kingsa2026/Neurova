// FilePage 文件管理页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：FileViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 FilePage 导出的 FileViewHelper 静态方法进行验证，
//       覆盖页面 getFileTypeIcon / getFileTypeColor / formatFileSize /
//       formatModifiedAt / buildPath / truncateFileName 的核心视图逻辑。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'primary'/'text_secondary'），
//   不加前缀，与 TaskPage/ProjectPage 现有模式一致。
import { describe, it, expect } from '@ohos/hypium';
import { FileViewHelper } from '../../../../main/ets/pages/FilePage';
import { FileItem, FileItemType } from '../../../../main/ets/libs/types';

export default function filePageTest() {
  describe('FilePage', () => {
    // ========== 切片1: getFileTypeIcon - folder → 📁 ==========

    it('file_type_icon_folder_returns_folder_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('folder' as FileItemType)).assertEqual('📁');
    });

    // ========== 切片2: getFileTypeIcon - file 无 mimeType → 📄 ==========

    it('file_type_icon_file_no_mime_returns_doc_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('file' as FileItemType)).assertEqual('📄');
    });

    // ========== 切片3: getFileTypeIcon - file image/* → 🖼️ ==========

    it('file_type_icon_file_image_returns_image_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('file' as FileItemType, 'image/png')).assertEqual('🖼️');
    });

    // ========== 切片4: getFileTypeIcon - file audio/* → 🎵 ==========

    it('file_type_icon_file_audio_returns_music_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('file' as FileItemType, 'audio/mp3')).assertEqual('🎵');
    });

    // ========== 切片5: getFileTypeIcon - file video/* → 🎬 ==========

    it('file_type_icon_file_video_returns_film_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('file' as FileItemType, 'video/mp4')).assertEqual('🎬');
    });

    // ========== 切片6: getFileTypeIcon - file 其他 mimeType → 📄 ==========

    it('file_type_icon_file_other_mime_returns_doc_emoji', 0, () => {
      expect(FileViewHelper.getFileTypeIcon('file' as FileItemType, 'application/pdf')).assertEqual('📄');
    });

    // ========== 切片7: getFileTypeColor - folder → primary ==========

    it('file_type_color_folder_returns_primary', 0, () => {
      expect(FileViewHelper.getFileTypeColor('folder' as FileItemType)).assertEqual('primary');
    });

    // ========== 切片8: getFileTypeColor - file → text_secondary ==========

    it('file_type_color_file_returns_text_secondary', 0, () => {
      expect(FileViewHelper.getFileTypeColor('file' as FileItemType)).assertEqual('text_secondary');
    });

    // ========== 切片9: formatFileSize - 0 B ==========

    it('format_file_size_zero_returns_zero_b', 0, () => {
      expect(FileViewHelper.formatFileSize(0)).assertEqual('0 B');
    });

    // ========== 切片10: formatFileSize - 小于 1KB 显示 B ==========

    it('format_file_size_under_kb_returns_bytes', 0, () => {
      expect(FileViewHelper.formatFileSize(512)).assertEqual('512.0 B');
    });

    // ========== 切片11: formatFileSize - 1KB 边界 ==========

    it('format_file_size_one_kb_boundary', 0, () => {
      expect(FileViewHelper.formatFileSize(1024)).assertEqual('1.0 KB');
    });

    // ========== 切片12: formatFileSize - KB 范围 ==========

    it('format_file_size_kb_range', 0, () => {
      expect(FileViewHelper.formatFileSize(1536)).assertEqual('1.5 KB');
    });

    // ========== 切片13: formatFileSize - MB 范围 ==========

    it('format_file_size_mb_range', 0, () => {
      expect(FileViewHelper.formatFileSize(1048576)).assertEqual('1.0 MB');
    });

    // ========== 切片14: formatFileSize - GB 范围 ==========

    it('format_file_size_gb_range', 0, () => {
      expect(FileViewHelper.formatFileSize(1073741824)).assertEqual('1.0 GB');
    });

    // ========== 切片15: formatModifiedAt - ISO → YYYY-MM-DD HH:mm ==========

    it('format_modified_at_iso_returns_yyyy_mm_dd_hh_mm', 0, () => {
      // 2024-06-15T08:30:45Z → 长度 16，前缀匹配 'YYYY-MM-DD HH:mm'
      const result = FileViewHelper.formatModifiedAt('2024-06-15T08:30:45Z');
      expect(result.length).assertEqual(16);
      expect(result.indexOf('2024-06-15')).assertEqual(0);
      expect(result.charAt(10)).assertEqual(' ');
      expect(result.charAt(13)).assertEqual(':');
    });

    // ========== 切片16: formatModifiedAt - undefined → '-' ==========

    it('format_modified_at_undefined_returns_dash', 0, () => {
      expect(FileViewHelper.formatModifiedAt(undefined)).assertEqual('-');
    });

    // ========== 切片17: formatModifiedAt - 空字符串 → '-' ==========

    it('format_modified_at_empty_returns_dash', 0, () => {
      expect(FileViewHelper.formatModifiedAt('')).assertEqual('-');
    });

    // ========== 切片18: formatModifiedAt - 无效日期 → '-' ==========

    it('format_modified_at_invalid_returns_dash', 0, () => {
      expect(FileViewHelper.formatModifiedAt('invalid-date')).assertEqual('-');
    });

    // ========== 切片19: buildPath - undefined parentId → ['根目录'] ==========

    it('build_path_root_returns_root_array', 0, () => {
      const files: FileItem[] = [];
      const result = FileViewHelper.buildPath(undefined, files);
      expect(result.length).assertEqual(1);
      expect(result[0]).assertEqual('根目录');
    });

    // ========== 切片20: buildPath - 有父子层级 → ['根目录', '父文件夹'] ==========

    it('build_path_with_parent_returns_full_path', 0, () => {
      const files: FileItem[] = [
        {
          id: 'root',
          name: '根目录',
          type: 'folder' as FileItemType,
          path: '/',
          size: 0,
          modifiedAt: '2024-06-15T08:30:45Z',
        },
        {
          id: 'parent',
          name: '父文件夹',
          type: 'folder' as FileItemType,
          path: '/parent',
          size: 0,
          parentId: 'root',
          modifiedAt: '2024-06-15T08:30:45Z',
        },
        {
          id: 'child',
          name: '子文件',
          type: 'file' as FileItemType,
          path: '/parent/child.txt',
          size: 100,
          parentId: 'parent',
          modifiedAt: '2024-06-15T08:30:45Z',
        },
      ];
      // 从 child（parentId='parent'）回溯：根目录 → 父文件夹
      const result = FileViewHelper.buildPath('parent', files);
      expect(result.length).assertEqual(2);
      expect(result[0]).assertEqual('根目录');
      expect(result[1]).assertEqual('父文件夹');
    });

    // ========== 切片21: buildPath - parentId 不存在 → ['根目录'] ==========

    it('build_path_orphan_parent_returns_root_only', 0, () => {
      const files: FileItem[] = [];
      const result = FileViewHelper.buildPath('nonexistent', files);
      expect(result.length).assertEqual(1);
      expect(result[0]).assertEqual('根目录');
    });

    // ========== 切片22: truncateFileName - 未超长原样返回 ==========

    it('truncate_file_name_under_max_returns_original', 0, () => {
      const name = 'document.pdf';
      expect(FileViewHelper.truncateFileName(name, 100)).assertEqual(name);
    });

    // ========== 切片23: truncateFileName - 超长截断加省略号 ==========

    it('truncate_file_name_over_max_returns_ellipsis', 0, () => {
      const long = 'a'.repeat(60) + '.txt';
      const result = FileViewHelper.truncateFileName(long, 30);
      expect(result.length).assertEqual(33);
      expect(result.substring(30)).assertEqual('...');
    });

    // ========== 切片24: truncateFileName - 默认 maxLen（100） ==========

    it('truncate_file_name_default_max_len', 0, () => {
      const long = 'b'.repeat(120) + '.pdf';
      const result = FileViewHelper.truncateFileName(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });
  });
}
