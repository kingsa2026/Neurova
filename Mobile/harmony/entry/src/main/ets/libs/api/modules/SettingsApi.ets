/**
 * SettingsApi - 应用设置 API 模块
 *
 * 职责：列出设置分组、获取单条设置、更新设置、重置分组
 * 设计：通过 HttpClient 委托请求；update body 形如 { value }；reset 可选 group
 *
 * 用法：
 *   const api = ApiFacade.getInstance().settings;
 *   const groups = await api.list();
 *   await api.update('theme', 'dark');
 *   await api.reset('appearance');
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse, SettingItem, SettingGroup } from '../../types';

/** 设置更新请求体 */
export interface SettingUpdateBody {
  value: Object;
  group?: string;
}

/** 设置重置请求体 */
export interface SettingResetBody {
  group?: string;
}

export class SettingsApi {
  constructor(private client: HttpClient) {}

  /** 列出所有设置分组 */
  async list(): Promise<ApiResponse<SettingGroup[]>> {
    return this.client.get<SettingGroup[]>('/v1/settings');
  }

  /** 获取单个设置项 */
  async get(key: string): Promise<ApiResponse<SettingItem>> {
    return this.client.get<SettingItem>(`/v1/settings/${key}`);
  }

  /** 更新设置项（值类型由前端按 SettingType 决定） */
  async update(key: string, value: Object): Promise<ApiResponse<SettingItem>> {
    const body: SettingUpdateBody = { value };
    return this.client.put<SettingItem>(`/v1/settings/${key}`, body);
  }

  /** 重置设置（可指定分组，不传则重置全部） */
  async reset(group?: string): Promise<ApiResponse<Object>> {
    const body: SettingResetBody = {};
    if (group !== undefined) body.group = group;
    return this.client.post<Object>('/v1/settings/reset', body);
  }
}
