import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getNotifications, getUnreadCount, markRead, markAllRead, deleteNotification } from '@/api/modules/notifications'
import type { Notification, UnreadCount } from '@/api/modules/notifications'

/**
 * Global notification store for badge counts and quick-access notification list.
 * Used by the layout header for the notification bell icon.
 */
export const useNotificationStore = defineStore('notifications', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const notifications = ref<Notification[]>([])
  const unreadCounts = ref<UnreadCount>({ total: 0, info: 0, warning: 0, error: 0, success: 0 })
  const loading = ref(false)
  const total = ref(0)
  const page = ref(1)
  const size = ref(20)

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const unreadTotal = computed(() => unreadCounts.value.total)
  const hasUnread = computed(() => unreadCounts.value.total > 0)

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /** Fetch notification list (first page). */
  async function fetchNotifications(p = 1) {
    loading.value = true
    page.value = p
    try {
      const res = await getNotifications({ page: p, size: size.value })
      notifications.value = res.data.items
      total.value = res.data.total
    } catch (e) {
      console.error('[NotificationStore] fetchNotifications failed', e)
    } finally {
      loading.value = false
    }
  }

  /** Refresh unread badge counts. */
  async function fetchUnreadCount() {
    try {
      const res = await getUnreadCount()
      unreadCounts.value = res.data
    } catch {
      // Silent fail for badge — not critical
    }
  }

  /** Mark a single notification as read. */
  async function markAsRead(id: string) {
    try {
      await markRead(id)
      const n = notifications.value.find((n) => n.id === id)
      if (n) n.read = true
      await fetchUnreadCount()
    } catch (e) {
      console.error('[NotificationStore] markRead failed', e)
    }
  }

  /** Mark all as read. */
  async function markAllAsRead() {
    try {
      await markAllRead()
      notifications.value.forEach((n) => (n.read = true))
      unreadCounts.value.total = 0
    } catch (e) {
      console.error('[NotificationStore] markAllRead failed', e)
    }
  }

  /** Delete a notification. */
  async function remove(id: string) {
    try {
      await deleteNotification(id)
      notifications.value = notifications.value.filter((n) => n.id !== id)
      await fetchUnreadCount()
    } catch (e) {
      console.error('[NotificationStore] delete failed', e)
    }
  }

  return {
    notifications,
    unreadCounts,
    loading,
    total,
    page,
    size,
    unreadTotal,
    hasUnread,
    fetchNotifications,
    fetchUnreadCount,
    markAsRead,
    markAllAsRead,
    remove,
  }
})
