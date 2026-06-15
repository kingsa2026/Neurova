import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useNotificationStore } from '@/stores/notifications'

vi.mock('@/api/modules/notifications', () => ({
  getNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  deleteNotification: vi.fn(),
}))

import { getNotifications, getUnreadCount, markRead, markAllRead, deleteNotification } from '@/api/modules/notifications'

describe('useNotificationStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts with empty state', () => {
    const store = useNotificationStore()
    expect(store.notifications).toEqual([])
    expect(store.unreadTotal).toBe(0)
    expect(store.hasUnread).toBe(false)
  })

  it('fetchNotifications loads items', async () => {
    vi.mocked(getNotifications).mockResolvedValue({
      data: { items: [{ id: '1', title: 'Test', read: false }], total: 1 },
    } as any)

    const store = useNotificationStore()
    await store.fetchNotifications()

    expect(store.notifications).toHaveLength(1)
    expect(store.total).toBe(1)
    expect(store.loading).toBe(false)
  })

  it('fetchUnreadCount updates badge', async () => {
    vi.mocked(getUnreadCount).mockResolvedValue({
      data: { total: 5, info: 2, warning: 1, error: 1, success: 1 },
    } as any)

    const store = useNotificationStore()
    await store.fetchUnreadCount()

    expect(store.unreadTotal).toBe(5)
    expect(store.hasUnread).toBe(true)
  })

  it('markAsRead updates notification and badge', async () => {
    vi.mocked(markRead).mockResolvedValue({} as any)
    vi.mocked(getUnreadCount).mockResolvedValue({
      data: { total: 4, info: 1, warning: 1, error: 1, success: 1 },
    } as any)

    const store = useNotificationStore()
    store.notifications = [{ id: '1', title: 'Test', read: false }] as any

    await store.markAsRead('1')

    expect(store.notifications[0].read).toBe(true)
  })

  it('markAllAsRead clears all unread', async () => {
    vi.mocked(markAllRead).mockResolvedValue({} as any)

    const store = useNotificationStore()
    store.notifications = [
      { id: '1', title: 'A', read: false },
      { id: '2', title: 'B', read: false },
    ] as any

    await store.markAllAsRead()

    expect(store.notifications.every((n) => n.read)).toBe(true)
    expect(store.unreadCounts.total).toBe(0)
  })

  it('remove deletes notification', async () => {
    vi.mocked(deleteNotification).mockResolvedValue({} as any)
    vi.mocked(getUnreadCount).mockResolvedValue({
      data: { total: 0, info: 0, warning: 0, error: 0, success: 0 },
    } as any)

    const store = useNotificationStore()
    store.notifications = [
      { id: '1', title: 'A', read: false },
      { id: '2', title: 'B', read: false },
    ] as any

    await store.remove('1')

    expect(store.notifications).toHaveLength(1)
    expect(store.notifications[0].id).toBe('2')
  })
})
