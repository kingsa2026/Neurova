import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api'
import {
  approveRequest as apiApproveRequest,
  rejectRequest as apiRejectRequest,
  addWhitelistEntry,
} from '@/api/modules/governance'
import { uiMessage } from '@/utils/message'

/**
 * 治理审批（P0 ASK 人工确认）状态机（2026-09-08 ChatPage 拆分产物）。
 *
 * 模块级共享 reactive：SSE 处理器（页面编排层 openApprovalModal）与
 * GovernanceApprovalModal 组件零 props 连线。
 * confirm/reject 的 API 逻辑原样迁自 ChatPage（不改写）。
 */

export interface ApprovalSegment {
  text: string
  head: string
  connector: string
  quoted: boolean
}

const approvalModal = reactive({
  open: false,
  loading: false,
  approvalId: '',
  toolName: '',
  command: '',
  reason: '',
  // P0-6 分段审批：多段命令的候选段（后端 governance.segments）
  segments: [] as ApprovalSegment[],
})
const approvalAddWhitelist = ref(false)
/** 审批记忆档位：'' = 仅本次 / exact / similar（补课 3.2，后端 approval_manager 记忆规则） */
const approvalRemember = ref<'' | 'exact' | 'similar'>('')

/** SSE approval_required 事件 → 打开弹窗（payload 字段原样迁自 ChatPage） */
function openApprovalModal(event: Record<string, any>): void {
  approvalModal.approvalId = event.approval_id || ''
  approvalModal.toolName = event.tool_name || ''
  const params = typeof event.params === 'string' ? event.params : JSON.stringify(event.params ?? {}, null, 2)
  approvalModal.command = params !== '{}' ? params : event.command || ''
  approvalModal.reason = event.reason || ''
  const govSegments = event.governance?.segments
  approvalModal.segments = Array.isArray(govSegments)
    ? govSegments.map((s: any) => ({
        text: String(s?.text ?? ''),
        head: String(s?.head ?? ''),
        connector: String(s?.connector ?? ''),
        quoted: Boolean(s?.quoted),
      }))
    : []
  approvalAddWhitelist.value = false
  approvalModal.open = true
}

/** 从命令中提取适合加入白名单的前缀（首个词或可执行文件名） */
function extractWhitelistPattern(command: string): string {
  const trimmed = (command || '').trim()
  if (!trimmed) return ''
  const head = trimmed.split(/[|;&]/)[0].trim()
  return head.split(/\s+/)[0] || head
}

/** 批准执行；勾选白名单时先加入免检列表再批准 */
async function confirmApproval(): Promise<void> {
  const { t } = useI18n()
  if (!approvalModal.approvalId || approvalModal.loading) return
  approvalModal.loading = true
  try {
    if (approvalAddWhitelist.value) {
      const pattern = extractWhitelistPattern(approvalModal.command)
      if (pattern) {
        await addWhitelistEntry({
          pattern,
          match_type: 'prefix',
          note: t('ui.approvalNote', { id: approvalModal.approvalId }),
        })
      }
    }
    const resp = await apiApproveRequest(
      approvalModal.approvalId,
      t('ui.userConfirmed'),
      approvalRemember.value || undefined,
    )
    approvalModal.open = false
    approvalRemember.value = ''
    const data = (resp as any)?.data?.data ?? (resp as any)?.data
    if (data?.executed && data?.result) {
      uiMessage.success(t('ui.approvedExecuted'))
    } else {
      uiMessage.success(t('ui.approved'))
    }
  } catch (e) {
    console.error('[Approval] approve failed:', e)
    uiMessage.error(t('ui.approveFailed'))
  } finally {
    approvalModal.loading = false
  }
}

/** 拒绝执行 */
async function rejectApproval(): Promise<void> {
  const { t } = useI18n()
  if (!approvalModal.approvalId || approvalModal.loading) return
  approvalModal.loading = true
  try {
    await apiRejectRequest(approvalModal.approvalId, t('ui.userRejected'))
    approvalModal.open = false
    approvalRemember.value = ''
    uiMessage.info(t('ui.rejectedOperation'))
  } catch (e) {
    console.error('[Approval] reject failed:', e)
    uiMessage.error(t('ui.operationFailed'))
  } finally {
    approvalModal.loading = false
  }
}

export function useGovernanceApproval() {
  return {
    approvalModal,
    approvalAddWhitelist,
    approvalRemember,
    openApprovalModal,
    confirmApproval,
    rejectApproval,
  }
}

// api 导入保留给后续扩展（当前审批 API 均经 governance 模块）
void api
