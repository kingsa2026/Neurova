/**
 * 技能管理 API 模块
 *
 * 提供技能池管理和技能操作的API调用
 */

import { request } from '@/api';
import type {
  SkillMetadata,
  SkillCreateRequest,
  SkillUpdateRequest,
  SkillPushRequest,
  SkillShareRequest,
} from '../types/skill';

/**
 * 列出公共技能
 * @param tags 标签过滤（逗号分隔）
 * @param search 搜索关键词
 * @returns 公共技能列表
 */
export async function listPublicSkills(
  tags?: string,
  search?: string,
): Promise<SkillMetadata[]> {
  const params = new URLSearchParams();
  if (tags) params.append('tags', tags);
  if (search) params.append('search', search);

  const query = params.toString();
  const url = `/skills/public${query ? `?${query}` : ''}`;

  return request.get(url);
}

/**
 * 获取公共技能详情
 * @param skillId 技能ID
 * @returns 技能详情
 */
export async function getPublicSkill(
  skillId: string,
): Promise<SkillMetadata> {
  return request.get(`/skills/public/${skillId}`);
}

/**
 * 安装公共技能到Agent
 * @param skillId 技能ID
 * @param targetAgentId 目标Agent ID
 * @returns 是否成功
 */
export async function installPublicSkill(
  skillId: string,
  targetAgentId: string,
): Promise<{ success: boolean; skill_id: string; agent_id: string }> {
  return request.post(`/skills/public/${skillId}/install?target_agent_id=${targetAgentId}`);
}

/**
 * 列出专属技能
 * @param visibility 可见性过滤
 * @returns 专属技能列表
 */
export async function listPrivateSkills(
  visibility?: string,
): Promise<SkillMetadata[]> {
  const params = new URLSearchParams();
  if (visibility) params.append('visibility', visibility);

  const query = params.toString();
  const url = `/skills/private${query ? `?${query}` : ''}`;

  return request.get(url);
}

/**
 * 创建专属技能
 * @param data 创建技能请求
 * @returns 技能详情
 */
export async function createPrivateSkill(
  data: SkillCreateRequest,
): Promise<{ success: boolean; skill_id: string; skill: SkillMetadata }> {
  return request.post('/skills/private', data);
}

/**
 * 更新专属技能
 * @param skillId 技能ID
 * @param data 更新技能请求
 * @returns 是否成功
 */
export async function updatePrivateSkill(
  skillId: string,
  data: SkillUpdateRequest,
): Promise<{ success: boolean }> {
  return request.put(`/skills/private/${skillId}`, data);
}

/**
 * 删除专属技能
 * @param skillId 技能ID
 * @returns 是否成功
 */
export async function deletePrivateSkill(
  skillId: string,
): Promise<{ success: boolean }> {
  return request.delete(`/skills/private/${skillId}`);
}

/**
 * 共享专属技能
 * @param skillId 技能ID
 * @param targetUserId 目标用户ID
 * @returns 是否成功
 */
export async function sharePrivateSkill(
  skillId: string,
  targetUserId: string,
): Promise<{ success: boolean }> {
  return request.post(`/skills/private/${skillId}/share`, { target_user_id: targetUserId });
}

/**
 * 推送技能给Agent
 * @param skillId 技能ID
 * @param agentId Agent ID
 * @param isPublic 是否是公共技能
 * @returns 是否成功
 */
export async function pushSkillToAgent(
  skillId: string,
  agentId: string,
  isPublic: boolean = false,
): Promise<{ success: boolean }> {
  const params = new URLSearchParams();
  params.append('is_public', String(isPublic));

  return request.post(`/skills/${skillId}/push?${params.toString()}`, { agent_id: agentId });
}

/**
 * 从Agent取消推送技能
 * @param skillId 技能ID
 * @param agentId Agent ID
 * @param isPublic 是否是公共技能
 * @returns 是否成功
 */
export async function unpushSkillFromAgent(
  skillId: string,
  agentId: string,
  isPublic: boolean = false,
): Promise<{ success: boolean }> {
  const params = new URLSearchParams();
  params.append('is_public', String(isPublic));

  return request.post(`/skills/${skillId}/unpush?${params.toString()}`, { agent_id: agentId });
}

/**
 * 获取Agent的所有技能
 * @param agentId Agent ID
 * @returns Agent技能列表
 */
export async function getAgentSkills(
  agentId: string,
): Promise<SkillMetadata[]> {
  return request.get(`/skills/agent/${agentId}`);
}
