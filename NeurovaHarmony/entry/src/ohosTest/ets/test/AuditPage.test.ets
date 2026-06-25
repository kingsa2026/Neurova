// AuditPage 审计日志页单元测试 - TDD 红绿灯垂直切片
//
// 测试范围：AuditViewHelper 视图模型行为（操作类型颜色/图标/标签映射、
//           成功状态颜色、时间戳格式化、元数据 JSON 格式化、资源类型截断）。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对从 AuditPage.ets 导出的 AuditViewHelper 静态方法进行验证。
// 严格规则：一个测试 → 一个实现 → 循环（垂直切片），禁止一次性写完所有测试再写实现。
import { describe, it, expect } from '@ohos/hypium';
import { AuditViewHelper } from '../../../../main/ets/pages/AuditPage';

export default function auditPageTest() {
  describe('AuditPage', () => {
    // ========== 切片1: getActionColor - create → success ==========

    it('action_color_create_returns_success', 0, () => {
      expect(AuditViewHelper.getActionColor('create')).assertEqual('success');
    });

    // ========== 切片2: getActionColor - update → info ==========

    it('action_color_update_returns_info', 0, () => {
      expect(AuditViewHelper.getActionColor('update')).assertEqual('info');
    });

    // ========== 切片3: getActionColor - delete → error ==========

    it('action_color_delete_returns_error', 0, () => {
      expect(AuditViewHelper.getActionColor('delete')).assertEqual('error');
    });

    // ========== 切片4: getActionColor - login → info ==========

    it('action_color_login_returns_info', 0, () => {
      expect(AuditViewHelper.getActionColor('login')).assertEqual('info');
    });

    // ========== 切片5: getActionColor - logout → text_secondary ==========

    it('action_color_logout_returns_text_secondary', 0, () => {
      expect(AuditViewHelper.getActionColor('logout')).assertEqual('text_secondary');
    });

    // ========== 切片6: getActionColor - export → warning ==========

    it('action_color_export_returns_warning', 0, () => {
      expect(AuditViewHelper.getActionColor('export')).assertEqual('warning');
    });

    // ========== 切片7: getActionColor - import → warning ==========

    it('action_color_import_returns_warning', 0, () => {
      expect(AuditViewHelper.getActionColor('import')).assertEqual('warning');
    });

    // ========== 切片8: getActionColor - config_change → warning ==========

    it('action_color_config_change_returns_warning', 0, () => {
      expect(AuditViewHelper.getActionColor('config_change')).assertEqual('warning');
    });

    // ========== 切片9: getActionIcon - create 返回 emoji ==========

    it('action_icon_create_returns_emoji', 0, () => {
      const icon = AuditViewHelper.getActionIcon('create');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片10: getActionIcon - delete 返回 emoji ==========

    it('action_icon_delete_returns_emoji', 0, () => {
      const icon = AuditViewHelper.getActionIcon('delete');
      expect(icon.length > 0).assertTrue();
    });

    // ========== 切片11: getActionLabel - create → 创建 ==========

    it('action_label_create_returns_创建', 0, () => {
      expect(AuditViewHelper.getActionLabel('create')).assertEqual('创建');
    });

    // ========== 切片12: getActionLabel - update → 更新 ==========

    it('action_label_update_returns_更新', 0, () => {
      expect(AuditViewHelper.getActionLabel('update')).assertEqual('更新');
    });

    // ========== 切片13: getActionLabel - delete → 删除 ==========

    it('action_label_delete_returns_删除', 0, () => {
      expect(AuditViewHelper.getActionLabel('delete')).assertEqual('删除');
    });

    // ========== 切片14: getActionLabel - login → 登录 ==========

    it('action_label_login_returns_登录', 0, () => {
      expect(AuditViewHelper.getActionLabel('login')).assertEqual('登录');
    });

    // ========== 切片15: getActionLabel - logout → 登出 ==========

    it('action_label_logout_returns_登出', 0, () => {
      expect(AuditViewHelper.getActionLabel('logout')).assertEqual('登出');
    });

    // ========== 切片16: getActionLabel - export → 导出 ==========

    it('action_label_export_returns_导出', 0, () => {
      expect(AuditViewHelper.getActionLabel('export')).assertEqual('导出');
    });

    // ========== 切片17: getActionLabel - import → 导入 ==========

    it('action_label_import_returns_导入', 0, () => {
      expect(AuditViewHelper.getActionLabel('import')).assertEqual('导入');
    });

    // ========== 切片18: getActionLabel - config_change → 配置变更 ==========

    it('action_label_config_change_returns_配置变更', 0, () => {
      expect(AuditViewHelper.getActionLabel('config_change')).assertEqual('配置变更');
    });

    // ========== 切片19: getSuccessColor - 成功 → success ==========

    it('success_color_true_returns_success', 0, () => {
      expect(AuditViewHelper.getSuccessColor(true)).assertEqual('success');
    });

    // ========== 切片20: getSuccessColor - 失败 → error ==========

    it('success_color_false_returns_error', 0, () => {
      expect(AuditViewHelper.getSuccessColor(false)).assertEqual('error');
    });

    // ========== 切片21: formatTimestamp - 标准 ISO 时间戳 ==========

    it('format_timestamp_valid_iso', 0, () => {
      // 使用 UTC 时间戳：2025-03-01T10:00:00Z
      // 预期格式：YYYY-MM-DD HH:mm:ss（本地时区渲染）
      const result = AuditViewHelper.formatTimestamp('2025-03-01T10:00:00Z');
      const pattern = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;
      expect(pattern.test(result)).assertTrue();
    });

    // ========== 切片22: formatTimestamp - 空值 → '—' ==========

    it('format_timestamp_empty_returns_dash', 0, () => {
      expect(AuditViewHelper.formatTimestamp('')).assertEqual('—');
    });

    // ========== 切片23: formatTimestamp - undefined → '—' ==========

    it('format_timestamp_undefined_returns_dash', 0, () => {
      expect(AuditViewHelper.formatTimestamp(undefined)).assertEqual('—');
    });

    // ========== 切片24: formatMetadata - 空对象 → '—' ==========

    it('format_metadata_empty_returns_dash', 0, () => {
      expect(AuditViewHelper.formatMetadata({})).assertEqual('—');
    });

    // ========== 切片25: formatMetadata - undefined → '—' ==========

    it('format_metadata_undefined_returns_dash', 0, () => {
      expect(AuditViewHelper.formatMetadata(undefined)).assertEqual('—');
    });

    // ========== 切片26: formatMetadata - 非空 → JSON 字符串 ==========

    it('format_metadata_with_data_returns_json', 0, () => {
      const meta = { key: 'value', count: 42 };
      const result = AuditViewHelper.formatMetadata(meta);
      expect(result).assertEqual(JSON.stringify(meta));
    });

    // ========== 切片27: truncateResource - 短资源原样返回 ==========

    it('truncate_resource_short_keeps_original', 0, () => {
      const result = AuditViewHelper.truncateResource('user', 20);
      expect(result).assertEqual('user');
    });

    // ========== 切片28: truncateResource - 超长截断 + '...' ==========

    it('truncate_resource_long_truncates_with_ellipsis', 0, () => {
      const long = 'a'.repeat(50);
      const result = AuditViewHelper.truncateResource(long, 10);
      expect(result.length).assertEqual(13);
      expect(result.substring(10)).assertEqual('...');
    });

    // ========== 切片29: truncateResource - 默认 maxLen ==========

    it('truncate_resource_default_maxLen', 0, () => {
      const long = 'b'.repeat(120);
      const result = AuditViewHelper.truncateResource(long);
      expect(result.length).assertEqual(103);
      expect(result.substring(100)).assertEqual('...');
    });
  });
}
