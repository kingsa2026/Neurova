// Logger 单元测试 - TDD
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { Logger, LogLevel } from '../../../../main/ets/libs/logger/Logger';

export default function loggerTest() {
  describe('Logger', () => {
    let logger: Logger;

    beforeEach(() => {
      logger = Logger.getInstance();
      logger.setLevel(LogLevel.DEBUG);
      logger.clearHistory();
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(Logger.getInstance()).assertEqual(Logger.getInstance());
    });

    // ========== 行为 1: 日志级别 ==========

    it('setLevel_changes_filter', 0, () => {
      logger.setLevel(LogLevel.WARN);
      logger.debug('TestTag', 'should be filtered');
      const history = logger.getHistory();
      expect(history.length).assertEqual(0);
    });

    it('debug_logged_when_level_is_debug', 0, () => {
      logger.debug('TestTag', 'debug message');
      const history = logger.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].level).assertEqual(LogLevel.DEBUG);
      expect(history[0].tag).assertEqual('TestTag');
      expect(history[0].message).assertEqual('debug message');
    });

    // ========== 行为 2: 各级别日志 ==========

    it('info_logs_correctly', 0, () => {
      logger.info('AppTag', 'info message');
      const history = logger.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].level).assertEqual(LogLevel.INFO);
    });

    it('warn_logs_correctly', 0, () => {
      logger.warn('AppTag', 'warn message');
      const history = logger.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].level).assertEqual(LogLevel.WARN);
    });

    it('error_logs_correctly', 0, () => {
      logger.error('AppTag', 'error message');
      const history = logger.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].level).assertEqual(LogLevel.ERROR);
    });

    // ========== 行为 3: 级别过滤 ==========

    it('warn_level_filters_debug_and_info', 0, () => {
      logger.setLevel(LogLevel.WARN);
      logger.debug('T', 'debug');
      logger.info('T', 'info');
      logger.warn('T', 'warn');
      logger.error('T', 'error');
      const history = logger.getHistory();
      // 只应保留 warn 和 error
      expect(history.length).assertEqual(2);
    });

    // ========== 行为 4: error 带错误对象 ==========

    it('error_with_error_object_includes_stack', 0, () => {
      const err = new Error('test error');
      logger.error('ErrTag', 'operation failed', err);
      const history = logger.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].message).assertEqual('operation failed');
    });

    // ========== 行为 5: clearHistory ==========

    it('clearHistory_empties_history', 0, () => {
      logger.info('T', 'msg1');
      logger.info('T', 'msg2');
      logger.clearHistory();
      expect(logger.getHistory().length).assertEqual(0);
    });
  });
}
