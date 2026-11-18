/**
 * PendingDeepLink - 待消费的配对深链（C7：neurova://pair 两端同源）
 *
 * 冷启动时 EntryAbility 先于 Index 拿到 want.uri，而 Index 的路由分发要等
 * 服务器档案/认证状态就绪才发生——深链先暂存于此，Index 分发完再消费，
 * 避开「路由栈未就绪」与「档案未就绪」两个时序坑。
 *
 * 与 Android 侧 PairingRefParser 同一协议事实源：《中继方案》§3.4
 * neurova://pair?ref=…&host=…（解析复用 libs/protocol/PairingPayload）。
 */
export class PendingDeepLink {
  private static instance: PendingDeepLink;
  private uri: string = '';

  private constructor() {}

  static getInstance(): PendingDeepLink {
    if (!PendingDeepLink.instance) {
      PendingDeepLink.instance = new PendingDeepLink();
    }
    return PendingDeepLink.instance;
  }

  set(uri: string): void {
    this.uri = uri;
  }

  /** 取走并清空（一次性消费） */
  take(): string {
    const out = this.uri;
    this.uri = '';
    return out;
  }

  peek(): string {
    return this.uri;
  }
}
