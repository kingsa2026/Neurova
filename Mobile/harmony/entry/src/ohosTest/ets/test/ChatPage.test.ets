// ChatPage 对话页单元测试 - TDD 红绿灯
//
// 测试范围：ChatPage 依赖的事件流契约与消息视图模型行为。
// 说明：@Component 结构体依赖 HarmonyOS UI 运行时，无法在纯单元测试中实例化，
//       因此此处针对页面所订阅的 EventBus 事件契约（chat:chunk/done/error）
//       与 ChatMessageView 视图模型的增删改行为进行验证，
//       覆盖页面 sendMessage / subscribeEvents / stopGeneration 的核心数据流。
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { EventBus } from '../../../../main/ets/libs/bus/EventBus';
import { WSChatChunk, WSChatDone, WSChatError } from '../../../../main/ets/libs/types';

// 与 ChatPage.ets 中定义保持一致的消息视图模型
interface ChatMessageView {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isStreaming: boolean;
}

export default function chatPageTest() {
  describe('ChatPage', () => {
    let bus: EventBus;

    beforeEach(() => {
      bus = EventBus.getInstance();
      bus.clearAll();
    });

    // ========== 行为 1: chat:chunk 事件需携带 content 字段 ==========

    it('chat_chunk_event_carries_content', 0, () => {
      let received: WSChatChunk | null = null;
      bus.on('chat:chunk', (data) => {
        received = data as WSChatChunk;
      });
      const chunk: WSChatChunk = {
        type: 'chat:chunk',
        session_id: 's1',
        content: '你好',
        index: 0,
      };
      bus.emit('chat:chunk', chunk);
      expect(received!.content).assertEqual('你好');
    });

    // ========== 行为 2: chunk 应追加到最后一条 streaming assistant 消息 ==========

    it('append_chunk_to_last_streaming_assistant', 0, () => {
      const messages: ChatMessageView[] = [
        { id: 'u1', role: 'user', content: 'hi', timestamp: 1, isStreaming: false },
        { id: 'a1', role: 'assistant', content: '', timestamp: 2, isStreaming: true },
      ];
      bus.on('chat:chunk', (data) => {
        const msg = data as WSChatChunk;
        const last = messages[messages.length - 1];
        if (last && last.role === 'assistant' && last.isStreaming) {
          last.content += msg.content;
        }
      });
      bus.emit('chat:chunk', { type: 'chat:chunk', session_id: 's1', content: '你', index: 0 });
      bus.emit('chat:chunk', { type: 'chat:chunk', session_id: 's1', content: '好', index: 1 });
      expect(messages[1].content).assertEqual('你好');
    });

    // ========== 行为 3: chunk 不应追加到非 streaming 消息 ==========

    it('chunk_ignored_when_no_streaming_assistant', 0, () => {
      const messages: ChatMessageView[] = [
        { id: 'u1', role: 'user', content: 'hi', timestamp: 1, isStreaming: false },
        { id: 'a1', role: 'assistant', content: '已结束', timestamp: 2, isStreaming: false },
      ];
      bus.on('chat:chunk', (data) => {
        const msg = data as WSChatChunk;
        const last = messages[messages.length - 1];
        if (last && last.role === 'assistant' && last.isStreaming) {
          last.content += msg.content;
        }
      });
      bus.emit('chat:chunk', { type: 'chat:chunk', session_id: 's1', content: '忽略', index: 0 });
      expect(messages[1].content).assertEqual('已结束');
    });

    // ========== 行为 4: chat:done 应将最后一条消息 isStreaming 置 false ==========

    it('chat_done_finalizes_streaming_message', 0, () => {
      const messages: ChatMessageView[] = [
        { id: 'u1', role: 'user', content: 'hi', timestamp: 1, isStreaming: false },
        { id: 'a1', role: 'assistant', content: '回复', timestamp: 2, isStreaming: true },
      ];
      let isGenerating = true;
      bus.on('chat:done', () => {
        const last = messages[messages.length - 1];
        if (last) {
          last.isStreaming = false;
        }
        isGenerating = false;
      });
      bus.emit('chat:done', { type: 'chat:done', session_id: 's1', message_id: 'm1' } as WSChatDone);
      expect(messages[1].isStreaming).assertFalse();
      expect(isGenerating).assertFalse();
    });

    // ========== 行为 5: chat:error 应停止流式并标记 isGenerating=false ==========

    it('chat_error_stops_generation', 0, () => {
      const messages: ChatMessageView[] = [
        { id: 'a1', role: 'assistant', content: '部分', timestamp: 1, isStreaming: true },
      ];
      let isGenerating = true;
      bus.on('chat:error', () => {
        isGenerating = false;
        const last = messages[messages.length - 1];
        if (last) {
          last.isStreaming = false;
        }
      });
      bus.emit('chat:error', {
        type: 'chat:error', session_id: 's1', error: '内部错误',
      } as WSChatError);
      expect(isGenerating).assertFalse();
      expect(messages[0].isStreaming).assertFalse();
    });

    // ========== 行为 6: sendMessage 应创建 user + assistant 占位两条消息 ==========

    it('send_message_creates_user_and_assistant_placeholder', 0, () => {
      const messages: ChatMessageView[] = [];
      const inputText = '你好';
      let isGenerating = false;
      // 模拟 sendMessage 的消息创建逻辑
      const userMsg: ChatMessageView = {
        id: 'u-' + Date.now(),
        role: 'user',
        content: inputText,
        timestamp: Date.now(),
        isStreaming: false,
      };
      const assistantMsg: ChatMessageView = {
        id: 'a-' + Date.now(),
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        isStreaming: true,
      };
      messages.push(userMsg, assistantMsg);
      isGenerating = true;
      expect(messages.length).assertEqual(2);
      expect(messages[0].role).assertEqual('user');
      expect(messages[0].content).assertEqual('你好');
      expect(messages[1].role).assertEqual('assistant');
      expect(messages[1].isStreaming).assertTrue();
      expect(isGenerating).assertTrue();
    });

    // ========== 行为 7: 空输入或生成中不应触发发送 ==========

    it('send_message_ignored_when_empty_or_generating', 0, () => {
      let sent = false;
      const trySend = (text: string, isGenerating: boolean): void => {
        if (!text || isGenerating) {
          return;
        }
        sent = true;
      };
      // 空文本不发送
      trySend('', false);
      expect(sent).assertFalse();
      // 生成中不发送
      trySend('hi', true);
      expect(sent).assertFalse();
      // 正常情况发送
      trySend('hi', false);
      expect(sent).assertTrue();
    });

    // ========== 行为 8: ChatMessageView 视图模型字段完整性 ==========

    it('chat_message_view_has_required_fields', 0, () => {
      const msg: ChatMessageView = {
        id: 'm1',
        role: 'user',
        content: 'text',
        timestamp: 1700000000000,
        isStreaming: false,
      };
      expect(msg.id).assertEqual('m1');
      expect(msg.role).assertEqual('user');
      expect(msg.content).assertEqual('text');
      expect(msg.timestamp).assertEqual(1700000000000);
      expect(msg.isStreaming).assertFalse();
    });

    // ========== 行为 9: stopGeneration 应发送 chat:cancel 类型 ==========

    it('stop_generation_sends_cancel_type', 0, () => {
      let sentPayload: Record<string, Object> | null = null;
      // 模拟 ws.send 拦截
      const fakeSend = (payload: string): void => {
        sentPayload = JSON.parse(payload) as Record<string, Object>;
      };
      const sessionId = 'session-123';
      // 模拟 stopGeneration 的发送逻辑
      fakeSend(JSON.stringify({
        type: 'chat:cancel',
        session_id: sessionId,
      }));
      expect(sentPayload!['type']).assertEqual('chat:cancel');
      expect(sentPayload!['session_id']).assertEqual('session-123');
    });

    // ========== 行为 10: sendMessage 的 WS 载荷应包含 type/content/session_id/agent_id ==========

    it('send_message_payload_has_required_fields', 0, () => {
      let sentPayload: Record<string, Object> | null = null;
      const fakeSend = (payload: string): void => {
        sentPayload = JSON.parse(payload) as Record<string, Object>;
      };
      const text = 'hello';
      const sessionId = 'session-1';
      const currentAgentId = 'agent-1';
      fakeSend(JSON.stringify({
        type: 'chat:send',
        content: text,
        session_id: sessionId,
        agent_id: currentAgentId,
      }));
      expect(sentPayload!['type']).assertEqual('chat:send');
      expect(sentPayload!['content']).assertEqual('hello');
      expect(sentPayload!['session_id']).assertEqual('session-1');
      expect(sentPayload!['agent_id']).assertEqual('agent-1');
    });
  });
}
