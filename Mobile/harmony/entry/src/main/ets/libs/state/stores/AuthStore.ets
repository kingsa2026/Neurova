/**
 * AuthStore - 认证状态存储
 *
 * 凭证按 serverId 分仓，并与该档案的规范化 origin 绑定。
 * access_token 仅内存；refresh_token / wsToken / pairingId / deviceSecret 沿用既有
 * StorageAdapter 持久化，不引入新的明文存储。切换档案立即摘除 HttpClient bearer，
 * 只有协议、主机、端口完全匹配时才重新装配。
 */
import { StateManager } from '../StateManager';
import { User, AuthTokens } from '../../types';
import { EventBus } from '../../bus/EventBus';
import { HttpClient } from '../../api/HttpClient';
import { AuthApi } from '../../api/modules/AuthApi';
import { StorageAdapter } from '../../adapters/StorageAdapter';
import { Logger } from '../../logger/Logger';
import { ServerProfiles, ServerProfile } from '../../config/ServerProfiles';

const KEY_ACCESS_TOKEN = 'auth:access_token';
const KEY_REFRESH_TOKEN = 'auth:refresh_token';
const KEY_USER = 'auth:user';
const KEY_WS_TOKEN = 'auth:ws_token';
const KEY_WS_URL = 'auth:ws_url';
const KEY_DEVICE_SECRET = 'auth:device_secret';
const KEY_PAIRING_ID = 'auth:pairing_id';
const LEGACY_KEYS: string[] = [
  KEY_ACCESS_TOKEN, KEY_REFRESH_TOKEN, KEY_USER, KEY_WS_TOKEN, KEY_WS_URL, KEY_DEVICE_SECRET, KEY_PAIRING_ID,
];

interface ServerCredentialSnapshot {
  origin: string;
  refreshToken: string;
  wsToken: string;
  wsUrl: string;
  pairingId: string;
  deviceSecret: string;
}

