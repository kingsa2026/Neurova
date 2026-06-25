/**
 * 统一 UI 提示库 - 封装 ant-design-vue message
 *
 * 所有 UI 提示必须通过此库调用，禁止直接调用 ant-design-vue message。
 *
 * 特性：
 * - 统一配置（duration: 3s, top: 60px, maxCount: 3）
 * - 去重功能（相同内容 1 秒内只显示一次）
 * - 与事件总线集成（success/error/warning/info 触发 notification:show 事件）
 *
 * 用法：
 *   import { uiMessage } from '@/utils/message'
 *   uiMessage.success('操作成功')
 *   uiMessage.error('出错了')
 */
import { message } from 'ant-design-vue'
import bus from '@/bus'

// ────── 统一配置 ──────

message.config({
  duration: 3,
  top: '60px',
  maxCount: 3,
})

// ────── 去重缓存 ──────
// key: 消息内容, value: 上次显示时间戳
const recentMessages = new Map<string, number>()

/**
 * 去重检查：相同内容在 1 秒内只允许显示一次
 *
 * @param content 消息内容
 * @returns true=允许显示, false=被去重跳过
 */
function dedupe(content: string): boolean {
  const now = Date.now()
  const last = recentMessages.get(content)
  if (last && now - last < 1000) return false // 1秒内重复，跳过
  recentMessages.set(content, now)
  return true
}

/**
 * 清空去重缓存（主要用于测试）
 */
export function clearDedupeCache(): void {
  recentMessages.clear()
}

// ────── 统一提示接口 ──────

export const uiMessage = {
  /**
   * 成功提示
   * @returns true=已显示, false=被去重
   */
  success(content: string, duration?: number): boolean {
    if (!dedupe(content)) return false
    message.success(content, duration)
    bus.emit('notification:show', { type: 'success', message: content })
    return true
  },

  /**
   * 错误提示
   * @returns true=已显示, false=被去重
   */
  error(content: string, duration?: number): boolean {
    if (!dedupe(content)) return false
    message.error(content, duration)
    bus.emit('notification:show', { type: 'error', message: content })
    return true
  },

  /**
   * 警告提示
   * @returns true=已显示, false=被去重
   */
  warning(content: string, duration?: number): boolean {
    if (!dedupe(content)) return false
    message.warning(content, duration)
    bus.emit('notification:show', { type: 'warning', message: content })
    return true
  },

  /**
   * 信息提示
   * @returns true=已显示, false=被去重
   */
  info(content: string, duration?: number): boolean {
    if (!dedupe(content)) return false
    message.info(content, duration)
    bus.emit('notification:show', { type: 'info', message: content })
    return true
  },

  /**
   * 加载提示（不触发 notification:show 事件）
   * @returns true=已显示, false=被去重
   */
  loading(content: string, duration?: number): boolean {
    if (!dedupe(content)) return false
    message.loading(content, duration)
    // loading 不触发 notification:show 事件
    return true
  },
}

export default uiMessage
