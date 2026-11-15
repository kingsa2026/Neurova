/**
 * AdminApi - 管理员域 API 模块（对照原型 F14-F17，同源 PC 管理页）
 *
 * 后端事实源（端点注册表 + 源码核对 2026-11-16）：
 *   GET    /v1/enhanced-users              → 裸 {items:[UserOut], total}
 *   DELETE /v1/enhanced-users/{id}
 *   GET    /v1/groups                      → 裸数组 List[GroupInfo]
 *   POST   /v1/groups                      → GroupCreate {name, description}
 *   GET    /v1/skill-pool/skill-submissions?review_status=pending
 *                                          → {code:0,data:{items,total}}
 *   POST   /v1/skill-pool/skill-submissions/{id}/review → {approve: bool, note}
 *   GET    /v1/governance/agent-limits     → 治理键值（仅管理员）
 * 注意：/v1/settings（扁平 kv）挂在无 /v1 前缀的 /api/settings——App baseUrl
 *       为 /api/v1 无法直达，设置全量面留在 PC；本模块只接治理 agent-limits。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 用户行（enhanced_users_api UserOut 投影） */
export interface AdminUserDto {
  id: number;
  username: string;
  email: string;
  role: string;
  active: boolean;
  created_at: string;
  last_login: string;
}

/** 用户列表载荷（裸 {items,total}） */
export interface AdminUserList {
  items: AdminUserDto[];
  total: number;
}

/** 用户组（groups_api GroupInfo） */
export interface AdminGroupDto {
  group_id: string;
  name: string;
  description: string;
  owner_id: string;
  members: string[];
  members_count: number;
}

/** 投稿条目（提交存储形状防御性子集：字段缺失即渲染为空） */
export interface SubmissionDto {
  id: string;
  title: string;
  skill_name: string;
  username: string;
  submitted_at: string;
  review_status: string;
}

export interface SubmissionList {
  items: SubmissionDto[];
  total: number;
}

export class AdminApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 用户列表（裸 {items,total}） */
  async listUsers(): Promise<AdminUserList> {
    const res = await this.client.get<AdminUserList>('/enhanced-users');
    return res as Object as AdminUserList;
  }

  /** 删除用户 */
  async removeUser(userId: number): Promise<ApiResponse<Object>> {
    return this.client.delete<Object>(`/enhanced-users/${userId}`);
  }

  /** 用户组列表（裸数组） */
  async listGroups(): Promise<AdminGroupDto[]> {
    const res = await this.client.get<AdminGroupDto[]>('/groups');
    return res as Object as AdminGroupDto[];
  }

  /** 创建用户组 */
  async createGroup(name: string, description: string): Promise<ApiResponse<AdminGroupDto>> {
    const body: Record<string, Object> = {
      'name': name,
      'description': description,
    };
    return this.client.post<AdminGroupDto>('/groups', body);
  }

  /** 待审技能投稿（信封 {code,data:{items,total}}） */
  async pendingSubmissions(): Promise<ApiResponse<SubmissionList>> {
    return this.client.get<SubmissionList>('/skill-pool/skill-submissions?review_status=pending');
  }

  /** 审阅投稿（approve=true 上架市场） */
  async reviewSubmission(submissionId: string, approve: boolean, note: string):
    Promise<ApiResponse<Object>> {
    const body: Record<string, Object> = {
      'approve': approve,
      'note': note,
    };
    return this.client.post<Object>(`/skill-pool/skill-submissions/${submissionId}/review`, body);
  }

  /** 治理 agent-limits（仅管理员；响应形状为动态键值，页面按键遍历渲染） */
  async agentLimits(): Promise<ApiResponse<Object>> {
    return this.client.get<Object>('/governance/agent-limits');
  }
}
