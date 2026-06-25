/**
 * ChunkBatcher - WS 流式 chunk 批量节流器
 *
 * 职责：累积 WS 流式到达的 chunk，按时间窗口批量刷新，减少 UI 重渲染次数
 * 设计：纯函数无副作用；通过 now 参数注入时间，便于单元测试
 *
 * 用法：
 *   const batcher = new ChunkBatcher({ interval: 60 }); // 60ms 时间窗口
 *   // chunk 到达：
 *   batcher.push(chunk);
 *   if (batcher.shouldFlush(Date.now())) {
 *     const content = batcher.flush(Date.now());
 *     // 追加到消息并触发响应式更新
 *   }
 *   // done 事件：
 *   const rest = batcher.forceFlush(); // 强制刷新剩余缓冲
 *
 * TDD：ChunkBatcher.test.ets 按红绿灯垂直切片逐步实现
 */

/** ChunkBatcher 构造选项 */
export interface ChunkBatchOptions {
  /** 时间窗口（毫秒），默认 60ms（约 16 帧） */
  interval?: number;
}

/** 默认时间窗口 60ms */
const DEFAULT_INTERVAL = 60;

export class ChunkBatcher {
  /** 待刷新缓冲区 */
  private buffer: string = '';
  /** 上次 flush 时间戳（毫秒） */
  private lastFlushTime: number = 0;
  /** 时间窗口（毫秒） */
  private readonly interval: number;

  constructor(options?: ChunkBatchOptions) {
    this.interval = options?.interval ?? DEFAULT_INTERVAL;
  }

  /**
   * 追加 chunk 到缓冲区
   * @param chunk 流式 chunk 字符串
   */
  push(chunk: string): void {
    this.buffer += chunk;
  }

  /**
   * 检查是否应该刷新
   * 规则：缓冲区非空 且 距上次 flush 时间 ≥ interval
   * @param now 当前时间戳（毫秒）
   * @return true 表示应调用 flush
   */
  shouldFlush(now: number): boolean {
    if (this.buffer.length === 0) return false;
    return (now - this.lastFlushTime) >= this.interval;
  }

  /**
   * 刷新缓冲区（按时间窗口）
   * 规则：缓冲区为空返回 ''；否则返回累积内容并清空、更新 lastFlushTime
   * @param now 当前时间戳（毫秒）
   * @return 累积的 chunk 内容
   */
  flush(now: number): string {
    if (this.buffer.length === 0) return '';
    const content = this.buffer;
    this.buffer = '';
    this.lastFlushTime = now;
    return content;
  }

  /**
   * 强制刷新（无视时间窗口）
   * 用于 done/error 事件，确保流结束时缓冲区内容全部输出
   * @return 累积的 chunk 内容
   */
  forceFlush(): string {
    if (this.buffer.length === 0) return '';
    const content = this.buffer;
    this.buffer = '';
    return content;
  }

  /** 当前缓冲区字节长度 */
  get pendingLength(): number {
    return this.buffer.length;
  }

  /**
   * 重置：清空缓冲区与计时
   * 用于会话切换或错误恢复
   */
  reset(): void {
    this.buffer = '';
    this.lastFlushTime = 0;
  }
}
