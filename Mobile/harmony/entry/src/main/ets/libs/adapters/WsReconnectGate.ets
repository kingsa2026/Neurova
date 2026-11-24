/**
 * WsReconnectGate - 前台恢复补连判定（纯函数，Node 直跑可测）
 *
 * 背景：真机/模拟器验证发现的断线不自愈缺口——WebSocketAdapter 自动重连
 * maxReconnect 耗尽后永久停摆，而退后台时 JS 定时器挂起、回前台没有任何
 * 重连触发点（对照安卓端 snapshotFlow 就绪即连 + connectIfIdle 幂等入口）。
 * 本门是前台补连的唯一判定源：已连接 / 用户主动关闭 / 重连定时器在途 → 不动；
 * 其余（含重试耗尽态）→ 放行，由调用方补一次连接。
 */

/** 放行补连：已连接、用户主动关闭（登出语义）、重连定时器在途三者任一即不动 */
export function shouldAttemptIdleConnect(connected: boolean, manualClose: boolean,
                                         reconnectPending: boolean): boolean {
  return !connected && !manualClose && !reconnectPending;
}
