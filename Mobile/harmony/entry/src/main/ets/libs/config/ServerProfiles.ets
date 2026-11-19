/**
 * ServerProfiles - 终端档案（多终端，设计方案 §4.5，已裁 D4）
 *
 * 每台 Neurova 服务端一条档案；切换档案后须重新登录（账号与 token 不跨档案共享）。
 * 持久化：@kit.ArkData preferences（单条 JSON 串）。
 * 与 ConfigManager 的关系：本库只管"有哪些终端、当前用哪台"；
 * 切换后由调用方把 active.baseUrl 经 ConfigManager.applyServerProfile() 落到 HTTP 装配点。
 */

import { preferences } from '@kit.ArkData';

const PREFERENCES_NAME = 'neurova_server_profiles';
const KEY_PROFILES = 'profiles_json';
const KEY_ACTIVE_ID = 'active_id';

/** 一台终端的档案 */
export interface ServerProfile {
  id: string;
  name: string;
  /** 直连：http(s)://host:port；中继转发地址：https://<relay>/t/<routeId> */
  baseUrl: string;
  /** direct=内网/反代直连；relay=经自研中继 */
  entryMode: string;
  /** 最近成功登录的账号（仅展示） */
  lastAccount: string;
}

function normalizeBaseUrl(url: string): string {
  return (url || '').replace(/\/+$/g, '').trim();
}

export class ServerProfiles {
  private static instance: ServerProfiles;
  private prefs: preferences.Preferences | null = null;
  private list: ServerProfile[] = [];
  private activeId: string = '';
  private loaded: boolean = false;

  private constructor() {}

  static getInstance(): ServerProfiles {
    if (!ServerProfiles.instance) {
      ServerProfiles.instance = new ServerProfiles();
    }
    return ServerProfiles.instance;
  }

  /** 启动时加载（幂等） */
  async load(context: Context): Promise<void> {
    if (this.loaded) {
      return;
    }
    this.prefs = await preferences.getPreferences(context, PREFERENCES_NAME);
    const raw = await this.prefs.get(KEY_PROFILES, '[]') as string;
    try {
      const parsed = JSON.parse(raw) as ServerProfile[];
      this.list = Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      this.list = [];
    }
    this.activeId = await this.prefs.get(KEY_ACTIVE_ID, '') as string;
    if (this.list.length > 0 && !this.list.some((p) => p.id === this.activeId)) {
      this.activeId = this.list[0].id;
    }
    this.loaded = true;
  }

  getList(): ServerProfile[] {
    return this.list.slice();
  }

  getActive(): ServerProfile | null {
    for (const p of this.list) {
      if (p.id === this.activeId) {
        return p;
      }
    }
    return this.list.length > 0 ? this.list[0] : null;
  }

  /** 当前档案的 API 根：{baseUrl}/api/v1 */
  getActiveApiBase(): string {
    const active = this.getActive();
    return active ? `${normalizeBaseUrl(active.baseUrl)}/api/v1` : '';
  }

  async add(name: string, baseUrl: string): Promise<ServerProfile> {
    const id = `srv-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
    const profile: ServerProfile = {
      id: id,
      name: name || normalizeBaseUrl(baseUrl),
      baseUrl: normalizeBaseUrl(baseUrl),
      entryMode: baseUrl.indexOf('/t/') >= 0 ? 'relay' : 'direct',
      lastAccount: '',
    };
    this.list.push(profile);
    this.activeId = id;
    await this.save();
    return profile;
  }

  async remove(id: string): Promise<void> {
    this.list = this.list.filter((p) => p.id !== id);
    if (this.activeId === id && this.list.length > 0) {
      this.activeId = this.list[0].id;
    }
    await this.save();
  }

  async switchTo(id: string): Promise<boolean> {
    for (const p of this.list) {
      if (p.id === id) {
        this.activeId = id;
        await this.save();
        return true;
      }
    }
    return false;
  }

  /** 编辑档案（名称/地址）；地址变更后由调用方重连 HttpClient 装配点（applyServerProfile） */
  async update(id: string, name: string, baseUrl: string): Promise<boolean> {
    for (const p of this.list) {
      if (p.id === id) {
        p.name = name.trim() || normalizeBaseUrl(baseUrl);
        p.baseUrl = normalizeBaseUrl(baseUrl);
        p.entryMode = p.baseUrl.indexOf('/t/') >= 0 ? 'relay' : 'direct';
        await this.save();
        return true;
      }
    }
    return false;
  }

  async markConnected(account: string): Promise<void> {
    const active = this.getActive();
    if (active) {
      active.lastAccount = account;
      await this.save();
    }
  }

  private async save(): Promise<void> {
    if (!this.prefs) {
      return;
    }
    await this.prefs.put(KEY_PROFILES, JSON.stringify(this.list));
    await this.prefs.put(KEY_ACTIVE_ID, this.activeId);
    await this.prefs.flush();
  }
}
