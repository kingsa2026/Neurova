// MessageManager 单元测试 - TDD 垂直切片
// 每个测试验证一个行为，仅通过公共接口验证，不耦合实现细节
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { MessageManager, MessageType } from '../../../../main/ets/libs/message/MessageManager';

export default function messageManagerTest() {
  describe('MessageManager', () => {
    let mm: MessageManager;

    beforeEach(() => {
      mm = MessageManager.getInstance();
      mm.clearHistory();
      mm.setHandler(undefined); // 清空 handler，回退到 EventBus
    });

    // ========== Tracer Bullet: 单例 ==========

    it('getInstance_returns_singleton', 0, () => {
      expect(MessageManager.getInstance()).assertEqual(MessageManager.getInstance());
    });

    // ========== 行为 1: toast 写入历史 ==========

    it('toast_adds_message_to_history', 0, () => {
      mm.toast('hello');
      const history = mm.getHistory();
      expect(history.length).assertEqual(1);
      expect(history[0].text).assertEqual('hello');
    });

    // ========== 行为 2: toast 默认 duration 为 2000 ==========

    it('toast_default_duration_is_2000', 0, () => {
      mm.toast('default');
      const history = mm.getHistory();
      expect(history[0].duration).assertEqual(2000);
    });

    // ========== 行为 3: toast 自定义 duration ==========

    it('toast_custom_duration_takes_effect', 0, () => {
      mm.toast('custom', 5000);
      const history = mm.getHistory();
      expect(history[0].duration).assertEqual(5000);
    });

    // ========== 行为 4: 各类型消息 ==========

    it('success_sets_type_to_success', 0, () => {
      mm.success('done');
      const history = mm.getHistory();
      expect(history[0].type).assertEqual(MessageType.SUCCESS);
    });

    it('error_sets_type_to_error', 0, () => {
      mm.error('failed');
      const history = mm.getHistory();
      expect(history[0].type).assertEqual(MessageType.ERROR);
    });

    it('warning_sets_type_to_warning', 0, () => {
      mm.warning('careful');
      const history = mm.getHistory();
      expect(history[0].type).assertEqual(MessageType.WARNING);
    });

    it('info_sets_type_to_info', 0, () => {
      mm.info('notice');
      const history = mm.getHistory();
      expect(history[0].type).assertEqual(MessageType.INFO);
    });

    // ========== 行为 5: setHandler 注入自定义分发 ==========

    it('setHandler_invoked_on_toast', 0, () => {
      let receivedText: string = '';
      let receivedType: MessageType = MessageType.INFO;
      mm.setHandler((msg) => {
        receivedText = msg.text;
        receivedType = msg.type;
      });
      mm.toast('via-handler');
      expect(receivedText).assertEqual('via-handler');
      expect(receivedType).assertEqual(MessageType.INFO);
    });

    // ========== 行为 6: clearHistory 清空历史 ==========

    it('clearHistory_empties_history', 0, () => {
      mm.toast('one');
      mm.toast('two');
      mm.clearHistory();
      expect(mm.getHistory().length).assertEqual(0);
    });

    // ========== 行为 7: getHistory 返回副本 ==========

    it('getHistory_returns_copy', 0, () => {
      mm.toast('original');
      const snapshot = mm.getHistory();
      // 修改返回的副本，不应影响内部历史
      snapshot.push({
        id: 'injected',
        type: MessageType.ERROR,
        text: 'injected',
        duration: 0,
        createdAt: 0,
      });
      expect(mm.getHistory().length).assertEqual(1);
    });
  });
}
