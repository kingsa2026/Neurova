/**
 * AuthStore - 认证状态存储（P1-36：凭证持久化）
 *
 * 管理：access_token、refresh_token、当前 user 对象、移动端配对下发的 wsToken/wsUrl、
 *   长期设备身份（pairingId/deviceSecret）
 * 持久化策略（经 StorageAdapter → @kit.ArkData preferences 落盘）：
 *   - refresh_token / wsToken / wsUrl / pairingId / deviceSecret：**持久化**——
 *     冷启动恢复，配对关系与续签凭证重启不丢；
 *   - access_token：**内存优先**——不落盘，冷启动用 refresh_token 走 /auth/refresh 续签；
 *   - user：不落盘——续签后经 /auth/me 回填。
 * 行为：login / logout / isAuthenticated / isPaired / restore
 */
import { StateManager } from '../StateManager';
import { User, AuthTokens } from '../../types';
import { EventBus } from '../../bus/EventBus';
import { HttpClient } from '../../api/HttpClient';
import { AuthApi } from '../../api/modules/AuthApi';
import { StorageAdapter } from '../../adapters/StorageAdapter';
import { Logger } from '../../logger/Logger';

const KEY_ACCESS_TOKEN = 'auth:access_token';
const KEY_REFRESH_TOKEN = 'auth:refresh_token';
const KEY_USER = 'auth:user';
// 移动端配对成功后下发的 WebSocket 凭证
const KEY_WS_TOKEN = 'auth:ws_token';
const KEY_WS_URL = 'auth:ws_url';
// 长期设备身份（refresh 续签用，设计方案 §4.7）
const KEY_DEVICE_SECRET = 'auth:device_secret';
const KEY_PAIRING_ID = 'auth:pairing_id';

export class AuthStore {
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private storage: StorageAdapter = StorageAdapter.getInstance();
  private logger: Logger = Logger.getInstance();

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

  /** 长期设备身份密钥（confirm 一次性下发；refresh 续签凭证用） */
  get deviceSecret(): string {
    return this.state.get<string>(KEY_DEVICE_SECRET, '');
  }

  /** 在册设备 ID（refresh 续签必须携带） */
  get pairingId(): string {
    return this.state.get<string>(KEY_PAIRING_ID, '');
  }

  /** 持久化写穿（失败经 ErrorManager 上报，不阻断内存态——存储故障时退化为内存会话） */
  private persist(key: string, value: string): void {
    this.storage.set<string>(key, value).catch((e: Error) => {
      this.logger.error('AuthStore', `持久化 ${key} 失败`, e);
    });
  }

  /** 持久化删除（同上，失败不阻断） */
  private unpersist(key: string): void {
    this.storage.remove(key).catch((e: Error) => {
      this.logger.error('AuthStore', `清除 ${key} 失败`, e);
    });
  }

  /** 写入长期设备身份（confirm 成功后调用；登出/解除配对时清除） */
  setDeviceIdentity(pairingId: string, deviceSecret: string): void {
    this.state.set(KEY_PAIRING_ID, pairingId);
    this.state.set(KEY_DEVICE_SECRET, deviceSecret);
    this.persist(KEY_PAIRING_ID, pairingId);
    this.persist(KEY_DEVICE_SECRET, deviceSecret);
  }

  /** 设置 tokens（登录成功后调用）；token 同步落 HttpClient 装配点，否则带凭证请求裸奔（me() 401 根因） */
  setTokens(tokens: AuthTokens): void {
    this.state.set(KEY_ACCESS_TOKEN, tokens.access_token);
    this.state.set(KEY_REFRESH_TOKEN, tokens.refresh_token);
    HttpClient.getInstance().setToken(tokens.access_token);
    this.persist(KEY_REFRESH_TOKEN, tokens.refresh_token);
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
    this.persist(KEY_WS_TOKEN, wsToken);
    this.persist(KEY_WS_URL, wsUrl);
    const payload: PairingSuccessPayload = { wsToken, wsUrl };
    this.bus.emit('pairing:success', payload);
  }

