// AuditPage 审计日志页单元测试 - R6 契约切换
//
// 测试范围：AuditViewHelper 视图模型行为（事件类颜色/图标/标签按 id 前缀的
//           开放集合映射、筛选匹配、时间戳格式化、details JSON 格式化、资源截断）。
// 契约：后端 action 是自由文本、event_type 随条目 id 前缀下发（"{event_type}_{ms}"）；
//       映射一律开放集合 + 未知兜默认，不抛错。
import { describe, it, expect } from '@ohos/hypium';
import { AuditViewHelper } from '../../../main/ets/pages/AuditPage';

export default function auditPageTest() {
  describe('AuditPage', () => {
    // ========== 切片1: getEventColor - 已知事件类 ==========

    it('event_color_auth_login_returns_success', 0, () => {
      expect(AuditViewHelper.getEventColor('auth_login_1700000000000')).assertEqual('success');
    });

    it('event_color_auth_failed_returns_error', 0, () => {
      expect(AuditViewHelper.getEventColor('auth_failed_1700000000000')).assertEqual('error');
    });

    it('event_color_config_change_returns_warning', 0, () => {
      expect(AuditViewHelper.getEventColor('config_change_1700000000000')).assertEqual('warning');
    });

    it('event_color_security_event_returns_error', 0, () => {
      expect(AuditViewHelper.getEventColor('security_event_1700000000000')).assertEqual('error');
    });

    // ========== 切片2: getEventColor - 未知事件类兜 'info'（开放集合不抛错） ==========

    it('event_color_unknown_defaults_to_info', 0, () => {
      expect(AuditViewHelper.getEventColor('future_event_1')).assertEqual('info');
      expect(AuditViewHelper.getEventColor('')).assertEqual('info');
    });

    // ========== 切片3: getEventIcon / getEventLabel ==========

    it('event_icon_auth_login_returns_key', 0, () => {
      expect(AuditViewHelper.getEventIcon('auth_login_1700000000000')).assertEqual('🔑');
    });

    it('event_label_auth_failed', 0, () => {
      expect(AuditViewHelper.getEventLabel('auth_failed_1700000000000')).assertEqual('认证失败');
    });

    it('event_label_unknown_defaults', 0, () => {
      expect(AuditViewHelper.getEventLabel('future_event_1')).assertEqual('系统事件');
    });

    // ========== 切片4: matchesEventFilter - 按 id 前缀匹配 ==========

    it('filter_all_matches_everything', 0, () => {
      expect(AuditViewHelper.matchesEventFilter('auth_login_1', 'all')).assertTrue();
      expect(AuditViewHelper.matchesEventFilter('config_change_1', 'all')).assertTrue();
    });

    it('filter_by_prefix_matches_only_same_prefix', 0, () => {
      expect(AuditViewHelper.matchesEventFilter('auth_login_1700', 'auth_login')).assertTrue();
      expect(AuditViewHelper.matchesEventFilter('auth_logout_1700', 'auth_login')).assertFalse();
    });

    // ========== 切片5: formatTimestamp ==========

    it('format_timestamp_valid_iso', 0, () => {
      const formatted = AuditViewHelper.formatTimestamp('2025-03-01T09:00:00Z');
      // 时区无关：合法 ISO 必产出 19 位 YYYY-MM-DD HH:mm:ss（日期随设备时区，不锁字面值）
      expect(formatted.length === 19).assertTrue();
      expect(formatted.charAt(4)).assertEqual('-');
      expect(formatted.charAt(10)).assertEqual(' ');
      expect(formatted.charAt(13)).assertEqual(':');
    });

    it('format_timestamp_invalid_returns_dash', 0, () => {
      expect(AuditViewHelper.formatTimestamp('')).assertEqual('—');
      expect(AuditViewHelper.formatTimestamp('not-a-date')).assertEqual('—');
    });

    // ========== 切片6: formatDetails ==========

    it('format_details_null_returns_dash', 0, () => {
      expect(AuditViewHelper.formatDetails(null)).assertEqual('—');
    });

    it('format_details_empty_returns_dash', 0, () => {
      expect(AuditViewHelper.formatDetails({})).assertEqual('—');
    });

    it('format_details_object_returns_json', 0, () => {
      const details: Record<string, Object> = { 'target': 'agent_1' };
      expect(AuditViewHelper.formatDetails(details)).assertEqual('{"target":"agent_1"}');
    });

    // ========== 切片7: truncateResource ==========

    it('truncate_resource_short_returns_raw', 0, () => {
      expect(AuditViewHelper.truncateResource('agent', 100)).assertEqual('agent');
    });

    it('truncate_resource_long_appends_ellipsis', 0, () => {
      const long = 'r'.repeat(120);
      expect(AuditViewHelper.truncateResource(long, 100)).assertEqual('r'.repeat(100) + '...');
    });
  });
}
