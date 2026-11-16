/**
 * MarketplaceApi - 技能市场 API 模块（R6 新增，端点经后端源码核对 2026-11-17）
 *
 * 后端事实源（marketplace.py @ /v1/marketplace）：
 *   GET    /skills?with_total=true → 裸 {items[MarketplaceSkill],total}（分页信封）
 *          不带 with_total 为裸数组旧契约——本模块统一走 with_total=true
 *   GET    /skills/{id}            → 裸 MarketplaceSkill
 *   POST   /skills/{id}/install    ← {version?,config?,force?,agent_id?} → 信封
 *   DELETE /skills/{id}/install?agent_id= → 信封（联邦注销目标 agent 过属主门）
 *
 * MarketplaceSkill 字段：skill_id/name/description/author/version/category/tags/
 * downloads/rating/installed/price/download_url/updated_at/source/permissions?/
 * sandbox_required?——后端是技能市场，无 itemType(free/paid/subscription) 维度。
 */
import { HttpClient } from '../HttpClient';
import { asEnvelope } from '../envelope';
import { ApiResponse } from '../../types';

/** 市场技能条目（marketplace.py MarketplaceSkill 模型） */
export interface MarketSkillDto {
  skill_id: string;
  name: string;
  description: string;
  author: string;
  version: string;
  category: string;
  tags: string[];
  downloads: number;
  rating: number;
  installed: boolean;
  price: number;
  download_url: string;
  updated_at: string | null;
  source: string;             // local(管理员上架)/aliyun/xfyun
  permissions: Record<string, Object> | null;
  sandbox_required: boolean | null;
}

/** 分页信封（with_total=true 的裸 {items,total}） */
export interface MarketSkillPageDto {
  items: MarketSkillDto[];
  total: number;
}

/** install/uninstall 信封 data（marketplace.py 三形态公共键：skill_id） */
export interface MarketOpResultDto {
  skill_id: string;
  status?: string;
  task_id?: string;
  version?: string;
  already_installed?: boolean;
}

/** 列表筛选参数 */
export interface MarketListParams {
  category?: string;
  search?: string;
  limit: number;
  offset: number;
  source?: string;
}

/** 安装请求体（marketplace.py SkillInstallRequest） */
export interface MarketInstallBody {
  version?: string;
  config?: Record<string, Object>;
  force?: boolean;
  agentId?: string;
}

export class MarketplaceApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 市场技能分页列表（GET /skills?with_total=true，裸 {items,total} 边界归一） */
  async list(params: MarketListParams): Promise<ApiResponse<MarketSkillPageDto>> {
    const query: Record<string, Object> = {
      'with_total': 'true',
      'limit': params.limit,
      'offset': params.offset,
    };
    if (params.category !== undefined && params.category.length > 0) {
      query['category'] = params.category;
    }
    if (params.search !== undefined && params.search.length > 0) {
      query['search'] = params.search;
    }
    if (params.source !== undefined && params.source.length > 0) {
      query['source'] = params.source;
    }
    const res = await this.client.get<MarketSkillPageDto>('/marketplace/skills', query);
    return asEnvelope<MarketSkillPageDto>(res, ['items', 'total']) as ApiResponse<MarketSkillPageDto>;
  }

  /** 技能详情（GET /skills/{id}，裸对象边界归一） */
  async detail(skillId: string): Promise<ApiResponse<MarketSkillDto>> {
    const res = await this.client.get<MarketSkillDto>(`/marketplace/skills/${skillId}`);
    return asEnvelope<MarketSkillDto>(res, ['skill_id', 'name']) as ApiResponse<MarketSkillDto>;
  }

  /** 安装（POST /skills/{id}/install，信封原样；agent_id 过属主门，409=安全门拒装） */
  async install(skillId: string, body?: MarketInstallBody): Promise<ApiResponse<MarketOpResultDto>> {
    const payload: Record<string, Object> = {};
    if (body) {
      if (body.version !== undefined) {
        payload['version'] = body.version;
      }
      if (body.config !== undefined) {
        payload['config'] = body.config;
      }
      if (body.force !== undefined) {
        payload['force'] = body.force;
      }
      if (body.agentId !== undefined && body.agentId.length > 0) {
        payload['agent_id'] = body.agentId;
      }
    }
    const res = await this.client.post<MarketOpResultDto>(`/marketplace/skills/${skillId}/install`, payload);
    return asEnvelope<MarketOpResultDto>(res, ['skill_id']);
  }

  /** 卸载（DELETE /skills/{id}/install?agent_id=，信封原样） */
  async uninstall(skillId: string, agentId: string = 'default'): Promise<ApiResponse<MarketOpResultDto>> {
    const url = `/marketplace/skills/${skillId}/install?agent_id=${encodeURIComponent(agentId)}`;
    const res = await this.client.delete<MarketOpResultDto>(url);
    return asEnvelope<MarketOpResultDto>(res, ['skill_id']);
  }
}
