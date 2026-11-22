/**
 * GovernanceApi - 治理审批 API 模块
 *
 * 后端事实源：neurova/api/endpoints/governance.py（router prefix="/v1/governance"）：
 *   POST /v1/governance/approvals/{request_id}/approve  批准并重放执行
 *   POST /v1/governance/approvals/{request_id}/reject   拒绝
 * 两口都要求管理员身份（_governance_admin_dep）；请求体 ApprovalActionRequest
 * {note, approved_by, remember?}。移动端审批卡（chat:approval_required）消费。
 * baseUrl 已含 /api/v1——路径不重复写 /v1。
 */
import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 审批动作请求体（governance.py ApprovalActionRequest 为 snake_case） */
export interface ApprovalActionBody {
  note: string;
  approved_by: string;
  /** None=仅本次 / "exact"=记住精确命令 / "similar"=记住同类 */
  remember?: string;
}

/** approve 响应 data：{approved, executed, result?} */
export interface ApprovalActionData {
  approved: boolean;
  executed?: boolean;
  message?: string;
  result?: Object;
}

export class GovernanceApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 批准并重放执行（POST /governance/approvals/{id}/approve） */
  async approve(requestId: string, note: string = '', remember?: string): Promise<ApiResponse<ApprovalActionData>> {
    const body: ApprovalActionBody = { note: note, approved_by: 'user' };
    if (remember !== undefined) {
      body.remember = remember;
    }
    return this.client.post<ApprovalActionData>(`/governance/approvals/${requestId}/approve`, body);
  }

  /** 拒绝（POST /governance/approvals/{id}/reject） */
  async reject(requestId: string, note: string = ''): Promise<ApiResponse<ApprovalActionData>> {
    const body: ApprovalActionBody = { note: note, approved_by: 'user' };
    return this.client.post<ApprovalActionData>(`/governance/approvals/${requestId}/reject`, body);
  }
}
