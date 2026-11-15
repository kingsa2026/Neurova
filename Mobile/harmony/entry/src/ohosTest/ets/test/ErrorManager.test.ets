// ErrorManager 单元测试 - TDD 垂直切片
// 每个测试验证一个行为，通过公共接口验证
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { ErrorManager, AppError, ErrorCategory } from '../../../../main/ets/libs/error/ErrorManager';

export default function errorManagerTest() {
  describe('ErrorManager', () => {
    let em: ErrorManager;

    beforeEach(() => {
      em = ErrorManager.getInstance();
      em.clearHistory();
      em.clearHandlers();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(ErrorManager.getInstance()).assertEqual(ErrorManager.getInstance());
    });

    // ========== 行为 1: create 创建 AppError ==========

    it('create_returns_apperror_with_code_message_category', 0, () => {
      const err = em.create('auth_failed', '认证失败', ErrorCategory.AUTH);
      expect(err.code).assertEqual('auth_failed');
      expect(err.message).assertEqual('认证失败');
      expect(err.category).assertEqual(ErrorCategory.AUTH);
      expect(err.timestamp > 0).assertTrue();
    });

    it('create_defaults_to_unknown_category', 0, () => {
      const err = em.create('some_error', '某错误');
      expect(err.category).assertEqual(ErrorCategory.UNKNOWN);
    });

    it('create_preserves_details', 0, () => {
      const err = em.create('api_error', 'API错误', ErrorCategory.API, { status: 500 });
      expect(err.details).assertEqual({ status: 500 });
    });

    // ========== 行为 2: report 记录到历史 ==========

    it('report_adds_error_to_history', 0, () => {
      const err = em.create('test_error', '测试错误');
      em.report(err);
      const history = em.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].code).assertEqual('test_error');
    });

    it('report_invokes_registered_handler', 0, () => {
      let handled: AppError | null = null;
      em.registerHandler('auth_failed', (e) => { handled = e; });
      const err = em.create('auth_failed', '认证失败', ErrorCategory.AUTH);
      em.report(err);
      expect(handled).assertEqual(err);
    });

    it('report_does_not_invoke_handler_for_different_code', 0, () => {
      let called = false;
      em.registerHandler('auth_failed', () => { called = true; });
      const err = em.create('other_error', '其他错误');
      em.report(err);
      expect(called).assertFalse();
    });

    // ========== 行为 3: history 容量限制 ==========

    it('history_caps_at_max_size', 0, () => {
      // 默认 maxHistory=100，超出后丢弃最旧的
      for (let i = 0; i < 105; i++) {
        em.report(em.create(`err_${i}`, `错误${i}`));
      }
      const history = em.getHistory();
      expect(history.length).assertEqual(100);
      // 最旧的应被丢弃，最新的保留
      expect(history[0].code).assertEqual('err_5');
      expect(history[99].code).assertEqual('err_104');
    });

    // ========== 行为 4: clearHistory ==========

    it('clearHistory_empties_history', 0, () => {
      em.report(em.create('err1', '错误1'));
      em.report(em.create('err2', '错误2'));
      em.clearHistory();
      expect(em.getHistory().length).assertEqual(0);
    });

    // ========== 行为 5: registerHandler / unregisterHandler ==========

    it('unregisterHandler_removes_handler', 0, () => {
      let called = false;
      em.registerHandler('auth_failed', () => { called = true; });
      em.unregisterHandler('auth_failed');
      em.report(em.create('auth_failed', '认证失败', ErrorCategory.AUTH));
      expect(called).assertFalse();
    });

    it('clearHandlers_removes_all_handlers', 0, () => {
      let called1 = false;
      let called2 = false;
      em.registerHandler('err_a', () => { called1 = true; });
      em.registerHandler('err_b', () => { called2 = true; });
      em.clearHandlers();
      em.report(em.create('err_a', 'A'));
      em.report(em.create('err_b', 'B'));
      expect(called1).assertFalse();
      expect(called2).assertFalse();
    });

    // ========== 行为 6: fromHttpStatus 映射 ==========

    it('fromHttpStatus_401_maps_to_auth', 0, () => {
      const err = em.fromHttpStatus(401, '未授权');
      expect(err.category).assertEqual(ErrorCategory.AUTH);
      expect(err.code).assertEqual('http_401');
    });

    it('fromHttpStatus_403_maps_to_auth', 0, () => {
      const err = em.fromHttpStatus(403);
      expect(err.category).assertEqual(ErrorCategory.AUTH);
    });

    it('fromHttpStatus_404_maps_to_api', 0, () => {
      const err = em.fromHttpStatus(404);
      expect(err.category).assertEqual(ErrorCategory.API);
    });

    it('fromHttpStatus_500_maps_to_api', 0, () => {
      const err = em.fromHttpStatus(500);
      expect(err.category).assertEqual(ErrorCategory.API);
    });

    it('fromHttpStatus_0_maps_to_network', 0, () => {
      const err = em.fromHttpStatus(0, '网络错误');
      expect(err.category).assertEqual(ErrorCategory.NETWORK);
    });

    // ========== 行为 7: fromError 转换原生 Error ==========

    it('fromError_converts_native_error', 0, () => {
      const native = new Error('原生错误');
      const appErr = em.fromError(native, ErrorCategory.STORAGE);
      expect(appErr.message).assertEqual('原生错误');
      expect(appErr.category).assertEqual(ErrorCategory.STORAGE);
      expect(appErr.code).assertEqual('native_error');
    });

    it('fromError_defaults_to_unknown_category', 0, () => {
      const native = new Error('某错误');
      const appErr = em.fromError(native);
      expect(appErr.category).assertEqual(ErrorCategory.UNKNOWN);
    });

    // ========== 行为 8: 便捷方法 reportError ==========

    it('reportError_creates_and_reports_in_one_call', 0, () => {
      em.reportError('quick_err', '快速错误', ErrorCategory.UI);
      const history = em.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].code).assertEqual('quick_err');
      expect(history[0].category).assertEqual(ErrorCategory.UI);
    });
  });
}
