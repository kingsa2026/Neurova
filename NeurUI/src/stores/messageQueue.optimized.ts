/**
 * Optimized Message Queue Store - Offline-First Architecture
 * 
 * Key improvements:
 * - Offline-first architecture with persistent queue
 * - Automatic sync when online
 * - Batch processing optimization
 * - Retry with exponential backoff
 * - Priority-based ordering
 * - Storage persistence (localStorage)
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { handleStoreError, logStoreOperation, debounce } from './utils'

// =============================================================================
// Types and Interfaces
// =============================================================================

export interface QueuedMessage {
  /** Client-generated ID (timestamp + sequence) */
  id: string
  text: string
  enqueuedAt: string
  status: 'pending' | 'sending' | 'sent' | 'failed'
  error?: string
  sessionId?: string
  /** Retry count for exponential backoff */
  retryCount?: number
  /** Last retry timestamp */
  lastRetryAt?: string
  /** Priority level (higher = more urgent) */
  priority?: number
  /** TTL in milliseconds (optional) */
  ttlMs?: number
}

export interface SyncConfig {
  /** Auto-sync interval in ms */
  syncIntervalMs?: number
  /** Max batch size for bulk operations */
  maxBatchSize?: number
  /** Retry configuration */
  retry: {
    maxAttempts: number
    initialDelayMs: number
    maxDelayMs: number
    backoffMultiplier: number
  }
}

const DEFAULT_SYNC_CONFIG: SyncConfig = {
  syncIntervalMs: 5000,
  maxBatchSize: 10,
  retry: {
    maxAttempts: 5,
    initialDelayMs: 1000,
    maxDelayMs: 60000,
    backoffMultiplier: 2,
  },
}

// =============================================================================
// Storage Helpers
// =============================================================================

const QUEUE_STORAGE_KEY = 'neurova_message_queue'

function saveQueueToStorage(items: QueuedMessage[]): void {
  try {
    const serialized = JSON.stringify(items, null, 2)
    localStorage.setItem(QUEUE_STORAGE_KEY, serialized)
  } catch (err) {
    console.warn('[MessageQueueStore] Failed to save to storage:', err)
  }
}

function loadQueueFromStorage(): QueuedMessage[] {
  try {
    const serialized = localStorage.getItem(QUEUE_STORAGE_KEY)
    if (serialized) {
      return JSON.parse(serialized) as QueuedMessage[]
    }
  } catch (err) {
    console.warn('[MessageQueueStore] Failed to load from storage:', err)
  }
  return []
}

// =============================================================================
// Store Definition
// =============================================================================