  /**
   * 冷启动恢复（P1-36）：先回填持久化凭证，再按需续签。
   * - 持久化凭证（refresh_token/wsToken/wsUrl/pairingId/deviceSecret）回填内存；
   * - access_token 内存优先：内存没有时用 refresh_token 走 /auth/refresh 换新，
   *   并经 /auth/me 回填用户；续签失败（过期/被吊销）→ 清除本地凭证回登录页。
   * 必须在 StorageAdapter.init(context) 之后调用。
   */
  async restore(): Promise<void> {
    try {
      const refreshToken = await this.storage.get<string>(KEY_REFRESH_TOKEN, '');
      const wsToken = await this.storage.get<string>(KEY_WS_TOKEN, '');
      const wsUrl = await this.storage.get<string>(KEY_WS_URL, '');
      const pairingId = await this.storage.get<string>(KEY_PAIRING_ID, '');
      const deviceSecret = await this.storage.get<string>(KEY_DEVICE_SECRET, '');
      if (refreshToken.length > 0) this.state.set(KEY_REFRESH_TOKEN, refreshToken);
      if (wsToken.length > 0) this.state.set(KEY_WS_TOKEN, wsToken);
      if (wsUrl.length > 0) this.state.set(KEY_WS_URL, wsUrl);
      if (pairingId.length > 0) this.state.set(KEY_PAIRING_ID, pairingId);
      if (deviceSecret.length > 0) this.state.set(KEY_DEVICE_SECRET, deviceSecret);
    } catch (e) {
      // 存储不可用：按无持久化处理（退回登录链路），不吞成静默成功
      this.logger.error('AuthStore', '冷启动恢复读取持久化凭证失败', e as Error);
      return;
    }

    if (this.accessToken.length > 0) {
      return; // 进程内已有 access_token（热启动），无需续签
    }
    const refreshToken = this.refreshToken;
    if (refreshToken.length === 0) {
      return; // 无任何凭证：未登录，走登录页
    }
    const api = new AuthApi(HttpClient.getInstance());
    try {
      const refreshed = await api.refresh(refreshToken);
      if (refreshed.code !== 0 || !refreshed.data) {
        this.clearPersistedCredentials();
        return;
      }
      this.setTokens(refreshed.data);
      const me = await api.me();
      if (me.code === 0 && me.data) {
        this.setUser(me.data);
      }
    } catch (e) {
      this.logger.error('AuthStore', '冷启动续签失败，清除本地凭证', e as Error);
      this.clearPersistedCredentials();
    }
  }

  /** 清除全部凭证（内存 + 持久化；续签失败/登出共用） */
  private clearPersistedCredentials(): void {
    this.state.remove(KEY_ACCESS_TOKEN);
    this.state.remove(KEY_REFRESH_TOKEN);
    this.state.remove(KEY_USER);
    this.unpersist(KEY_REFRESH_TOKEN);
    HttpClient.getInstance().setToken('');
  }

  /** 登出：清除所有认证状态（内存 + 持久化，含 HttpClient 装配点的 token） */
  logout(): void {
    this.state.remove(KEY_ACCESS_TOKEN);
    this.state.remove(KEY_REFRESH_TOKEN);
    this.state.remove(KEY_USER);
    this.state.remove(KEY_WS_TOKEN);
    this.state.remove(KEY_WS_URL);
    this.state.remove(KEY_DEVICE_SECRET);
    this.state.remove(KEY_PAIRING_ID);
    this.unpersist(KEY_REFRESH_TOKEN);
    this.unpersist(KEY_WS_TOKEN);
    this.unpersist(KEY_WS_URL);
    this.unpersist(KEY_DEVICE_SECRET);
    this.unpersist(KEY_PAIRING_ID);
    HttpClient.getInstance().setToken('');
    this.bus.emit('user:logout', new Object());
  }
}

/** 配对成功事件载荷 */
export interface PairingSuccessPayload {
  wsToken: string;
  wsUrl: string;
}
