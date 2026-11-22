/**
 * ActionCardModels 单测（Node 直跑）：主机确认卡 / 审批卡的解析与状态文案
 *
 * 载荷口径对齐后端事实源：
 * - tool_executor._handleSshHostConfirmation → _emit_computer_event 透传的
 *   needs_host_confirmation{host,port,fingerprint,key_type,agent_id}（随 tool_result 结果体）；
 * - console._extract_approval_payload → chat:approval_required data 的
 *   {approval_id,tool_name,params,reason,governance,fingerprint_tail}。
 */

import {
  approvalStatusText,
  hostConfirmStatusText,
  parseApprovalCard,
  parseHostConfirmationCard,
  APPROVAL_APPROVED,
  APPROVAL_FAILED,
  APPROVAL_PENDING,
  APPROVAL_REJECTED,
  HOST_CONFIRM_CONFIRMED,
  HOST_CONFIRM_FAILED,
  HOST_CONFIRM_PENDING,
  HOST_CONFIRM_REJECTED,
} from '../../entry/src/main/ets/libs/chat/ActionCardModels';
import { check, eq, eqStr, source } from './Harness';

source('U1 主机确认卡 + U6 审批卡移动端渲染面——适配卡 B（批五）');

// ── 主机确认卡解析 ──

function hostConfirmPayload(): Record<string, Object> {
  const p: Record<string, Object> = {};
  p['needs_host_confirmation'] = true;
  p['host'] = '10.0.0.8';
  p['port'] = 2222;
  p['fingerprint'] = 'SHA256:AbCdEf0123456789';
  p['key_type'] = 'ssh-ed25519';
  p['agent_id'] = 'agent-7';
  p['error'] = '主机 10.0.0.8:2222 首次连接，公钥指纹 SHA256:AbCdEf0123456789，请在确认卡中核对后确认';
  return p;
}

// tool_result.data.content 是 JSON 串（tool_message 形态）
const asContent: Record<string, Object> = {};
asContent['content'] = JSON.stringify(hostConfirmPayload());
const fromContent = parseHostConfirmationCard(asContent);
check('主机卡：JSON 串结果可解析', fromContent !== null);
if (fromContent !== null) {
  eqStr('主机卡：host', fromContent.host, '10.0.0.8');
  eqStr('主机卡：agentId', fromContent.agentId, 'agent-7');
  check('主机卡：port', fromContent.port === 2222);
  eqStr('主机卡：fingerprint', fromContent.fingerprint, 'SHA256:AbCdEf0123456789');
  eqStr('主机卡：keyType', fromContent.keyType, 'ssh-ed25519');
  eqStr('主机卡：初始 pending', fromContent.status, HOST_CONFIRM_PENDING);
  eqStr('主机卡：pending 期无 detail', fromContent.detail, '');
}

// result 为已解对象形态
const asResult: Record<string, Object> = {};
asResult['result'] = hostConfirmPayload();
check('主机卡：对象结果可解析', parseHostConfirmationCard(asResult) !== null);

// 普通工具结果（无标记）不弹卡
const plain: Record<string, Object> = {};
plain['content'] = JSON.stringify({ success: true, stdout: 'ok' });
check('主机卡：普通结果不弹卡', parseHostConfirmationCard(plain) === null);
check('主机卡：非 JSON 串不弹卡', parseHostConfirmationCard((() => {
  const d: Record<string, Object> = {};
  d['content'] = 'plain text result';
  return d;
})()) === null);

// 缺关键字段（host/fingerprint）不弹卡——confirm 端点两字段必填，弹了也没法提交
const missingFp = hostConfirmPayload();
missingFp['fingerprint'] = '';
const missingCase: Record<string, Object> = {};
missingCase['content'] = JSON.stringify(missingFp);
check('主机卡：缺指纹不弹卡', parseHostConfirmationCard(missingCase) === null);

// ── 审批卡解析 ──

