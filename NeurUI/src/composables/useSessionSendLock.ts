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

// ---------------------------------------------------------------------------
// 2026-09-08 dock 收编 / composer 拆分产物：共享单例。
// ChatPage（sendMessage 守卫）与 ChatComposerArea（发送按钮 disabled）各自
// 实例化时会对同一把 Web Lock 互相竞争——本标签页内部两个实例都调 acquire，
// 第二个实例 ifAvailable 竞争失败把 isOwner 置 false → 发送按钮恒禁用。
// 修复：模块级共享同一实例（同 useComputerPanel 模式）。
// ---------------------------------------------------------------------------
const sharedIsOwner = ref(true)
let sharedReleaseLock: (() => void) | null = null
let sharedCurrentKey: string | null = null

function sharedRelease(): void {
  if (sharedReleaseLock) {
    sharedReleaseLock()
    sharedReleaseLock = null
  }
  sharedCurrentKey = null
}

async function sharedAcquire(key: string): Promise<void> {
  sharedRelease()
  if (typeof navigator === 'undefined' || !navigator.locks) {
    sharedIsOwner.value = true // 能力降级：无锁 API 不阻塞
    return
  }
  sharedCurrentKey = key
  try {
    const handle = await navigator.locks.request(
      `neurova-chat-send:${key}`,
      { ifAvailable: true },
      (lock) => {
        if (lock) {
          sharedIsOwner.value = true
          return new Promise<void>((resolve) => {
            sharedReleaseLock = () => resolve()
          })
        }
        sharedIsOwner.value = false
        sharedReleaseLock = null
        return undefined
      },
    )
    if (handle === undefined) sharedIsOwner.value = false
  } catch {
    sharedIsOwner.value = true
  }
}

export function useSessionSendLock(sessionId: Ref<string | null | undefined>) {
  // 每个调用方各自 watch 同一 store ref（回调都写共享状态，天然去重：
  // sharedAcquire 内部先 sharedRelease 旧 key，key 未变时跳过重复竞争——
  // 防 Web Locks 同标签自锁：ifAvailable 下自己持有的锁自己再请求会失败）。
  watch(
    sessionId,
    (sid) => {
      if (sid && sid !== sharedCurrentKey) {
        void sharedAcquire(sid)
      } else if (!sid) {
        sharedIsOwner.value = true
        sharedRelease()
      }
      // sid === sharedCurrentKey：同 key 重复触发（多实例同步）跳过
    },
    { immediate: true },
  )

  return { isOwner: sharedIsOwner, release: sharedRelease }
}

/** 测试隔离出口：清空单例 watch 安装标记（锁本体由浏览器端释放） */
export function resetSessionSendLockForTest(): void {
  sharedCurrentKey = null
}
