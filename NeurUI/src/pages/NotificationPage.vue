<template>
  <div class="notification-page">
    <div class="page-header">
      <h2 class="page-title">
        {{ t('system.notifications') }}
        <a-badge :count="unreadCount" :offset="[8, -4]" />
      </h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" :loading="markingAll" @click="markAllRead">{{ t('common.markAllRead') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchNotifications">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <!-- Notification list -->
    <a-spin :spinning="loading">
      <div class="notification-list">
        <GlassPanel
          v-for="notif in notifications"
          :key="notif.id"
          :variant="notif.read ? 'subtle' : 'default'"
          class="notification-item"
          :class="{ unread: !notif.read, clickable: true }"
          @click="openDetail(notif)"
        >
          <div class="notif-content">
            <div class="notif-header">
              <span class="notif-title">{{ notif.title }}</span>
              <span class="notif-time">{{ formatTime(notif.created_at) }}</span>
            </div>
            <p class="notif-body">{{ notif.message }}</p>
            <div class="notif-meta">
              <a-tag v-if="notif.type" :color="typeColor(notif.type)" size="small">{{ notif.type }}</a-tag>
              <div class="notif-actions" @click.stop>
                <GlassButton v-if="!notif.read" variant="ghost" size="sm" @click="markRead(notif.id)">
                  {{ t('common.markRead') }}
                </GlassButton>
                <a-popconfirm :title="t('common.confirm') + '?'" @confirm="deleteNotif(notif.id)">
                  <GlassButton variant="ghost" size="sm">
                    {{ t('common.delete') }}
                  </GlassButton>
                </a-popconfirm>
              </div>
            </div>
          </div>
        </GlassPanel>
        <a-empty v-if="!notifications.length && !loading" :description="t('common.noData')" />
      </div>
    </a-spin>

    <!-- Pagination -->
    <div v-if="total > pageSize" class="pagination-row">
      <a-pagination v-model:current="page" :total="total" :page-size="pageSize" @change="onPageChange" />
    </div>

    <!-- Detail modal：点卡片查看详情；审批类通知（kb_review/skill_review）管理员就地审批 -->
    <a-modal v-model:open="detailVisible" :title="t('notification.detailTitle')" :footer="null" width="520px">
      <div v-if="detailNotif" class="notif-detail">
        <div class="notif-detail-header">
          <a-tag :color="typeColor(detailNotif.type)">{{ detailNotif.type }}</a-tag>
          <span class="notif-time">{{ formatTime(detailNotif.created_at) }}</span>
        </div>
        <h4 class="notif-detail-title">{{ detailNotif.title }}</h4>
        <p class="notif-detail-body">{{ detailNotif.message }}</p>

        <div v-if="detailFields.length" class="notif-detail-fields">
          <div v-for="f in detailFields" :key="f.label" class="field-row">
            <span class="field-label">{{ f.label }}</span>
            <span class="field-value">{{ f.value }}</span>
          </div>
        </div>

        <!-- 审批操作：仅管理员 + 审批类通知 -->
        <div v-if="canReview" class="notif-review">
          <a-textarea v-model:value="reviewNote" :rows="2" :placeholder="t('notification.reviewNotePh')" />
          <div class="notif-review-actions">
            <GlassButton variant="primary" size="sm" :loading="reviewing" @click="doReview(true)">
              {{ t('knowledge.reviewApprove') }}
            </GlassButton>
            <GlassButton variant="danger" size="sm" :loading="reviewing" @click="doReview(false)">
              {{ t('knowledge.reviewReject') }}
            </GlassButton>
          </div>
        </div>

        <div class="notif-detail-footer">
          <GlassButton variant="ghost" size="sm" @click="detailVisible = false">
            {{ t('notification.close') }}
          </GlassButton>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import * as notifApi from '@/api/modules/notifications'
import { reviewKnowledgePublic } from '@/api/modules/knowledge'
import { reviewSkillSubmission } from '@/api/modules/skill-pool'
import { useAuthStore } from '@/stores/auth'
import type { Notification } from '@/api/modules/notifications'