const approvalPayload: Record<string, Object> = {};
approvalPayload['approval_id'] = 'apr-001';
approvalPayload['tool_name'] = 'computer_ssh_exec';
approvalPayload['reason'] = 'L1 敏感操作，需要用户批准';
approvalPayload['governance'] = JSON.stringify({ level: 'L1' });
const approvalData: Record<string, Object> = {};
approvalData['data'] = approvalPayload;
const card = parseApprovalCard(approvalPayload);
check('审批卡：可解析', card !== null);
if (card !== null) {
  eqStr('审批卡：approvalId', card.approvalId, 'apr-001');
  eqStr('审批卡：toolName', card.toolName, 'computer_ssh_exec');
  eqStr('审批卡：reason', card.reason, 'L1 敏感操作，需要用户批准');
  eqStr('审批卡：初始 pending', card.status, APPROVAL_PENDING);
}
check('审批卡：缺 approval_id 不弹卡', parseApprovalCard((() => {
  const d: Record<string, Object> = {};
  d['tool_name'] = 'x';
  return d;
})()) === null);

// ── 状态文案（诚实暴露：失败带原因） ──

const hc = parseHostConfirmationCard(asContent);
if (hc !== null) {
  eqStr('主机卡文案：pending', hostConfirmStatusText(hc), '首次连接该主机，请核对指纹后确认');
  hc.status = HOST_CONFIRM_CONFIRMED;
  hc.detail = '';
  eqStr('主机卡文案：confirmed 缺省', hostConfirmStatusText(hc), '已确认，命令将自动重试执行');
  hc.status = HOST_CONFIRM_REJECTED;
  hc.detail = '';
  eqStr('主机卡文案：rejected 缺省', hostConfirmStatusText(hc), '已拒绝：本次命令未执行');
  hc.status = HOST_CONFIRM_FAILED;
  hc.detail = '确认请求失败：网络不可达';
  eqStr('主机卡文案：failed 带原因', hostConfirmStatusText(hc), '确认请求失败：网络不可达');
}

const ac = parseApprovalCard(approvalPayload);
if (ac !== null) {
  eqStr('审批卡文案：pending 带 reason', approvalStatusText(ac), 'L1 敏感操作，需要用户批准');
  ac.status = APPROVAL_APPROVED;
  ac.detail = '';
  eqStr('审批卡文案：approved 缺省', approvalStatusText(ac), '已批准，等待执行结果回传');
  ac.status = APPROVAL_REJECTED;
  ac.detail = '';
  eqStr('审批卡文案：rejected 缺省', approvalStatusText(ac), '已拒绝：本次操作不执行');
  ac.status = APPROVAL_FAILED;
  ac.detail = '批准失败：审批单状态为 rejected，无法批准';
  eqStr('审批卡文案：failed 带原因', approvalStatusText(ac), '批准失败：审批单状态为 rejected，无法批准');
}

// 状态常量口径自检（字面量逐一咬合，防止串改）
eqStr('状态常量：HOST_CONFIRM_PENDING', HOST_CONFIRM_PENDING, 'pending');
eqStr('状态常量：HOST_CONFIRM_CONFIRMED', HOST_CONFIRM_CONFIRMED, 'confirmed');
eqStr('状态常量：HOST_CONFIRM_REJECTED', HOST_CONFIRM_REJECTED, 'rejected');
eqStr('状态常量：HOST_CONFIRM_FAILED', HOST_CONFIRM_FAILED, 'failed');
eqStr('状态常量：APPROVAL_PENDING', APPROVAL_PENDING, 'pending');
eqStr('状态常量：APPROVAL_APPROVED', APPROVAL_APPROVED, 'approved');
eqStr('状态常量：APPROVAL_REJECTED', APPROVAL_REJECTED, 'rejected');
eqStr('状态常量：APPROVAL_FAILED', APPROVAL_FAILED, 'failed');
