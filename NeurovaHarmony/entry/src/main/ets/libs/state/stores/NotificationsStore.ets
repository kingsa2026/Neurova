/**
 * NotificationsStore - 通知列表状态
 */
import { StateManager } from '../StateManager';
import { EventBus } from '../bus/EventBus';

const KEY_NOTIFICATIONS = 'notifications:list';
const KEY_UNREAD_COUNT = 'notifications:unread';

export interface AppNotification {
  id: string;
  title: string;
  body: string;
  type: 'info' | 'success' | 'warning' | 'error';
  read: boolean;
  createdAt: number;
}

export class NotificationsStore {
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();

  get notifications(): AppNotification[] {
    return this.state.get<AppNotification[]>(KEY_NOTIFICATIONS, []);
  }

  get unreadCount(): number {
    return this.state.get<number>(KEY_UNREAD_COUNT, 0);
  }

  add(notification: AppNotification): void {
    const list = [notification, ...this.notifications];
    this.state.set(KEY_NOTIFICATIONS, list);
    if (!notification.read) {
      this.state.set(KEY_UNREAD_COUNT, this.unreadCount + 1);
    }
    this.bus.emit('notification:show', notification);
  }

  markAsRead(id: string): void {
    const list = this.notifications.map(n => n.id === id ? { ...n, read: true } : n);
    this.state.set(KEY_NOTIFICATIONS, list);
    this.state.set(KEY_UNREAD_COUNT, Math.max(0, this.unreadCount - 1));
  }

  clear(): void {
    this.state.set(KEY_NOTIFICATIONS, []);
    this.state.set(KEY_UNREAD_COUNT, 0);
  }
}
