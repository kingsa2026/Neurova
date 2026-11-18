/**
 * SettingsApi - 应用设置 API 模块（端点经后端源码核对 2026-11-16，P1-30/P1-31）
 *
 * 后端事实源（settings.py，router 自述 prefix="/v1/settings"，挂载表前缀为空）：
 *   GET /v1/settings        → SettingsResponse{settings: Dict, updated_at}（裸对象）
 *   GET /v1/settings/{key}  → {code:0, data:{key, value}}
 *   PUT /v1/settings/{key}  ← {value}（仅管理员；section 键拒收，走 PUT /v1/settings 整表）
 *   PUT /v1/settings        ← {settings: Dict}（整表，仅管理员）
 *   POST /v1/settings/clear-cache
 * 后端**无** /v1/settings/reset：reset 诚实 throw 点名。
 * baseUrl 已含 /api/v1——路径一律不重复写 /v1（P1-30 模块守卫盯防）。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import { ApiResponse, SettingItem, SettingGroup, SettingType } from '../../types';

/** 设置更新请求体 */
export interface SettingUpdateBody {
  value: Object;
}

/** GET/PUT /settings 的响应体（settings.py SettingsResponse） */
interface SettingsResponseDto {
  settings: Record<string, Object>;
  updated_at: string | null;
}

/** 单键读写的 data 载荷（{key, value}） */
interface SettingKeyValueDto {
  key: string;
  value: Object;
}

/** 按值类型推断 SettingType（后端无 UI 元数据，诚实回落 input） */
function inferSettingType(value: Object): SettingType {
  if (typeof value === 'boolean') {
    return 'toggle';
  }
  return 'input';
}

/**
 * 后端 section 键 → 中文组名（单一映射出口）。
 * 已知键译名；未知键诚实保留原键（不编造译名）。
 */
function sectionTitle(key: string): string {
  if (key === 'general') { return '通用'; }
  if (key === 'security') { return '安全'; }
  if (key === 'storage') { return '存储'; }
  if (key === 'advanced') { return '高级'; }
  if (key === 'routing') { return '路由'; }
  if (key === 'quota') { return '配额'; }
  if (key === 'theme') { return '主题'; }
  if (key === 'appearance') { return '外观'; }
  if (key === 'notification') { return '通知'; }
  if (key === 'privacy') { return '隐私'; }
  if (key === 'about') { return '关于'; }
  return key;
}

/** settings.py 单键载荷 → SettingItem（单源映射；组名取键首段译名，条目名取键尾段） */
function toSettingItem(key: string, value: Object): SettingItem {
  const group = key.indexOf('.') !== -1 ? key.split('.')[0] : 'general';
  const parts = key.split('.');
  const label = parts.length > 1 ? parts[parts.length - 1] : key;
  const item: SettingItem = {
    key: key,
    label: label,
    type: inferSettingType(value),
    value: value,
    defaultValue: value,
    group: group,
  };
  return item;
}

export class SettingsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * 列出所有设置（GET /settings，{settings:Dict} 真实形状解析——P1-31）：
   * section 值为 dict 时展开成 `${section}.${subkey}` 条目并按 section 分组；
   * 平铺键归入 general 组。返回 SettingGroup[] 供 SettingPage 直接渲染。
   */
  async list(): Promise<ApiResponse<SettingGroup[]>> {
    const res = asEnvelope<SettingsResponseDto>(await this.client.get<SettingsResponseDto>('/settings'), ['settings']);
    if (res.code !== 0 || !res.data) {
      throw new Error(res.message && res.message.length > 0 ? res.message : '设置获取失败');
    }
    const settings = (res.data.settings ?? {}) as Record<string, Object>;
    const groups: SettingGroup[] = [];
    const flatItems: SettingItem[] = [];
    const keys: string[] = Object.keys(settings);
    for (const key of keys) {
      const value: Object = settings[key];
      if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
        // section（general/security/storage/advanced/routing/quota...）：展开为子键条目
        const items: SettingItem[] = [];
        const subKeys: string[] = Object.keys(value as Record<string, Object>);
        for (const sub of subKeys) {
          const subValue: Object = (value as Record<string, Object>)[sub];
          items.push(toSettingItem(`${key}.${sub}`, subValue));
        }
        const group: SettingGroup = { key: key, title: sectionTitle(key), items: items };
        groups.push(group);
      } else {
        flatItems.push(toSettingItem(key, value));
      }
    }
    if (flatItems.length > 0) {
      const general: SettingGroup = { key: 'general', title: sectionTitle('general'), items: flatItems };
      groups.unshift(general);
    }
    return { code: 0, message: res.message, data: groups } as ApiResponse<SettingGroup[]>;
  }

  /** 获取单个设置项（GET /settings/{key}，{code,data:{key,value}} 信封） */
  async get(key: string): Promise<ApiResponse<SettingItem>> {
    const res = await this.client.get<SettingKeyValueDto>(`/settings/${key}`);
    const ok = asEnvelope<SettingKeyValueDto>(res, ['key', 'value']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '设置项获取失败');
    }
    const dto = ok.data as Object as SettingKeyValueDto;
    return { code: ok.code, message: ok.message, data: toSettingItem(dto.key, dto.value) } as ApiResponse<SettingItem>;
  }

  /** 更新设置项（PUT /settings/{key}，body {value}；值类型由前端按 SettingType 决定） */
  async update(key: string, value: Object): Promise<ApiResponse<SettingItem>> {
    const body: SettingUpdateBody = { value: value };
    const res = await this.client.put<SettingKeyValueDto>(`/settings/${key}`, body);
    const ok = asEnvelope<SettingKeyValueDto>(res, ['key', 'value']);
    if (ok.code !== 0 || !ok.data) {
      throw new Error(ok.message && ok.message.length > 0 ? ok.message : '设置保存失败');
    }
    const dto = ok.data as Object as SettingKeyValueDto;
    return { code: ok.code, message: ok.message, data: toSettingItem(dto.key, dto.value) } as ApiResponse<SettingItem>;
  }

  /** @deprecated 后端无 POST /v1/settings/reset（最近真面是 POST /v1/settings/clear-cache，语义不同不冒充） */
  async reset(group?: string): Promise<ApiResponse<Object>> {
    throw new Error('后端无此端点：POST /v1/settings/reset（后端仅提供 PUT /v1/settings 整表更新与 POST /v1/settings/clear-cache）');
  }
}