const { t } = useI18n()
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const markingAll = ref(false)
const notifications = ref<Notification[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const unreadCount = computed(() => notifications.value.filter(n => !n.read).length)

const typeColor = (type: string) => {
  const map: Record<string, string> = {
    info: 'blue',
    warning: 'orange',
    error: 'red',
    success: 'green',
    // 业务闭环类型
    kb_review: 'purple',
    kb_review_result: 'geekblue',
    skill_review: 'purple',
    skill_review_result: 'geekblue',
    market_update: 'cyan',
    // P1-11 审批状态机镜像（approval_manager 通知路由）
    approval_request: 'orange',
    approval_result: 'geekblue',
  }
  return map[type] || 'default'
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchNotifications = async () => {
  loading.value = true
  try {
    const res = await notifApi.getNotifications({ page: page.value, size: pageSize.value })
    const data = res?.data
    notifications.value = data?.items ?? (Array.isArray(data) ? data : [])
    total.value = data?.total ?? notifications.value.length
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const markRead = async (id: string) => {
  try {
    await notifApi.markRead(id)
    const notif = notifications.value.find(n => n.id === id)
    if (notif) notif.read = true
  } catch {
    message.error(t('common.error'))
  }
}

const markAllRead = async () => {
  markingAll.value = true
  try {
    await notifApi.markAllRead()
    notifications.value.forEach(n => { n.read = true })
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    markingAll.value = false
  }
}

const deleteNotif = async (id: string) => {
  try {
    await notifApi.deleteNotification(id)
    notifications.value = notifications.value.filter(n => n.id !== id)
    total.value = Math.max(0, total.value - 1)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

const onPageChange = (p: number) => { page.value = p; fetchNotifications() }

// ── 详情弹窗 + 就地审批（2026-09-01 二期） ─────────────────

const detailVisible = ref(false)
const detailNotif = ref<Notification | null>(null)
const reviewNote = ref('')
const reviewing = ref(false)

/** 审批类通知判定：数据里带审核目标 id（knowledge_id / submission_id） */
const isReviewNotif = computed(() => {
  const d = (detailNotif.value?.data ?? {}) as Record<string, unknown>
  return !!(d.knowledge_id || d.submission_id)
})

const canReview = computed(() => isAdmin.value && isReviewNotif.value)

/** 详情负载数据的展示字段（按类型取关键 id，白名单避免内部字段裸奔） */
const detailFields = computed(() => {
  const d = (detailNotif.value?.data ?? {}) as Record<string, unknown>
  const rows: { label: string; value: string }[] = []
  if (d.knowledge_id) rows.push({ label: t('notification.knowledgeId'), value: String(d.knowledge_id) })
  if (d.skill_id) rows.push({ label: t('notification.skillId'), value: String(d.skill_id) })
  if (d.name) rows.push({ label: t('notification.skillName'), value: String(d.name) })
  if (d.submitter_name) rows.push({ label: t('notification.submitter'), value: String(d.submitter_name) })
  return rows
})

async function openDetail(notif: Notification) {
  detailNotif.value = notif
  reviewNote.value = ''
  detailVisible.value = true
  if (!notif.read) {
    try {
      await notifApi.markRead(notif.id)
      notif.read = true
    } catch {
      // 标记已读失败不阻断查看
    }
  }
}

async function doReview(approve: boolean) {
  const d = (detailNotif.value?.data ?? {}) as Record<string, unknown>
  reviewing.value = true
  try {
    if (d.knowledge_id) {
      await reviewKnowledgePublic(String(d.knowledge_id), approve, reviewNote.value)
    } else if (d.submission_id) {
      await reviewSkillSubmission(String(d.submission_id), approve, reviewNote.value)
    }
    message.success(t('notification.reviewSuccess'))
    detailVisible.value = false
    await fetchNotifications()
  } catch (err: any) {
    const msg = err?.response?.data?.detail || err?.message || t('notification.reviewError')
    message.error(msg)
  } finally {
    reviewing.value = false
  }
}

onMounted(fetchNotifications)
</script>

<style scoped>
.notification-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; display: flex; align-items: center; gap: 8px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.notification-list { display: flex; flex-direction: column; gap: 12px; }
.notification-item { transition: all 0.2s; }
.notification-item.unread { border-left: 3px solid #6366f1; }
.notification-item.clickable { cursor: pointer; }
.notification-item.clickable:hover { transform: translateY(-1px); }

/* 详情弹窗 */
.notif-detail-header { display: flex; align-items: center; gap: 8px; }
.notif-detail-title { margin: 10px 0 4px; font-size: 15px; color: var(--nr-text-primary); }
.notif-detail-body { font-size: 13px; color: var(--nr-text-secondary); }
.notif-detail-fields { margin: 10px 0; padding: 8px 10px; border-radius: 8px; background: rgba(99, 102, 241, 0.06); }
.field-row { display: flex; gap: 8px; font-size: 12px; padding: 2px 0; }
.field-label { color: var(--nr-text-muted); min-width: 72px; }
.field-value { color: var(--nr-text-secondary); font-family: var(--nr-font-mono); word-break: break-all; }
.notif-review { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.notif-review-actions { display: flex; gap: 8px; }
.notif-detail-footer { margin-top: 12px; display: flex; justify-content: flex-end; }
.notif-content { display: flex; flex-direction: column; gap: 8px; }
.notif-header { display: flex; justify-content: space-between; align-items: center; }
.notif-title { font-weight: 600; color: var(--nr-text-primary); font-size: 14px; }
.notif-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.notif-body { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.notif-meta { display: flex; justify-content: space-between; align-items: center; }
.notif-actions { display: flex; gap: 6px; }
.pagination-row { display: flex; justify-content: center; padding-top: 8px; }
</style>
