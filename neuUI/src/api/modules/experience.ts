import { request } from '@/api'

// 经验记录
export interface ExperienceRecord {
  id: string
  skill_name: string
  input_context: string
  output_result: string
  success: boolean
  execution_time_ms: number
  metadata: Record<string, any>
  tags: string[]
  created_at: string
}

// 添加经验记录请求
export interface AddExperienceRecordRequest {
  skill_name: string
  input_context: string
  output_result: string
  success?: boolean
  execution_time_ms?: number
  metadata?: Record<string, any>
  tags?: string[]
}

// 查找相似经验请求
export interface FindSimilarExperiencesRequest {
  context: string
  skill_name?: string
  top_k?: number
}

// 技能评估结果
export interface SkillEvaluation {
  skill_name: string
  total_executions: number
  success_rate: number
  average_execution_time: number
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
}

/**
 * 添加经验记录
 * @param data 经验记录数据
 * @returns 添加结果
 */
export async function addExperienceRecord(data: AddExperienceRecordRequest): Promise<{ code: number; message: string; data: ExperienceRecord }> {
  return request({
    url: '/api/v1/experience/records',
    method: 'post',
    data,
  })
}

/**
 * 获取技能的经验记录
 * @param skillName 技能名称
 * @param page 页码
 * @param size 每页数量
 * @returns 经验记录列表
 */
export async function getExperienceRecords(
  skillName: string,
  page: number = 1,
  size: number = 20
): Promise<{ code: number; message: string; data: PaginatedResponse<ExperienceRecord> }> {
  return request({
    url: `/api/v1/experience/records/${skillName}`,
    method: 'get',
    params: { page, size },
  })
}

/**
 * 查找相似经验
 * @param data 查找请求
 * @returns 相似经验列表
 */
export async function findSimilarExperiences(
  data: FindSimilarExperiencesRequest
): Promise<{ code: number; message: string; data: { results: ExperienceRecord[]; total: number } }> {
  return request({
    url: '/api/v1/experience/similar',
    method: 'post',
    data,
  })
}

/**
 * 评估技能效果
 * @param skillName 技能名称
 * @returns 评估结果
 */
export async function evaluateSkill(skillName: string): Promise<{ code: number; message: string; data: SkillEvaluation }> {
  return request({
    url: `/api/v1/experience/evaluate/${skillName}`,
    method: 'get',
  })
}

export default {
  addExperienceRecord,
  getExperienceRecords,
  findSimilarExperiences,
  evaluateSkill,
}