// KnowledgePage 知识库页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：KnowledgeViewHelper 视图模型纯函数行为契约。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对 KnowledgePage 导出的 KnowledgeViewHelper 视图模型层
//       （状态颜色映射 / 来源图标映射 / 文件大小格式化）进行验证，
//       覆盖页面渲染所需的全部纯函数。视图模型刻意设计为无 UI 依赖的纯函数，
//       返回颜色 token 名（如 'success'）而非已解析颜色值，便于测试与主题切换。
import { describe, it, expect } from '@ohos/hypium';
import { KnowledgeViewHelper } from '../../../../main/ets/pages/KnowledgePage';
import { KnowledgeStatus } from '../../../../main/ets/libs/types';

export default function knowledgePageTest() {
  describe('KnowledgePage', () => {
    // ========== 切片 1: status_color_ready_returns_success ==========

    it('status_color_ready_returns_success', 0, () => {
      const token = KnowledgeViewHelper.getStatusColor('ready' as KnowledgeStatus);
      expect(token).assertEqual('success');
    });

    // ========== 切片 2: status_color_indexing_returns_info ==========

    it('status_color_indexing_returns_info', 0, () => {
      const token = KnowledgeViewHelper.getStatusColor('indexing' as KnowledgeStatus);
      expect(token).assertEqual('info');
    });

    // ========== 切片 3: status_color_error_returns_error ==========

    it('status_color_error_returns_error', 0, () => {
      const token = KnowledgeViewHelper.getStatusColor('error' as KnowledgeStatus);
      expect(token).assertEqual('error');
    });

    // ========== 切片 4: status_color_pending_returns_warning ==========

    it('status_color_pending_returns_warning', 0, () => {
      const token = KnowledgeViewHelper.getStatusColor('pending' as KnowledgeStatus);
      expect(token).assertEqual('warning');
    });

    // ========== 切片 5: status_color_unknown_returns_default ==========

    it('status_color_unknown_returns_default', 0, () => {
      // 未知状态值应回退到默认 text_disabled token
      const token = KnowledgeViewHelper.getStatusColor('unknown' as KnowledgeStatus);
      expect(token).assertEqual('text_disabled');
    });

    // ========== 切片 6: source_icon_upload_returns_camera ==========

    it('source_icon_upload_returns_camera', 0, () => {
      const icon = KnowledgeViewHelper.getSourceIcon('upload');
      expect(icon).assertEqual('📷');
    });

    // ========== 切片 7: source_icon_url_returns_link ==========

    it('source_icon_url_returns_link', 0, () => {
      const icon = KnowledgeViewHelper.getSourceIcon('url');
      expect(icon).assertEqual('🔗');
    });

    // ========== 切片 8: source_icon_manual_returns_pen ==========

    it('source_icon_manual_returns_pen', 0, () => {
      const icon = KnowledgeViewHelper.getSourceIcon('manual');
      expect(icon).assertEqual('✍️');
    });

    // ========== 切片 9: source_icon_unknown_returns_default ==========

    it('source_icon_unknown_returns_default', 0, () => {
      // 未知来源应回退到默认 📄 图标
      const icon = KnowledgeViewHelper.getSourceIcon('unknown_source');
      expect(icon).assertEqual('📄');
    });

    // ========== 切片 10: format_file_size_bytes_to_human ==========

    it('format_file_size_bytes_to_human', 0, () => {
      // 1024 字节 → "1.0 KB"
      expect(KnowledgeViewHelper.formatFileSize(1024)).assertEqual('1.0 KB');
      // 1048576 字节（1 MB）→ "1.0 MB"
      expect(KnowledgeViewHelper.formatFileSize(1048576)).assertEqual('1.0 MB');
    });

    // ========== 切片 11: format_file_size_zero_returns_empty ==========

    it('format_file_size_zero_returns_empty', 0, () => {
      // 0 字节 → 占位符 "—"
      expect(KnowledgeViewHelper.formatFileSize(0)).assertEqual('—');
      // undefined（未提供 fileSize）→ 占位符 "—"
      expect(KnowledgeViewHelper.formatFileSize(undefined)).assertEqual('—');
    });
  });
}
