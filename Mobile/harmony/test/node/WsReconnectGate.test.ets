/**
 * WsReconnectGate 单测（Node 直跑）：前台恢复补连门判定
 *
 * 背景：真机/模拟器验证发现的断线不自愈缺口——适配器自动重连 maxReconnect=10
 * 耗尽后永久停摆，退后台时 JS 定时器挂起、回前台无任何重连触发点（对照安卓端
 * snapshotFlow 就绪即连 + connectIfIdle 幂等入口）。门是补连的唯一判定源。
 */

import { shouldAttemptIdleConnect } from '../../entry/src/main/ets/libs/adapters/WsReconnectGate';
import { check, source } from './Harness';

source('鸿蒙 WS 前台补连门——真机验证发现的重试耗尽后永久停摆缺口');

// 已连接：什么都不做（幂等核心）
check('已连接 → 不动',
  !shouldAttemptIdleConnect(true, false, false));
// 用户主动断开（登出语义）：不抢回
check('主动关闭（登出）→ 不动',
  !shouldAttemptIdleConnect(false, true, false));
// 重连定时器已在途：交给既有退避流程，不另起第二条重连路径
check('重连定时器挂起 → 不动',
  !shouldAttemptIdleConnect(false, false, true));
// 重试耗尽（未连 + 非主动 + 无挂起定时器）→ 放行补连（本缺口的红点）
check('重试耗尽态 → 放行补连',
  shouldAttemptIdleConnect(false, false, false));
// 普通断线（未连 + 非主动 + 无挂起）→ 放行补连
check('普通断线态 → 放行补连',
  shouldAttemptIdleConnect(false, false, false));
// 主动关闭优先于一切：即使已断线也不自动回连
check('主动关闭且已断线 → 仍不动',
  !shouldAttemptIdleConnect(false, true, true));