/** URL origin 单源：忽略路径/query，保留协议、小写主机与显式端口；默认端口归一。 */
function normalizeOrigin(raw: string): string {
  const match = /^(https?):\/\/([^/?#]+)(?:[/?#]|$)/i.exec(raw.trim());
  if (!match) return '';
  const scheme = match[1].toLowerCase();
  const authority = match[2].slice(match[2].lastIndexOf('@') + 1);
  let host = '';
  let portText = '';
  if (authority.startsWith('[')) {
    const end = authority.indexOf(']');
    if (end < 0) return '';
    host = authority.slice(0, end + 1).toLowerCase();
    const rest = authority.slice(end + 1);
    if (rest.length > 0) {
      if (!rest.startsWith(':')) return '';
      portText = rest.slice(1);
    }
  } else {
    const colon = authority.indexOf(':');
    if (colon >= 0) {
      if (authority.indexOf(':', colon + 1) >= 0) return '';
      host = authority.slice(0, colon).toLowerCase();
      portText = authority.slice(colon + 1);
    } else {
      host = authority.toLowerCase();
    }
  }
  if (host.length === 0) return '';
  const defaultPort = scheme === 'https' ? 443 : 80;
  let port = defaultPort;
  if (portText.length > 0) {
    if (!/^\d+$/.test(portText)) return '';
    port = Number(portText);
    if (port < 1 || port > 65535) return '';
  }
  return `${scheme}://${host}:${port}`;
}

function scopedKey(serverId: string, field: string): string {
  return `auth:server:${encodeURIComponent(serverId)}:${field}`;
}

export class AuthStore {
  private static guardedClient: HttpClient | null = null;
  private state: StateManager = StateManager.getInstance();
  private bus: EventBus = EventBus.getInstance();
  private storage: StorageAdapter = StorageAdapter.getInstance();
  private logger: Logger = Logger.getInstance();
  private activeServerId: string = '';
  private activeOrigin: string = '';

  constructor() {
    this.installHttpGuard();
  }

  private installHttpGuard(): void {
    const client = HttpClient.getInstance();
    if (AuthStore.guardedClient === client) return;
    client.addInterceptor({
      before: (headers: Record<string, string>) => { this.applyOriginGuard(headers); },
    });
    AuthStore.guardedClient = client;
  }

  /** 在每次请求头装配前复核当前档案与 HTTP baseUrl；失配立即摘除 bearer。 */
  private applyOriginGuard(headers: Record<string, string>): void {
    const token = this.currentCredential('access_token');
    const requestOrigin = normalizeOrigin(HttpClient.getInstance().getBaseUrl());
    const serverId = this.resolveServerId();
    const allowed = serverId.length > 0 && this.activeOrigin.length > 0 &&
      requestOrigin === this.activeOrigin && token.length > 0;
    if (allowed) {
      headers['Authorization'] = `Bearer ${token}`;
      HttpClient.getInstance().setToken(token);
    } else {
      delete headers['Authorization'];
      HttpClient.getInstance().setToken('');
    }
  }

  private resolveServerId(): string {
    const active = ServerProfiles.getInstance().getActive();
    if (active) {
      const origin = normalizeOrigin(active.baseUrl);
      if (active.id !== this.activeServerId || origin !== this.activeOrigin) {
        this.activeServerId = active.id;
        this.activeOrigin = origin;
        this.syncHttpToken();
      }
    } else if (this.activeServerId.length > 0 || this.activeOrigin.length > 0) {
      this.activeServerId = '';
      this.activeOrigin = '';
      this.syncHttpToken();
    }
    return this.activeServerId;
  }

  /** 内存 origin 元数据必须与当前档案一致，避免同 serverId 改地址时沿用旧 token。 */
  private originMatches(serverId: string): boolean {
    return serverId.length > 0 && this.activeOrigin.length > 0 &&
      this.state.get<string>(scopedKey(serverId, 'origin'), '') === this.activeOrigin;
  }

  private currentCredential(field: string): string {
    const serverId = this.resolveServerId();
    if (!this.originMatches(serverId)) return '';
    return this.state.get<string>(scopedKey(serverId, field), '');
  }

  private syncHttpToken(): void {
    const client = HttpClient.getInstance();
    const token = this.activeServerId.length > 0 && this.originMatches(this.activeServerId)
      ? this.state.get<string>(scopedKey(this.activeServerId, 'access_token'), '') : '';
    if (token.length > 0 && normalizeOrigin(client.getBaseUrl()) === this.activeOrigin) {
      client.setToken(token);
    } else {
      client.setToken('');
    }
  }

  private targetBinding(serverId: string, origin: string): { serverId: string, origin: string } {
    const activeId = this.resolveServerId();
    const targetId = serverId.length > 0 ? serverId : activeId;
    const targetOrigin = origin.length > 0 ? normalizeOrigin(origin)
      : (targetId === activeId ? this.activeOrigin : normalizeOrigin(HttpClient.getInstance().getBaseUrl()));
    if (targetId.length === 0 || targetOrigin.length === 0) {
      throw new Error('尚未绑定终端档案，不能写入或读取凭证');
    }
    return { serverId: targetId, origin: targetOrigin };
  }

  get accessToken(): string {
    return this.currentCredential('access_token');
  }

  get refreshToken(): string {
    return this.currentCredential('refresh_token');
  }

  get user(): User | undefined {
    const id = this.resolveServerId();
    return this.originMatches(id) ? this.state.get<User>(scopedKey(id, 'user')) : undefined;
  }

  get isAuthenticated(): boolean {
    return this.accessToken.length > 0;
  }

  get wsToken(): string {
    return this.currentCredential('ws_token');
  }

  get wsUrl(): string {
    return this.currentCredential('ws_url');
  }

  get isPaired(): boolean {
    return this.wsToken.length > 0;
  }

  get deviceSecret(): string {
    return this.currentCredential('device_secret');
  }

  get pairingId(): string {
    return this.currentCredential('pairing_id');
  }

  private persist(key: string, value: string): void {
    this.storage.set<string>(key, value).catch((e: Error) => {
      this.logger.error('AuthStore', `持久化 ${key} 失败`, e);
    });
  }

  private unpersist(key: string): void {
    this.storage.remove(key).catch((e: Error) => {
      this.logger.error('AuthStore', `清除 ${key} 失败`, e);
    });
  }

  /** 旧全局凭证无法证明属于哪台服务器，切换/恢复时淘汰，不做迁移。 */
  private clearLegacyCredentials(): void {
    LEGACY_KEYS.forEach((key: string) => {
      this.state.remove(key);
      this.unpersist(key);
    });
  }

  /** 切换前同步摘 token；随后只恢复目标 serverId 且 origin 相符的持久化凭证。 */
  async activateServer(serverId: string, baseUrl: string): Promise<void> {
    HttpClient.getInstance().setToken('');
    this.clearLegacyCredentials();
    if (serverId.length === 0) {
      this.activeServerId = '';
      this.activeOrigin = '';
      return;
    }
    const origin = normalizeOrigin(baseUrl);
    if (origin.length === 0) throw new Error('终端地址非法');
    this.activeServerId = serverId;
    this.activeOrigin = origin;
    this.syncHttpToken();
    await this.loadServerCredentials(serverId, origin);
  }

  private async loadServerCredentials(serverId: string, origin: string): Promise<void> {
    await this.storage.flush();
    const snapshot: ServerCredentialSnapshot = {
      origin: await this.storage.get<string>(scopedKey(serverId, 'origin'), ''),
      refreshToken: await this.storage.get<string>(scopedKey(serverId, 'refresh_token'), ''),
      wsToken: await this.storage.get<string>(scopedKey(serverId, 'ws_token'), ''),
      wsUrl: await this.storage.get<string>(scopedKey(serverId, 'ws_url'), ''),
      pairingId: await this.storage.get<string>(scopedKey(serverId, 'pairing_id'), ''),
      deviceSecret: await this.storage.get<string>(scopedKey(serverId, 'device_secret'), ''),
    };
    if (this.activeServerId !== serverId || this.activeOrigin !== origin) return;
    if (snapshot.origin.length === 0 || snapshot.origin !== origin) {
      if (snapshot.origin.length > 0) this.clearServerCredentials(serverId, true);
      return;
    }
    this.setOrRemove(scopedKey(serverId, 'refresh_token'), snapshot.refreshToken);
    this.setOrRemove(scopedKey(serverId, 'ws_token'), snapshot.wsToken);
    this.setOrRemove(scopedKey(serverId, 'ws_url'), snapshot.wsUrl);
    this.setOrRemove(scopedKey(serverId, 'pairing_id'), snapshot.pairingId);
    this.setOrRemove(scopedKey(serverId, 'device_secret'), snapshot.deviceSecret);
    this.state.set(scopedKey(serverId, 'origin'), snapshot.origin);
    this.syncHttpToken();
  }

  private setOrRemove(key: string, value: string): void {
    if (value.length > 0) this.state.set(key, value);
    else this.state.remove(key);
  }

  setTokens(tokens: AuthTokens, serverId: string = '', origin: string = ''): void {
    const target = this.targetBinding(serverId, origin);
    this.state.set(scopedKey(target.serverId, 'access_token'), tokens.access_token);
    this.state.set(scopedKey(target.serverId, 'refresh_token'), tokens.refresh_token);
    this.state.set(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'refresh_token'), tokens.refresh_token);
    if (target.serverId === this.activeServerId) this.syncHttpToken();
  }

  setUser(user: User): void {
    const id = this.resolveServerId();
    if (id.length === 0) return;
    this.state.set(scopedKey(id, 'user'), user);
    this.bus.emit('user:login', user);
  }

  setWsPairing(wsToken: string, wsUrl: string, serverId: string = '', origin: string = ''): void {
    const target = this.targetBinding(serverId, origin);
    this.state.set(scopedKey(target.serverId, 'ws_token'), wsToken);
    this.state.set(scopedKey(target.serverId, 'ws_url'), wsUrl);
    this.state.set(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'ws_token'), wsToken);
    this.persist(scopedKey(target.serverId, 'ws_url'), wsUrl);
    if (target.serverId === this.activeServerId) {
      const payload: PairingSuccessPayload = { wsToken, wsUrl };
      this.bus.emit('pairing:success', payload);
    }
  }

  setDeviceIdentity(pairingId: string, deviceSecret: string, serverId: string = '', origin: string = ''): void {
    const target = this.targetBinding(serverId, origin);
    this.state.set(scopedKey(target.serverId, 'pairing_id'), pairingId);
    this.state.set(scopedKey(target.serverId, 'device_secret'), deviceSecret);
    this.state.set(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'origin'), target.origin);
    this.persist(scopedKey(target.serverId, 'pairing_id'), pairingId);
    this.persist(scopedKey(target.serverId, 'device_secret'), deviceSecret);
  }

  /** 冷启动只恢复当前档案；持久化 origin 与档案不一致时清除该仓，不拿旧 token 续签。 */
  async restore(): Promise<void> {
    const serverId = this.resolveServerId();
    HttpClient.getInstance().setToken('');
    this.clearLegacyCredentials();
    if (serverId.length === 0) return;
    const origin = this.activeOrigin;
    await this.loadServerCredentials(serverId, origin);
    if (this.activeServerId !== serverId || this.activeOrigin !== origin) return;
    if (this.accessToken.length > 0) return;
    const refreshToken = this.refreshToken;
    if (refreshToken.length === 0) return;
    const api = new AuthApi(HttpClient.getInstance());
    try {
      const refreshed = await api.refresh(refreshToken);
      if (this.activeServerId !== serverId || this.activeOrigin !== origin) return;
      if (refreshed.code !== 0 || !refreshed.data) {
        this.clearServerCredentials(serverId, false);
        return;
      }
      this.setTokens(refreshed.data, serverId, origin);
      const me = await api.me();
      if (this.activeServerId === serverId && me.code === 0 && me.data) this.setUser(me.data);
    } catch (e) {
      this.logger.error('AuthStore', '冷启动续签失败，清除本地凭证', e as Error);
      this.clearServerCredentials(serverId, false);
    }
  }

  private clearServerCredentials(serverId: string, includePairing: boolean): void {
    const fields: string[] = ['access_token', 'refresh_token', 'user'];
    if (includePairing) fields.push('ws_token', 'ws_url', 'pairing_id', 'device_secret', 'origin');
    fields.forEach((field: string) => {
      const key = scopedKey(serverId, field);
      this.state.remove(key);
      this.unpersist(key);
    });
    if (serverId === this.activeServerId) this.syncHttpToken();
  }

  /** 删除档案时调用：清掉该 serverId 的内存与持久化凭证。 */
  forgetServer(serverId: string): void {
    this.clearServerCredentials(serverId, true);
  }

  /** 登出保持既有全终端、同步内存清理与 fail-soft 持久化语义。 */
  logout(): void {
    const ids: Set<string> = new Set<string>();
    const activeId = this.resolveServerId();
    if (activeId.length > 0) ids.add(activeId);
    ServerProfiles.getInstance().getList().forEach((p: ServerProfile) => { ids.add(p.id); });
    HttpClient.getInstance().setToken('');
    this.clearLegacyCredentials();
    for (const id of ids) this.clearServerCredentials(id, true);
    this.bus.emit('user:logout', new Object());
  }
}

/** 配对成功事件载荷 */
export interface PairingSuccessPayload {
  wsToken: string;
  wsUrl: string;
}
