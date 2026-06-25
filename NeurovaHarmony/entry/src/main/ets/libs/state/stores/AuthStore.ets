/**
 * AuthStore - 认证状态存储
 *
 * 管理：access_token、refresh_token、当前 user 对象、移动端配对下发的 wsToken/wsUrl
 * 行为：login / logout / isAuthenticated / isPaired
 */
import { StateManager } from '../StateManager';
import { User, AuthTokens } from '../../types';
import { EventBus } from '../bus/EventBus';

const KEY_ACCESS_TOKEN = 'auth:access_token';
const KEY_REFRESH_TOKEN = 'auth:refresh_token';
const KEY_USER = 'auth:user';
// 移动端配对成功后下发的 WebSocket 凭证
const KEY_WS_TOKEN = 'auth:ws_token';
const KEY_WS_URL = 'auth:ws_url';

export class AuthStore {
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();

  get accessToken(): string {
    return this.state.get<string>(KEY_ACCESS_TOKEN, '');
  }

  get refreshToken(): string {
    return this.state.get<string>(KEY_REFRESH_TOKEN, '');
  }

  get user(): User | undefined {
    return this.state.get<User>(KEY_USER);
  }

  get isAuthenticated(): boolean {
    return !!this.accessToken;
  }

  /** 配对成功后下发的 WebSocket 连接 token（未配对时为空串） */
  get wsToken(): string {
    return this.state.get<string>(KEY_WS_TOKEN, '');
  }

  /** 配对成功后下发的 WebSocket 连接 URL（未配对时为空串） */
  get wsUrl(): string {
    return this.state.get<string>(KEY_WS_URL, '');
  }

  /** 是否已完成移动端配对（wsToken 存在即视为已配对） */
  get isPaired(): boolean {
    return !!this.wsToken;
  }

  /** 设置 tokens（登录成功后调用） */
  setTokens(tokens: AuthTokens): void {
    this.state.set(KEY_ACCESS_TOKEN, tokens.access_token);
    this.state.set(KEY_REFRESH_TOKEN, tokens.refresh_token);
  }

  /** 设置当前用户 */
  setUser(user: User): void {
    this.state.set(KEY_USER, user);
    this.bus.emit('user:login', user);
  }

  /**
   * 写入移动端配对成功后的 WebSocket 凭证
   * 由 PairingPage 在 mobilePairing.confirm 成功后调用
   */
  setWsPairing(wsToken: string, wsUrl: string): void {
    this.state.set(KEY_WS_TOKEN, wsToken);
    this.state.set(KEY_WS_URL, wsUrl);
    this.bus.emit('pairing:success', { wsToken, wsUrl } as Object);
  }

  /** 登出：清除所有认证状态 */
  logout(): void {
    this.state.remove(KEY_ACCESS_TOKEN);
    this.state.remove(KEY_REFRESH_TOKEN);
    this.state.remove(KEY_USER);
    this.state.remove(KEY_WS_TOKEN);
    this.state.remove(KEY_WS_URL);
    this.bus.emit('user:logout', {});
  }
}
