<template>
  <a-modal
    v-model:open="approvalModal.open"
    :title="t('ui.confirmNeeded')"
    :confirm-loading="approvalModal.loading"
    :ok-text="t('ui.approveExecute')"
    :cancel-text="t('ui.reject')"
    @ok="confirmApproval"
    @cancel="rejectApproval"
  >
    <div class="approval-body">
      <div class="approval-field">
        <span class="approval-label">{{ t('ui.tool') }}</span>
        <a-tag color="orange">{{ approvalModal.toolName || t('ui.unknown') }}</a-tag>
      </div>
      <div v-if="approvalModal.command" class="approval-field">
        <span class="approval-label">{{ t('ui.content') }}</span>
        <pre class="approval-command">{{ approvalModal.command }}</pre>
      </div>
      <!-- P0-6 分段审批：链式命令逐段确认，注入段无法借白名单段搭便车 -->
      <div v-if="approvalModal.segments.length > 1" class="approval-field">
        <span class="approval-label">{{ t('ui.approvalSegments') }}</span>
        <ul class="approval-segments">
          <li v-for="(seg, idx) in approvalModal.segments" :key="idx" class="approval-segment">
            <a-tag v-if="seg.connector" color="default" class="approval-segment-connector">{{ seg.connector }}</a-tag>
            <code class="approval-segment-text">{{ seg.text }}</code>
            <a-tag v-if="seg.quoted" color="purple">{{ t('ui.approvalSegmentInline') }}</a-tag>
          </li>
        </ul>
      </div>
      <div v-if="approvalModal.reason" class="approval-field">
        <span class="approval-label">{{ t('ui.reason') }}</span>
        <span class="approval-reason">{{ approvalModal.reason }}</span>
      </div>
      <a-checkbox v-model:checked="approvalAddWhitelist">
        {{ t('ui.addToWhitelistAndApprove') }}
      </a-checkbox>
      <a-radio-group v-model:value="approvalRemember" class="approval-remember" size="small">
        <a-radio value="">{{ t('ui.rememberNone') }}</a-radio>
        <a-radio value="exact">{{ t('ui.rememberExact') }}</a-radio>
        <a-radio value="similar">{{ t('ui.rememberSimilar') }}</a-radio>
      </a-radio-group>
      <p class="approval-hint">{{ t('ui.approvalHint') }}</p>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 治理审批弹窗（P0 ASK 人工确认）。
 * 模板原样迁自 ChatPage（2026-09-08 拆分）；状态收敛在
 * useGovernanceApproval 模块级 reactive，SSE approval_required 事件
 * 经 openApprovalModal 驱动，零 props 连线。
 * 样式：approval-* 类在 ChatPage 全局/共享样式中保留（跨组件类名不变）。
 */
import { useI18n } from 'vue-i18n'
import { useGovernanceApproval } from '@/composables/useGovernanceApproval'

const { t } = useI18n()
const { approvalModal, approvalAddWhitelist, approvalRemember, confirmApproval, rejectApproval } =
  useGovernanceApproval()
</script>

<style scoped>
.approval-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.approval-field {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.approval-label {
  min-width: 42px;
  font-size: 13px;
  color: var(--nr-text-secondary);
  line-height: 22px;
  flex-shrink: 0;
}
.approval-command {
  font-size: 12px;
  color: var(--nr-text-primary, inherit);
  background: var(--nr-bg-inset);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 140px;
  flex: 1;
}
/* P0-6 分段审批：链式命令逐段展示 */
.approval-segments {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}
.approval-segment {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.approval-segment-text {
  font-size: 12px;
  color: var(--nr-text-primary, inherit);
  background: var(--nr-bg-inset);
  border-radius: 4px;
  padding: 2px 8px;
  word-break: break-all;
}
.approval-reason {
  font-size: 13px;
  color: var(--nr-warning);
  line-height: 1.5;
}
.approval-hint {
  font-size: 12px;
  color: var(--nr-text-secondary);
  margin: 4px 0 0;
}
</style>
