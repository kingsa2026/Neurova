import { describe, it, expect } from '@ohos/hypium';
import { WsReliabilityState } from '../../../main/ets/libs/adapters/WsReliabilityState';

export default function wsReliabilityStateTest() {
  describe('WsReliabilityState', () => {
    it('decodesEscapedJsonWithoutTrimAndTakesMaxSeq', 0, () => {
      const state = new WsReliabilityState();
      const frame = JSON.parse('{"type":"chat:chunk","content":"a\\\"b\\\\c\\n","seq":9}') as Record<string, Object>;
      expect(state.accept(frame)).assertTrue();
      expect(frame['content']).assertEqual('a"b\\c\n');
      expect(state.accept({ 'type': 'chat:done', 'seq': 4 })).assertFalse();
      expect(state.cursor).assertEqual(9);
    });

    it('resetClearsCursorAndBusinessIdsForSnapshotResync', 0, () => {
      const state = new WsReliabilityState();
      expect(state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 9 })).assertTrue();
      state.reset();
      expect(state.cursor).assertEqual(0);
      expect(state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 1 })).assertTrue();
    });

    it('deduplicatesMessageAndEventIds', 0, () => {
      const state = new WsReliabilityState();
      expect(state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 1 })).assertTrue();
      expect(state.accept({ 'type': 'chat:chunk', 'message_id': 'm1', 'seq': 2 })).assertFalse();
      expect(state.accept({ 'type': 'device:event', 'event_id': 'e1', 'seq': 3 })).assertTrue();
      expect(state.accept({ 'type': 'device:event', 'event_id': 'e1', 'seq': 4 })).assertFalse();
      expect(state.cursor).assertEqual(4);
    });
  });
}
