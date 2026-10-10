<template>
  <section class="nr-cid" data-testid="identity-panel">
    <div class="nr-cid-head">
      <div>
        <h3 class="nr-cid-title">{{ t('channel.identityTitle') }}</h3>
        <p class="nr-cid-desc">{{ t('channel.identityDesc') }}</p>
      </div>
      <div class="nr-cid-issue">
        <a-select class="nr-cid-select" data-testid="identity-channel-select" :value="channelType"
          size="small" style="width: 160px" :options="channelOptions" @change="pickChannel" />
        <GlassButton size="sm" variant="primary" data-testid="identity-issue"
          :disabled="!channelType || issuing" @click="issue">
          {{ issuing ? t('channel.identityIssuing') : t('channel.identityIssue') }}
        </GlassButton>
      </div>
    </div>

    <p v-if="issued" class="nr-cid-issued" data-testid="identity-issued-command">
      {{ t('channel.identityIssued', { command: issued.command, seconds: issued.expires_in }) }}
    </p>
    <p v-if="errorText" class="nr-cid-error" data-testid="identity-error">{{ errorText }}</p>

    <a-spin :spinning="loading">
      <!-- 空态只在"真的读到了空列表"时出现：读失败（尤其 403）时挂着"还没有绑定"，
           等于把权限问题伪装成空数据，用户永远想不到去要权限。 -->
      <div v-if="visibleRows.length === 0 && !errorText" class="nr-cid-empty" data-testid="identity-empty">
        {{ t('channel.identityEmpty') }}
      </div>
      <table v-else class="nr-cid-table">
        <thead>
          <tr>
            <th>{{ t('channel.identityColSender') }}</th>
            <th>{{ t('channel.identityColAccount') }}</th>
            <th>{{ t('channel.identityColBoundBy') }}</th>
            <th>{{ t('channel.identityColStatus') }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.channel_type + ':' + row.channel_user_id"
            data-testid="identity-row" :class="{ revoked: row.status === 'revoked' }">
            <td><b>{{ row.channel_type }}</b> · {{ row.channel_user_id }}</td>
            <td>{{ row.user_id }}</td>
            <td>{{ row.bound_by || '—' }}</td>
            <td>
              <a-tag :color="row.status === 'active' ? 'green' : 'default'">
                {{ row.status === 'active' ? t('channel.identityActive') : t('channel.identityRevoked') }}
              </a-tag>
            </td>
            <td class="nr-cid-act">
              <GlassButton v-if="row.status === 'active'" size="sm" variant="danger"
                :data-testid="'identity-revoke-' + row.channel_user_id" @click="revoke(row)">
                {{ t('channel.identityRevoke') }}
              </GlassButton>
            </td>
          </tr>
        </tbody>
      </table>
    </a-spin>
  </section>
</template>

<script setup lang="ts">
/**
 * 渠道身份绑定面板（工单 2026-10-10 批 4b）。
 *
 * 面板只做两件事：**发码**与**解绑**。刻意没有"选一个渠道发送者、再挑一个平台账号
 * 绑上"那种下拉——那等于把归属的决定权交给点面板的人，而绑定一旦生效，那个渠道发送者
 * 此后写进的记忆就落在被选账号名下（不可逆）。归属只从登录态出（发码即本人），
 * 手工指定账号那条路径留在服务端按管理员门放行，不在前端提供入口。
 *
 * 已解绑的行**继续显示**：这张表要答得出"这个人以前算谁的"，删行即失忆。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import {
  issueChannelBindingCode, listChannelIdentityBindings, revokeChannelIdentityBinding,
  type ChannelBindingCode, type ChannelIdentityBinding,
} from '@/api/modules/channel-configs'

const props = defineProps<{ agentId: string; channelTypes: string[] }>()

const { t } = useI18n()

const loading = ref(false)
const issuing = ref(false)
const rows = ref<ChannelIdentityBinding[]>([])
const issued = ref<ChannelBindingCode | null>(null)
const errorText = ref('')
const channelType = ref('')

const channelOptions = computed(() => props.channelTypes.map((c) => ({ value: c, label: c })))
const visibleRows = computed(() => rows.value)

function pickChannel(value: unknown) {
  channelType.value = String(value ?? '')
  issued.value = null
  errorText.value = ''
}

async function load() {
  loading.value = true
  try {
    const res = await listChannelIdentityBindings(props.agentId)
    const list = (res as any)?.bindings ?? (res as any)?.data?.bindings ?? []
    rows.value = Array.isArray(list) ? list : []
    errorText.value = ''
  } catch (e: any) {
    // 403（非属主/非管理员）要说"无权"，不能退化成"还没有绑定"——后者会把
    // 权限问题伪装成空态，用户永远想不到去问属主要权限。
    rows.value = []
    errorText.value = failureText(e)
  } finally {
    loading.value = false
  }
}

function failureText(e: any): string {
  const status = e?.response?.status
  if (status === 403) return t('channel.identityDenied')
  return t('channel.identityFailed', {
    reason: String(e?.response?.data?.detail || e?.message || ''),
  })
}

async function issue() {
  if (!channelType.value || issuing.value) return
  issuing.value = true
  errorText.value = ''
  issued.value = null
  try {
    const res = await issueChannelBindingCode(props.agentId, channelType.value)
    issued.value = ((res as any)?.code ? res : (res as any)?.data) as ChannelBindingCode
    await load()
  } catch (e: any) {
    errorText.value = failureText(e)
  } finally {
    issuing.value = false
  }
}

async function revoke(row: ChannelIdentityBinding) {
  errorText.value = ''
  try {
    await revokeChannelIdentityBinding({
      agent_id: props.agentId,
      channel_type: row.channel_type,
      channel_user_id: row.channel_user_id,
    })
    await load()
  } catch (e: any) {
    errorText.value = failureText(e)
  }
}

watch(() => props.agentId, () => { issued.value = null; load() }, { immediate: true })
</script>

<style scoped>
.nr-cid { margin-top: 24px; padding: 16px 18px; border: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.1)); border-radius: 14px; }
.nr-cid-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.nr-cid-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--nr-text-primary); }
.nr-cid-desc { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-tertiary); max-width: 60ch; }
.nr-cid-issue { display: flex; gap: 8px; align-items: center; }
.nr-cid-issued { margin: 12px 0 0; font-size: 12px; color: var(--nr-accent, #6366f1); }
.nr-cid-error { margin: 12px 0 0; font-size: 12px; color: var(--nr-color-danger, #e11d48); }
.nr-cid-empty { margin-top: 14px; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-cid-table { width: 100%; margin-top: 14px; border-collapse: collapse; font-size: 12px; }
.nr-cid-table th { text-align: left; color: var(--nr-text-tertiary); font-weight: 500; padding: 6px 8px; }
.nr-cid-table td { padding: 8px; color: var(--nr-text-primary); border-top: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.06)); }
.nr-cid-table tr.revoked td { opacity: 0.55; }
.nr-cid-act { text-align: right; }
</style>
