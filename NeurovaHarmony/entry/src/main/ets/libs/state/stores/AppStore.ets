/**
 * AppStore - 应用级状态
 *
 * 管理：theme、language、sidebarCollapsed、onlineStatus
 */
import { StateManager } from '../StateManager';
import { EventBus } from '../bus/EventBus';

const KEY_THEME = 'app:theme';        // 'light' | 'dark'
const KEY_LANGUAGE = 'app:language';  // 'zh-CN' | 'en-US' | ...
const KEY_SIDEBAR_COLLAPSED = 'app:sidebar_collapsed';
const KEY_ONLINE = 'app:online';

export class AppStore {
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();

  get theme(): 'light' | 'dark' {
    return this.state.get<'light' | 'dark'>(KEY_THEME, 'light');
  }

  setTheme(theme: 'light' | 'dark'): void {
    this.state.set(KEY_THEME, theme);
    this.bus.emit('theme:changed', theme);
  }

  toggleTheme(): void {
    this.setTheme(this.theme === 'light' ? 'dark' : 'light');
  }

  get language(): string {
    return this.state.get<string>(KEY_LANGUAGE, 'zh-CN');
  }

  setLanguage(lang: string): void {
    this.state.set(KEY_LANGUAGE, lang);
    this.bus.emit('language:changed', lang);
  }

  get sidebarCollapsed(): boolean {
    return this.state.get<boolean>(KEY_SIDEBAR_COLLAPSED, false);
  }

  setSidebarCollapsed(collapsed: boolean): void {
    this.state.set(KEY_SIDEBAR_COLLAPSED, collapsed);
  }

  get isOnline(): boolean {
    return this.state.get<boolean>(KEY_ONLINE, true);
  }

  setOnline(online: boolean): void {
    this.state.set(KEY_ONLINE, online);
    this.bus.emit('network:status', { online });
  }
}
