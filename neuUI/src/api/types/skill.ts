/**
 * 技能相关类型定义
 */

/**
 * 技能池类型
 */
export type SkillPoolType = 'public' | 'private';

/**
 * 技能可见性
 */
export type SkillVisibility = 'public' | 'private' | 'shared';

/**
 * 技能元数据
 */
export interface SkillMetadata {
  skill_id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  pool_type: SkillPoolType;
  visibility: SkillVisibility;
  owner_user_id: string | null;
  shared_with: string[];
  pushed_to_agents: string[];
  tags: string[];
  install_count: number;
  rating: number;
  rating_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * 创建技能请求
 */
export interface SkillCreateRequest {
  skill_id: string;
  name: string;
  description: string;
  visibility?: SkillVisibility;
  tags?: string[];
}

/**
 * 更新技能请求
 */
export interface SkillUpdateRequest {
  name?: string;
  description?: string;
  visibility?: SkillVisibility;
  tags?: string[];
}

/**
 * 技能推送请求
 */
export interface SkillPushRequest {
  agent_id: string;
}

/**
 * 技能共享请求
 */
export interface SkillShareRequest {
  target_user_id: string;
}

/**
 * API响应类型
 */
export interface SkillAPIResponse<T> {
  code: number;
  message: string;
  data: T;
}
