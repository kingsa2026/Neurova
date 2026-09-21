/**
 * Message Queue Store Unit Tests
 * 
 * Tests for the optimized Message Queue Store with offline-first architecture
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useMessageQueueStore } from '@/stores/messageQueue.optimized'
import { defineStore } from 'pinia'
import { createPinia, setActivePinia } from 'pinia'

// Mock localStorage
const localStorageMock: Record<string, string> = {}
Object.defineProperty(global, 'localStorage', {
  value: {
    getItem: vi.fn((key: string) => localStorageMock[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      localStorageMock[key] = value
    }),
    removeItem: vi.fn((key: string) => {
      delete localStorageMock[key]
    }),
    clear: vi.fn(() => {
      Object.keys(localStorageMock).forEach(key => {
        delete localStorageMock[key]
      })
    }),
  },
})

// Mock navigator.onLine
Object.defineProperty(global.navigator, 'onLine', {
  value: true,
  writable: true,
})

describe('MessageQueueStore', () => {
  let store: ReturnType<typeof useMessageQueueStore>
  
  beforeEach(() => {
    setActivePinia(createPinia())
    store = useMessageQueueStore()
    // Reset state
    store.reset()
  })
  
  describe('enqueue', () => {
    it('should add message to queue', () => {
      const result = store.enqueue('Test message', 'session-1')
      
      expect(result.id).toBeDefined()
      expect(result.text).toBe('Test message')
      expect(result.sessionId).toBe('session-1')
      expect(result.status).toBe('pending')
      expect(result.enqueuedAt).toBeDefined()
    })
    
    it('should trim whitespace from text', () => {
      const result = store.enqueue('  Test message  ')
      
      expect(result.text).toBe('Test message')
    })
    
    it('should assign priority and TTL if provided', () => {
      const result = store.enqueue('High priority', 'session-1', {
        priority: 10,
        ttlMs: 60000,
      })
      
      expect(result.priority).toBe(10)
      expect(result.ttlMs).toBe(60000)
    })
    
    it('should increment totalEnqueued counter', () => {
      store.enqueue('Message 1')
      store.enqueue('Message 2')
      
      expect(store.stats.totalEnqueued).toBe(2)
    })
    
    it('should persist to storage', () => {
      store.enqueue('Test message')
      
      expect(global.localStorage.setItem).toHaveBeenCalled()
    })
  })
  
  describe('next', () => {
    it('should return first pending message', () => {
      store.enqueue('First message')
      store.enqueue('Second message')
      
      const next = store.next()
      
      expect(next?.text).toBe('First message')
    })
    
    it('should respect session filter', () => {
      store.enqueue('Session A message', 'session-a')
      store.enqueue('Session B message', 'session-b')
      
      const next = store.next('session-a')
      
      expect(next?.sessionId).toBe('session-a')
    })
    
    it('should prioritize by priority field', () => {
      store.enqueue('Low priority', undefined, { priority: 1 })
      store.enqueue('High priority', undefined, { priority: 10 })
      
      const next = store.next()
      
      expect(next?.text).toBe('High priority')
    })
  })
  
  describe('status tracking', () => {
    it('should mark message as sending', () => {
      const msg = store.enqueue('Test message')
      const result = store.markSending(msg.id)
      
      expect(result).toBe(true)
      expect(msg.status).toBe('sending')
    })
    
    it('should not allow re-marking as sending', () => {
      const msg = store.enqueue('Test message')
      store.markSending(msg.id)
      const result = store.markSending(msg.id)
      
      expect(result).toBe(false)
    })
    
    it('should mark message as sent and remove from queue', () => {
      const msg = store.enqueue('Test message')
      store.markSent(msg.id)
      
      expect(store.items.length).toBe(0)
      expect(store.stats.totalSent).toBe(1)
    })
    
    it('should mark message as failed with error', () => {
      const msg = store.enqueue('Test message')
      store.markFailed(msg.id, 'Network error')
      
      expect(msg.status).toBe('failed')
      expect(msg.error).toBe('Network error')
      expect(store.stats.totalFailed).toBe(0) // Only incremented on retry failure
    })
    
    it('should retry failed message', () => {
      const msg = store.enqueue('Test message')
      store.markFailed(msg.id, 'Error')
      const result = store.retry(msg.id)
      
      expect(result).toBe(true)
      expect(msg.status).toBe('pending')
      expect(msg.error).toBeUndefined()
      expect(msg.retryCount).toBe(1)
      expect(store.stats.totalRetried).toBe(1)
    })
    
    it('should fail after max retries exceeded', () => {
      const msg = store.enqueue('Test message')
      
      // Manually set retry count to max
      msg.retryCount = 5
      msg.status = 'failed'
      
      store.retry(msg.id)
      
      expect(msg.status).toBe('failed')
      expect(msg.error).toContain('Max retries')
      expect(store.stats.totalFailed).toBe(1)
    })
    
    it('should update text of pending message', () => {
      const msg = store.enqueue('Original text')
      const result = store.updateText(msg.id, 'Updated text')
      
      expect(result).toBe(true)
      expect(msg.text).toBe('Updated text')
    })
    
    it('should not update text of non-pending message', () => {
      const msg = store.enqueue('Test message')
      store.markSent(msg.id)
      const result = store.updateText(msg.id, 'New text')
      
      expect(result).toBe(false)
    })
  })
  
  describe('ordering', () => {
    it('should reorder pending messages', () => {
      const msg1 = store.enqueue('Message 1')
      const msg2 = store.enqueue('Message 2')
      const msg3 = store.enqueue('Message 3')
      
      store.reorder([msg3.id, msg1.id, msg2.id])
      
      const pending = store.items.filter(i => i.status === 'pending')
      expect(pending[0].id).toBe(msg3.id)
      expect(pending[1].id).toBe(msg1.id)
      expect(pending[2].id).toBe(msg2.id)
    })
    
    it('should move message to top', () => {
      const msg1 = store.enqueue('First')
      const msg2 = store.enqueue('Second')
      
      store.moveToTop(msg2.id)
      
      const next = store.next()
      expect(next?.id).toBe(msg2.id)
    })
    
    // 回归：moveToTop 是「改写数组次序」，不能被出队排序按 enqueuedAt 抹掉。
    // enqueuedAt 为毫秒精度，上面那条用例只在两次 enqueue 恰好落在同一毫秒时通过
    // （同一毫秒时旧实现的 sort 稳定退化为无操作），跨毫秒就红——CI 里表现为偶发。
    // 这里强制两条目落在不同毫秒，把「排序不得覆盖插队」固化成确定性断言。
    it('should keep moved message on top across differing enqueue timestamps', () => {
      vi.useFakeTimers()
      try {
        vi.setSystemTime(new Date('2026-01-01T00:00:00.000Z'))
        const msg1 = store.enqueue('First')
        vi.setSystemTime(new Date('2026-01-01T00:00:00.500Z'))
        const msg2 = store.enqueue('Second')
        expect(msg1.enqueuedAt).not.toBe(msg2.enqueuedAt)
        
        store.moveToTop(msg2.id)
        
        expect(store.next()?.id).toBe(msg2.id)
        expect(store.prioritizedQueue[0]?.id).toBe(msg2.id)
      } finally {
        vi.useRealTimers()
      }
    })
    
    it('should not move sending message to top', () => {
      const msg = store.enqueue('Test')
      store.markSending(msg.id)
      const result = store.moveToTop(msg.id)
      
      expect(result).toBe(false)
    })
    
    it('should remove single message', () => {
      const msg = store.enqueue('Test message')
      const result = store.remove(msg.id)
      
      expect(result).toBe(true)
      expect(store.items.length).toBe(0)
    })
    
    it('should not remove sending message', () => {
      const msg = store.enqueue('Test message')
      store.markSending(msg.id)
      const result = store.remove(msg.id)
      
      expect(result).toBe(false)
    })
    
    it('should clear queue keeping sending messages', () => {
      store.enqueue('Pending 1')
      store.enqueue('Pending 2')
      const sendingMsg = store.enqueue('Sending')
      store.markSending(sendingMsg.id)
      
      store.clear()
      
      expect(store.items.length).toBe(1)
      expect(store.items[0].id).toBe(sendingMsg.id)
    })
  })
  
  describe('computed properties', () => {
    it('should count pending messages', () => {
      store.enqueue('Pending 1')
      store.enqueue('Pending 2')
      // 第三条也必须保持 pending：pendingCount 数的是收集态，
      // 入队即变 sending/sent 会与 enqueue 契约（只入队、不代发）冲突。
      store.enqueue('Sent', undefined, {})
      
      expect(store.pendingCount).toBe(3)
    })
    
    it('should count failed messages', () => {
      const msg = store.enqueue('Failed')
      store.markFailed(msg.id, 'Error')
      
      expect(store.failedCount).toBe(1)
    })
    
    it('should group pending by session', () => {
      store.enqueue('Session A', 'session-a')
      store.enqueue('Session A again', 'session-a')
      store.enqueue('Session B', 'session-b')
      
      expect(store.pendingBySession.size).toBe(2)
      expect(store.pendingBySession.get('session-a')?.length).toBe(2)
      expect(store.pendingBySession.get('session-b')?.length).toBe(1)
    })
    
    it('should sort prioritized queue by priority and time', () => {
      store.enqueue('Low priority', undefined, { priority: 1 })
      store.enqueue('High priority', undefined, { priority: 10 })
      store.enqueue('Medium priority', undefined, { priority: 5 })
      
      const sorted = store.prioritizedQueue
      expect(sorted[0].text).toBe('High priority')
      expect(sorted[1].text).toBe('Medium priority')
      expect(sorted[2].text).toBe('Low priority')
    })
  })
  
  describe('control actions', () => {
    it('should pause queue processing', () => {
      store.setPaused(true)
      expect(store.paused).toBe(true)
    })
    
    it('should toggle pause state', () => {
      store.togglePause()
      expect(store.paused).toBe(true)
      
      store.togglePause()
      expect(store.paused).toBe(false)
    })
    
    it('should configure sync settings', () => {
      store.configure({
        maxBatchSize: 20,
        syncIntervalMs: 10000,
      })
      
      expect(store.syncConfig.maxBatchSize).toBe(20)
      expect(store.syncConfig.syncIntervalMs).toBe(10000)
    })
  })
  
  describe('statistics', () => {
    it('should provide comprehensive statistics', () => {
      const msg1 = store.enqueue('Message 1')
      const msg2 = store.enqueue('Message 2')
      store.markSent(msg1.id)
      store.markFailed(msg2.id, 'Error')
      store.retry(msg2.id)
      
      const stats = store.getStatistics()
      
      expect(stats.totalEnqueued).toBe(2)
      expect(stats.totalSent).toBe(1)
      expect(stats.totalRetried).toBe(1)
      // retry 后回到 pending（尚未再失败），故 failed 计数为 0；
      // failedCount 是「当前失败态」读数，不是历史失败次数（后者在 totalFailed）。
      expect(stats.current.pending).toBe(1)
      expect(stats.current.failed).toBe(0)
    })
  })
  
  describe('cleanup', () => {
    it('should remove expired messages', () => {
      const recent = store.enqueue('Recent', undefined, { ttlMs: 60000 })
      const expired = store.enqueue('Expired', undefined, { ttlMs: 1 })
      
      // Wait for expiration
      vi.useFakeTimers()
      vi.advanceTimersByTime(100)
      
      const removed = store.cleanupExpired()
      
      expect(removed).toBe(1)
      expect(store.items.length).toBe(1)
      expect(store.items[0].id).toBe(recent.id)
      
      vi.useRealTimers()
    })
    
    it('should not remove non-expired messages', () => {
      const msg = store.enqueue('Not expired', undefined, { ttlMs: 60000 })
      
      const removed = store.cleanupExpired()
      
      expect(removed).toBe(0)
      expect(store.items.length).toBe(1)
    })
  })
  
  describe('persistence', () => {
    it('should save to localStorage', () => {
      store.enqueue('Test message')
      
      expect(global.localStorage.setItem).toHaveBeenCalledWith(
        'neurova_message_queue',
        expect.any(String)
      )
    })
    
    it('should restore from localStorage', () => {
      const mockData = JSON.stringify([
        {
          id: 'test-1',
          text: 'Restored message',
          enqueuedAt: new Date().toISOString(),
          status: 'pending',
          sessionId: 'session-1',
        },
      ])
      
      localStorageMock['neurova_message_queue'] = mockData
      
      store.restoreFromStorage()
      
      expect(store.items.length).toBe(1)
      expect(store.items[0].text).toBe('Restored message')
    })
  })
  
  describe('reset', () => {
    it('should reset all state', () => {
      store.enqueue('Message 1')
      store.enqueue('Message 2')
      store.markSent('q123-456')
      
      store.reset()
      
      expect(store.items.length).toBe(0)
      expect(store.paused).toBe(false)
      expect(store.isSyncing).toBe(false)
      expect(store.stats.totalEnqueued).toBe(0)
      expect(store.stats.totalSent).toBe(0)
    })
  })
})