export const useMessageQueueStore = defineStore('messageQueue', () => {
  // ===========================================================================
  // State
  // ===========================================================================
  
  const items = ref<QueuedMessage[]>([])
  const paused = ref(false)
  const isSyncing = ref(false)
  const lastSyncTime = ref<Date | null>(null)
  const online = ref(navigator.onLine)
  
  // Sync configuration
  const syncConfig = ref<SyncConfig>(DEFAULT_SYNC_CONFIG)
  
  // Statistics
  const stats = ref({
    totalEnqueued: 0,
    totalSent: 0,
    totalFailed: 0,
    totalRetried: 0,
  })
  
  // ===========================================================================
  // Getters
  // ===========================================================================
  
  const pendingCount = computed(() => 
    items.value.filter((i) => i.status === 'pending').length
  )
  
  const sendingCount = computed(() => 
    items.value.filter((i) => i.status === 'sending').length
  )
  
  const failedCount = computed(() => 
    items.value.filter((i) => i.status === 'failed').length
  )
  
  const hasPending = computed(() => pendingCount.value > 0)
  
  const hasFailed = computed(() => failedCount.value > 0)
  
  const hasSending = computed(() => sendingCount.value > 0)
  
  /** Get pending messages grouped by session */
  const pendingBySession = computed(() => {
    const map = new Map<string, QueuedMessage[]>()
    
    items.value
      .filter((i) => i.status === 'pending')
      .forEach((item) => {
        const sessionId = item.sessionId || '__global__'
        if (!map.has(sessionId)) {
          map.set(sessionId, [])
        }
        map.get(sessionId)!.push(item)
      })
    
    return map
  })
  
  /**
   * Pending 消息的出队视图：先按 priority 降序，同级保持 `items` 的数组顺序。
   *
   * 同级**不再**按 enqueuedAt 重排：数组本身就是出队次序的事实源
   * （enqueue push 到尾部；reorder/moveToTop 直接改写数组）。
   * 旧实现同级按 enqueuedAt 排序，会让 moveToTop 插队失效——
   * 被移到队首的项时间戳不变，下一次排序又把它按时间戳排回原位；
   * 而 enqueuedAt 为毫秒精度，相邻两次 enqueue 落在同一毫秒时该 sort
   * 退化成"无操作"，于是同一处逻辑时对时错（CI 里表现为偶发红）。
   * sort 契约自 ES2019 起稳定，同级返回 0 即保留输入顺序。
   */
  const prioritizedQueue = computed(() => {
    return [...items.value].sort((a, b) => {
      // Higher priority first
      if ((b.priority || 0) !== (a.priority || 0)) {
        return (b.priority || 0) - (a.priority || 0)
      }
      // Equal priority: keep queue (array) order — stable, does not fight moveToTop
      return 0
    })
  })
  
  // ===========================================================================
  // Lifecycle - Online/Offline Detection
  // ===========================================================================
  
  function setupOnlineDetection() {
    window.addEventListener('online', () => {
      online.value = true
      logStoreOperation('messageQueue', 'online', true)
      
      // Auto-sync when going online
      if (hasPending.value && !paused.value) {
        processQueue()
      }
    })
    
    window.addEventListener('offline', () => {
      online.value = false
      logStoreOperation('messageQueue', 'offline', false)
    })
  }
  
  // Initialize online detection
  setupOnlineDetection()
  
  // ===========================================================================
  // Action Groups
  // ===========================================================================
  
  /** Queue management actions */
  const queueActions = {
    /** Add message to queue */
    enqueue(text: string, sessionId?: string, options?: {
      priority?: number
      ttlMs?: number
    }): QueuedMessage {
      const seq = `q${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
      
      const item: QueuedMessage = {
        id: seq,
        text: text.trim(),
        enqueuedAt: new Date().toISOString(),
        status: 'pending',
        sessionId,
        retryCount: 0,
        priority: options?.priority || 0,
        ttlMs: options?.ttlMs,
      }
      
      items.value.push(item)
      stats.value.totalEnqueued++
      
      // 收集时刻必须保持 pending（契约：enqueue 只入队，不代发）。
      // 旧实现入队即调 processQueue() → markSending 把形态改成 sending，
      // 调用方拿到的返回值与 store 内状态都对不上（且异步挂起 100ms 后才出队）。
      // 立即出队是消费方职责（next → markSending → markSent），本 store 一律不自动发送。
      logStoreOperation('messageQueue', 'enqueue', `${seq}: ${text.length} chars`)
      
      // Persist to storage
      saveQueueToStorage(items.value)
      
      return item
    },
    
    /**
     * Get next message to process (respects session filter).
     *
     * 取队首 = priority 最高；同级取数组中最靠前的一项（见 prioritizedQueue 注释）。
     * 同级**禁止**再按 enqueuedAt 排序，否则 moveToTop/reorder 的插队顺序会被抹掉。
     */
    next(sessionId?: string): QueuedMessage | undefined {
      const filtered = items.value.filter(
        (i) => i.status === 'pending' && (!sessionId || i.sessionId === sessionId)
      )
      
      return filtered.sort((a, b) => {
        if ((b.priority || 0) !== (a.priority || 0)) {
          return (b.priority || 0) - (a.priority || 0)
        }
        return 0
      })[0]
    },
    
    /** Count pending messages (optionally filtered by session) */
    countPending(sessionId?: string): number {
      return items.value.filter(
        (i) => i.status === 'pending' && (!sessionId || i.sessionId === sessionId)
      ).length
    },
    
    /** Remove expired messages */
    cleanupExpired(): number {
      const now = Date.now()
      const beforeCount = items.value.length
      
      items.value = items.value.filter((item) => {
        if (!item.ttlMs || item.status !== 'pending') return true
        
        const age = now - new Date(item.enqueuedAt).getTime()
        return age < item.ttlMs
      })
      
      const removed = beforeCount - items.value.length
      
      if (removed > 0) {
        logStoreOperation('messageQueue', 'cleanupExpired', removed)
        saveQueueToStorage(items.value)
      }
      
      return removed
    },
  }
  
  /** Status tracking actions */
  const statusActions = {
    /** Mark as sending (prevents re-entry) */
    markSending(id: string): boolean {
      const item = items.value.find((i) => i.id === id)
      if (!item || item.status !== 'pending') {
        return false
      }
      
      item.status = 'sending'
      logStoreOperation('messageQueue', 'markSending', id)
      return true
    },
    
    /** Mark as sent and remove from queue */
    markSent(id: string): void {
      const idx = items.value.findIndex((i) => i.id === id)
      if (idx !== -1) {
        items.value.splice(idx, 1)
        stats.value.totalSent++
        
        logStoreOperation('messageQueue', 'markSent', id)
        saveQueueToStorage(items.value)
      }
    },
    
    /** Mark as failed (keeps for retry) */
    markFailed(id: string, error?: string): void {
      const item = items.value.find((i) => i.id === id)
      if (item) {
        item.status = 'failed'
        item.error = error
        
        logStoreOperation('messageQueue', 'markFailed', `${id}: ${error}`)
        saveQueueToStorage(items.value)
      }
    },
    
    /** Retry failed message */
    retry(id: string): boolean {
      const item = items.value.find((i) => i.id === id)
      if (!item || item.status !== 'failed') {
        return false
      }
      
      const config = syncConfig.value.retry
      item.retryCount = (item.retryCount || 0) + 1
      item.lastRetryAt = new Date().toISOString()
      item.error = undefined
      
      // Check if max retries exceeded
      if (item.retryCount >= config.maxAttempts) {
        item.status = 'failed'
        item.error = `Max retries (${config.maxAttempts}) exceeded`
        stats.value.totalFailed++
      } else {
        item.status = 'pending'
        stats.value.totalRetried++
      }
      
      logStoreOperation('messageQueue', 'retry', `${id}: attempt ${item.retryCount}`)
      saveQueueToStorage(items.value)
      
      return true
    },
    
    /** Update text of pending message */
    updateText(id: string, text: string): boolean {
      const item = items.value.find((i) => i.id === id)
      if (!item || item.status !== 'pending') {
        return false
      }
      
      item.text = text.trim()
      logStoreOperation('messageQueue', 'updateText', id)
      return true
    },
  }
  
  /** Ordering actions */
  const orderActions = {
    /** Reorder pending messages */
    reorder(orderedIds: string[]): void {
      const byId = new Map(items.value.map((i) => [i.id, i]))
      const pendingOrdered = orderedIds
        .map((id) => byId.get(id))
        .filter((i): i is QueuedMessage => !!i && i.status === 'pending')
      
      const pendingIds = new Set(pendingOrdered.map((i) => i.id))
      const rest = items.value.filter(
        (i) => i.status === 'pending' && !pendingIds.has(i.id)
      )
      const nonPending = items.value.filter((i) => i.status !== 'pending')
      
      items.value = [...nonPending, ...pendingOrdered, ...rest]
      saveQueueToStorage(items.value)
      
      logStoreOperation('messageQueue', 'reorder', orderedIds.length)
    },
    
    /** Move message to top of queue */
    moveToTop(id: string): boolean {
      const item = items.value.find((i) => i.id === id)
      if (!item || item.status !== 'pending') {
        return false
      }
      
      const rest = items.value.filter((i) => i.id !== id)
      const nonPending = rest.filter((i) => i.status !== 'pending')
      const pendings = rest.filter((i) => i.status === 'pending')
      
      items.value = [...nonPending, item, ...pendings]
      saveQueueToStorage(items.value)
      
      logStoreOperation('messageQueue', 'moveToTop', id)
      return true
    },
    
    /** Remove single message */
    remove(id: string): boolean {
      const item = items.value.find((i) => i.id === id)
      if (!item || item.status === 'sending') {
        return false
      }
      
      items.value = items.value.filter((i) => i.id !== id)
      logStoreOperation('messageQueue', 'remove', id)
      saveQueueToStorage(items.value)
      
      return true
    },
    
    /** Clear queue (keeps sending messages) */
    clear(): void {
      const beforeCount = items.value.length
      items.value = items.value.filter((i) => i.status === 'sending')
      const cleared = beforeCount - items.value.length
      
      if (cleared > 0) {
        logStoreOperation('messageQueue', 'clear', cleared)
        saveQueueToStorage(items.value)
      }
    },
  }
  
  /** Control actions */
  const controlActions = {
    setPaused(value: boolean): void {
      paused.value = value
      logStoreOperation('messageQueue', 'setPaused', value)
    },
    
    togglePause(): void {
      paused.value = !paused.value
      logStoreOperation('messageQueue', 'togglePause', paused.value)
    },
    
    configure(config: Partial<SyncConfig>): void {
      syncConfig.value = {
        ...syncConfig.value,
        ...config,
        retry: {
          ...syncConfig.value.retry,
          ...(config.retry || {}),
        },
      }
      logStoreOperation('messageQueue', 'configure', true)
    },
  }
  
  // ===========================================================================
  // Core Processing Logic
  // ===========================================================================
  
  /** Process queue with batching and exponential backoff */
  async function processQueue(): Promise<void> {
    if (isSyncing.value || paused.value || !online.value || !hasPending.value) {
      return
    }
    
    isSyncing.value = true
    
    try {
      const config = syncConfig.value
      const batch = prioritizedQueue.value
        .filter((i) => i.status === 'pending')
        .slice(0, config.maxBatchSize || 10)
      
      if (batch.length === 0) {
        return
      }
      
      logStoreOperation('messageQueue', 'processQueue', batch.length)
      lastSyncTime.value = new Date()
      
      // Process batch concurrently
      await Promise.allSettled(
        batch.map((item) => processSingleItem(item))
      )
    } finally {
      isSyncing.value = false
    }
  }
  
  /** Process a single queue item with retry logic */
  async function processSingleItem(item: QueuedMessage): Promise<void> {
    // Check TTL
    if (item.ttlMs) {
      const age = Date.now() - new Date(item.enqueuedAt).getTime()
      if (age > item.ttlMs) {
        logStoreOperation('messageQueue', 'expired', item.id)
        items.value = items.value.filter((i) => i.id !== item.id)
        return
      }
    }
    
    // Mark as sending
    if (!statusActions.markSending(item.id)) {
      return
    }
    
    try {
      // TODO: Implement actual send logic
      // await api.sendMessage({ text: item.text, sessionId: item.sessionId })
      
      // Simulate network delay
      await new Promise(resolve => setTimeout(resolve, 100))
      
      // Success
      statusActions.markSent(item.id)
    } catch (err) {
      const errorMessage = handleStoreError(err, `processItem:${item.id}`, { silent: true })
      
      // Mark as failed
      statusActions.markFailed(item.id, errorMessage)
      
      // Schedule retry with exponential backoff
      scheduleRetry(item)
    }
  }
  
  /** Schedule retry with exponential backoff */
  function scheduleRetry(item: QueuedMessage): void {
    const config = syncConfig.value.retry
    const delay = Math.min(
      config.initialDelayMs * Math.pow(config.backoffMultiplier, item.retryCount || 0),
      config.maxDelayMs
    )
    
    setTimeout(() => {
      if (item.status === 'failed') {
        statusActions.retry(item.id)
        processQueue()
      }
    }, delay)
  }
  
  /** Force sync all pending items */
  async function forceSync(): Promise<void> {
    paused.value = false
    await processQueue()
  }
  
  /** Restore queue from storage */
  function restoreFromStorage(): void {
    const stored = loadQueueFromStorage()
    if (stored.length > 0) {
      items.value = stored
      logStoreOperation('messageQueue', 'restoreFromStorage', stored.length)
    }
  }
  
  // ===========================================================================
  // Utility Actions
  // ===========================================================================
  
  /** Get queue statistics */
  function getStatistics() {
    return {
      ...stats.value,
      current: {
        pending: pendingCount.value,
        sending: sendingCount.value,
        failed: failedCount.value,
        total: items.value.length,
      },
      lastSyncTime: lastSyncTime.value,
      isSyncing: isSyncing.value,
      online: online.value,
      paused: paused.value,
    }
  }
  
  /** Reset store state */
  function reset(): void {
    items.value = []
    paused.value = false
    isSyncing.value = false
    lastSyncTime.value = null
    stats.value = {
      totalEnqueued: 0,
      totalSent: 0,
      totalFailed: 0,
      totalRetried: 0,
    }
    
    logStoreOperation('messageQueue', 'reset', true)
    saveQueueToStorage([])
  }
  
  // ===========================================================================
  // Return all state and actions
  // ===========================================================================
  
  return {
    // State
    items,
    paused,
    isSyncing,
    lastSyncTime,
    online,
    syncConfig,
    stats,
    
    // Getters
    pendingCount,
    sendingCount,
    failedCount,
    hasPending,
    hasFailed,
    hasSending,
    pendingBySession,
    prioritizedQueue,
    
    // Actions
    ...queueActions,
    ...statusActions,
    ...orderActions,
    ...controlActions,
    
    // Core functions
    processQueue,
    forceSync,
    restoreFromStorage,
    getStatistics,
    reset,
  }
})
