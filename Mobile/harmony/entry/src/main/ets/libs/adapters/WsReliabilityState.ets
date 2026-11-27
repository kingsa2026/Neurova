/** WS 帧去重与单调游标判据；纯逻辑，鸿蒙单测与适配器共用。 */
export class WsReliabilityState {
  cursor: number = 0;
  private seenIds: string[] = [];

  constructor(cursor: number = 0) {
    this.cursor = cursor;
  }

  reset(): void {
    this.cursor = 0;
    this.seenIds = [];
  }

  accept(frame: Record<string, Object>): boolean {
    const rawSeq = frame['seq'];
    const seq = typeof rawSeq === 'number' ? rawSeq : 0;
    if (seq > 0 && seq <= this.cursor) {
      return false;
    }
    // 先取最大 seq：业务 ID 重复只抑制派发，游标仍必须越过该帧。
    if (seq > this.cursor) {
      this.cursor = seq;
    }
    const messageId = frame['message_id'];
    const eventId = frame['event_id'];
    const id = typeof messageId === 'string' && messageId.length > 0
      ? messageId : (typeof eventId === 'string' ? eventId : '');
    if (id.length > 0) {
      if (this.seenIds.indexOf(id) >= 0) {
        return false;
      }
      this.seenIds.push(id);
      if (this.seenIds.length > 256) {
        this.seenIds.shift();
      }
    }
    return true;
  }
}
