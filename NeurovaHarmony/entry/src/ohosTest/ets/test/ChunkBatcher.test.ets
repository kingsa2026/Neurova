// ChunkBatcher 单元测试 - TDD 红绿灯垂直切片
// 验证 WS 流式 chunk 批量节流行为，纯函数无 UI 依赖
// 设计：通过 now 参数注入时间，避免依赖系统时钟，便于测试
import { describe, it, expect, beforeEach } from '@ohos/hypium';
import { ChunkBatcher } from '../../../../main/ets/libs/perf/ChunkBatcher';

export default function chunkBatcherTest() {
  describe('ChunkBatcher', () => {
    let batcher: ChunkBatcher;

    beforeEach(() => {
      batcher = new ChunkBatcher({ interval: 60 });
    });

    // ========== 行为 1: push 单个 chunk 后缓冲区长度递增 ==========
    it('push_single_chunk_increases_pending_length', 0, () => {
      batcher.push('hello');
      expect(batcher.pendingLength).assertEqual(5);
    });

    // ========== 行为 2: push 多个 chunk 累积到缓冲区 ==========
    it('push_multiple_chunks_accumulates', 0, () => {
      batcher.push('hello');
      batcher.push(' ');
      batcher.push('world');
      expect(batcher.pendingLength).assertEqual(11);
    });

    // ========== 行为 3: flush 空缓冲区返回空字符串 ==========
    it('flush_empty_buffer_returns_empty', 0, () => {
      expect(batcher.flush(100)).assertEqual('');
    });

    // ========== 行为 4: flush 返回累积内容并清空缓冲区 ==========
    it('flush_returns_accumulated_content_and_clears', 0, () => {
      batcher.push('foo');
      batcher.push('bar');
      const content = batcher.flush(100);
      expect(content).assertEqual('foobar');
      expect(batcher.pendingLength).assertEqual(0);
    });

    // ========== 行为 5: shouldFlush 在时间窗口内返回 false ==========
    it('shouldFlush_within_interval_returns_false', 0, () => {
      batcher.push('data');
      // lastFlushTime 初始为 0，now=50 < interval=60
      expect(batcher.shouldFlush(50)).assertFalse();
    });

    // ========== 行为 6: shouldFlush 在时间窗口外返回 true ==========
    it('shouldFlush_after_interval_returns_true', 0, () => {
      batcher.push('data');
      // now=100 >= interval=60
      expect(batcher.shouldFlush(100)).assertTrue();
    });

    // ========== 行为 7: shouldFlush 缓冲区为空时永远返回 false ==========
    it('shouldFlush_empty_buffer_returns_false', 0, () => {
      // 缓冲区为空，即使时间窗口已过
      expect(batcher.shouldFlush(10000)).assertFalse();
    });

    // ========== 行为 8: flush 更新 lastFlushTime，下个窗口内 shouldFlush 返回 false ==========
    it('flush_updates_lastFlushTime_resets_window', 0, () => {
      batcher.push('data1');
      batcher.flush(100); // lastFlushTime=100
      batcher.push('data2');
      // 距上次 flush 仅 30ms，未到窗口
      expect(batcher.shouldFlush(130)).assertFalse();
    });

    // ========== 行为 9: forceFlush 无视时间窗口立即返回累积内容 ==========
    it('forceFlush_ignores_time_window', 0, () => {
      batcher.push('data1');
      batcher.flush(100); // 进入新窗口
      batcher.push('data2');
      // 距上次 flush 仅 10ms，shouldFlush 应为 false
      expect(batcher.shouldFlush(110)).assertFalse();
      // 但 forceFlush 应立即返回
      const content = batcher.forceFlush();
      expect(content).assertEqual('data2');
      expect(batcher.pendingLength).assertEqual(0);
    });

    // ========== 行为 10: forceFlush 空缓冲区返回空字符串 ==========
    it('forceFlush_empty_returns_empty', 0, () => {
      expect(batcher.forceFlush()).assertEqual('');
    });

    // ========== 行为 11: reset 清空缓冲区与计时 ==========
    it('reset_clears_buffer_and_timer', 0, () => {
      batcher.push('foo');
      batcher.flush(100);
      batcher.push('bar');
      batcher.reset();
      expect(batcher.pendingLength).assertEqual(0);
      // 重置后即使时间窗口已过，因缓冲区为空，shouldFlush 仍为 false
      expect(batcher.shouldFlush(10000)).assertFalse();
    });

    // ========== 行为 12: 默认 interval 为 60ms（不传 options） ==========
    it('default_interval_is_60ms', 0, () => {
      const b = new ChunkBatcher();
      b.push('data');
      // now=59 < 60
      expect(b.shouldFlush(59)).assertFalse();
      // now=60 >= 60
      expect(b.shouldFlush(60)).assertTrue();
    });

    // ========== 行为 13: 自定义 interval 生效 ==========
    it('custom_interval_takes_effect', 0, () => {
      const b = new ChunkBatcher({ interval: 200 });
      b.push('data');
      expect(b.shouldFlush(199)).assertFalse();
      expect(b.shouldFlush(200)).assertTrue();
    });

    // ========== 行为 14: 完整流式周期：push→shouldFlush→flush→forceFlush ==========
    it('full_streaming_cycle', 0, () => {
      // 模拟 WS chunk 流式到达
      batcher.push('H');
      batcher.push('e');
      batcher.push('l');
      batcher.push('l');
      batcher.push('o');
      // 窗口未到，不刷新
      expect(batcher.shouldFlush(30)).assertFalse();
      // 窗口到，刷新一次
      expect(batcher.shouldFlush(60)).assertTrue();
      const first = batcher.flush(60);
      expect(first).assertEqual('Hello');
      // 继续累积
      batcher.push(' ');
      batcher.push('World');
      // 距上次 flush 仅 20ms，不刷新
      expect(batcher.shouldFlush(80)).assertFalse();
      // done 事件触发强制刷新
      const rest = batcher.forceFlush();
      expect(rest).assertEqual(' World');
      expect(batcher.pendingLength).assertEqual(0);
    });
  });
}
