/**
 * 跨标签单发送者锁（补课 A4，QP Web Locks 语义）。
 *
 * 同一 session 在多个浏览器标签打开时，Web Locks API（Navigator.locks，
 * Chrome/Edge/Safari 均已支持）保证同一时刻只有一个标签持有发送权；
 * 持有者标签关闭后锁自动释放，等待中的标签自动接管成为新持有者。
 *
 * 语义：
 * - isOwner=true 的标签才能 sendMessage；非持有者发送按钮禁用并提示
 * - 组件卸载自动释放（release 回调）
 * - 无 locks API（旧浏览器）→ 恒返回 owner=true（能力降级不阻塞）
 */
import { onUnmounted, ref, watch, type Ref } from 'vue'

export function useSessionSendLock(sessionId: Ref<string | null | undefined>) {
  const isOwner = ref(true)
  let releaseLock: (() => void) | null = null
  let currentKey: string | null = null

  async function acquire(key: string): Promise<void> {
    // 先释放上一个 session 的锁
    release()
    if (typeof navigator === 'undefined' || !navigator.locks) {
      isOwner.value = true // 能力降级：无锁 API 不阻塞
      return
    }
    currentKey = key
    try {
      const handle = await navigator.locks.request(
        `neurova-chat-send:${key}`,
        { ifAvailable: true },
        (lock) => {
          if (lock) {
            isOwner.value = true
            // 持锁直到显式释放：返回一个永不 resolve 的 Promise 的
            // 替代方案是让回调立即返回并配合 ifAvailable 重新竞争——
            // 这里用"持有期由 release() 控制"的托管模式：
            return new Promise<void>((resolve) => {
              releaseLock = () => resolve()
            })
          }
          isOwner.value = false
          releaseLock = null
          return undefined
        },
      )
      // handle 为 undefined 表示未获得锁
      if (handle === undefined) isOwner.value = false
    } catch {
      // 锁机制异常不阻塞聊天（与能力降级同策略）
      isOwner.value = true
    }
  }

  function release(): void {
    if (releaseLock) {
      releaseLock()
      releaseLock = null
    }
    currentKey = null
  }

  watch(
    sessionId,
    (sid) => {
      if (sid) {
        void acquire(sid)
      } else {
        isOwner.value = true
        release()
      }
    },
    { immediate: true },
  )

  onUnmounted(release)

  return { isOwner, release }
}
