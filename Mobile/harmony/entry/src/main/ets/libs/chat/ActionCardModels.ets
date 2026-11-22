/**
 * ActionCardModels - 确认/审批卡的视图模型与解析（纯逻辑，Node 可测）
 *
 * 两类卡的数据源与字段口径（后端事实源，勿凭 UI 臆造）：
 * - U1 主机确认卡：chat:tool_result 的结果 JSON 携 `needs_host_confirmation:true`
 *   及 `host/port/fingerprint/key_type/agent_id`（tool_executor._handleSshHostConfirmation
 *   → _emit_computer_event 透传）；
 *   确认动作 = POST /api/v1/settings/ssh-credentials/host-key/confirm
 *   （settings.py confirmSshHostKey，body {agent_id,host,port,fingerprint,key_type}）。
 * - U6 治理审批卡：chat:approval_required 的 data 携
 *   `approval_id/tool_name/params/reason/governance`（console._extract_approval_payload
 *   经 mobile_pairing._sendToolResultDerivedEvents 派生）；
 *   裁决动作 = POST /api/v1/governance/approvals/{id}/approve | /reject。
 *
 * 状态机（诚实暴露，不吞失败）：
 *   pending → confirmed/rejected（本端动作已提交且服务端应答）
 *   pending → failed（请求失败/非零码，detail 带原因，卡可重试）
 */

/** 主机确认卡状态 */
export const HOST_CONFIRM_PENDING = 'pending';
export const HOST_CONFIRM_CONFIRMED = 'confirmed';
export const HOST_CONFIRM_REJECTED = 'rejected';
export const HOST_CONFIRM_FAILED = 'failed';

/** 审批卡状态 */
export const APPROVAL_PENDING = 'pending';
export const APPROVAL_APPROVED = 'approved';
export const APPROVAL_REJECTED = 'rejected';
export const APPROVAL_FAILED = 'failed';

/** U1 SSH 首连主机公钥确认卡 */
export interface HostConfirmationCard {
  agentId: string;
  host: string;
  port: number;
  fingerprint: string;
  keyType: string;
  status: string;
  /** 动作结果/失败原因（诚实文案；pending 期为空） */
  detail: string;
}

/** U6 动态干预审批卡 */
export interface ApprovalCard {
  approvalId: string;
  toolName: string;
  reason: string;
  status: string;
  detail: string;
}

function asString(value: Object | undefined, fallback: string = ''): string {
  return typeof value === 'string' ? value as string : fallback;
}

function asNumber(value: Object | undefined, fallback: number): number {
  return typeof value === 'number' ? value as number : fallback;
}

/**
 * 从 chat:tool_result 的 data 里解析主机确认卡。
 * 结果体可能是 JSON 串（tool_message.content）或已解对象（result）；
 * 无 needs_host_confirmation 标记即回 null（普通工具结果不弹卡）。
 */
export function parseHostConfirmationCard(data: Record<string, Object>): HostConfirmationCard | null {
  let payload: Record<string, Object> | null = null;
  const raw = data['result'] ?? data['content'] ?? data;
  if (typeof raw === 'string') {
    try {
      payload = JSON.parse(raw as string) as Record<string, Object>;
    } catch (e) {
      return null;
    }
  } else if (raw instanceof Object) {
    payload = raw as Record<string, Object>;
  }
  if (payload === null || payload['needs_host_confirmation'] !== true) {
    return null;
  }
  const host = asString(payload['host']);
  const fingerprint = asString(payload['fingerprint']);
  if (host === '' || fingerprint === '') {
    // 缺关键字段的卡没法确认（后端 confirm 端点两字段必填）——不弹卡，让超时路径诚实终止
    return null;
  }
  const card: HostConfirmationCard = {
    agentId: asString(payload['agent_id']),
    host: host,
    port: asNumber(payload['port'], 22),
    fingerprint: fingerprint,
    keyType: asString(payload['key_type']),
    status: HOST_CONFIRM_PENDING,
    detail: '',
  };
  return card;
}

/** 从 chat:approval_required 的 data 解析审批卡（无 approval_id 即回 null） */
export function parseApprovalCard(data: Record<string, Object>): ApprovalCard | null {
  const approvalId = asString(data['approval_id']);
  if (approvalId === '') {
    return null;
  }
  const card: ApprovalCard = {
    approvalId: approvalId,
    toolName: asString(data['tool_name']),
    reason: asString(data['reason']),
    status: APPROVAL_PENDING,
    detail: '',
  };
  return card;
}

/** 主机确认卡状态文案（pending 期不给 detail，用固定引导语） */
export function hostConfirmStatusText(card: HostConfirmationCard): string {
  if (card.status === HOST_CONFIRM_CONFIRMED) {
    return card.detail === '' ? '已确认，命令将自动重试执行' : card.detail;
  }
  if (card.status === HOST_CONFIRM_REJECTED) {
    return card.detail === '' ? '已拒绝：本次命令未执行' : card.detail;
  }
  if (card.status === HOST_CONFIRM_FAILED) {
    return card.detail === '' ? '确认失败，请重试' : card.detail;
  }
  return '首次连接该主机，请核对指纹后确认';
}

/** 审批卡状态文案 */
export function approvalStatusText(card: ApprovalCard): string {
  if (card.status === APPROVAL_APPROVED) {
    return card.detail === '' ? '已批准，等待执行结果回传' : card.detail;
  }
  if (card.status === APPROVAL_REJECTED) {
    return card.detail === '' ? '已拒绝：本次操作不执行' : card.detail;
  }
  if (card.status === APPROVAL_FAILED) {
    return card.detail === '' ? '操作失败，请重试' : card.detail;
  }
  return card.reason === '' ? '该操作需要你批准后才会执行' : card.reason;
}
