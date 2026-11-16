/**
 * SkillsApi - 技能系统 API 模块（R6 新增，端点经后端源码核对 2026-11-17）
 *
 * 后端事实源（skill.py @ /v1/skills，router 级 get_current_user）：
 *   GET  /skills                → 裸数组 List[SkillInfo]（category/enabled_only 可选 query）
 *   PUT  /skills/{id}/enable    → 信封 {code,message,data:{skill_id,enabled:true}}
 *   PUT  /skills/{id}/disable   → 信封 {code,message,data:{skill_id,enabled:false}}
 *
 * SkillInfo 字段：skill_id/name/description/category/version/enabled/
 * usage_count/success_rate/created_at/updated_at——后端无 draft/published/
 * deprecated 三态与 installs/rating 字段（那是市场域契约），本模块不投影。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope, asEnvelopeList } from '../envelope';
import { ApiResponse } from '../../types';

/** SkillInfo 投影（skill.py，蛇形字段原样透传） */
export interface SkillInfoDto {
  skill_id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  enabled: boolean;
  usage_count: number;
  success_rate: number;
  created_at: number;
  updated_at: number;
}

/** enable/disable 信封 data（skill.py：{skill_id, enabled}） */
export interface SkillToggleResultDto {
  skill_id: string;
  enabled: boolean;
}

export class SkillsApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * 技能列表（GET /skills，裸数组边界归一）。
   * @param category 按分类筛选（可选）
   * @param enabledOnly 仅显示启用技能（可选）
   */
  async list(category?: string, enabledOnly?: boolean): Promise<ApiResponse<SkillInfoDto[]>> {
    const params: Record<string, Object> = {};
    if (category !== undefined && category.length > 0) {
      params['category'] = category;
    }
    if (enabledOnly === true) {
      params['enabled_only'] = 'true';
    }
    const res = await this.client.get<SkillInfoDto[]>('/skills', params);
    return asEnvelopeList<SkillInfoDto>(res as ApiResponse<SkillInfoDto[]>);
  }

  /** 启用技能（PUT /skills/{id}/enable，信封原样） */
  async enable(skillId: string): Promise<ApiResponse<SkillToggleResultDto>> {
    const emptyBody: Record<string, Object> = {};
    const res = await this.client.put<SkillToggleResultDto>(`/skills/${skillId}/enable`, emptyBody);
    return asEnvelope<SkillToggleResultDto>(res, ['skill_id', 'enabled']);
  }

  /** 禁用技能（PUT /skills/{id}/disable，信封原样） */
  async disable(skillId: string): Promise<ApiResponse<SkillToggleResultDto>> {
    const emptyBody: Record<string, Object> = {};
    const res = await this.client.put<SkillToggleResultDto>(`/skills/${skillId}/disable`, emptyBody);
    return asEnvelope<SkillToggleResultDto>(res, ['skill_id', 'enabled']);
  }
}
