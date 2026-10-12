<template>
  <section class="nr-cid" data-testid="identity-panel">
    <div class="nr-cid-head">
      <div>
        <h3 class="nr-cid-title">{{ t('channel.identityTitle') }}</h3>
        <p class="nr-cid-desc">{{ t('channel.identityDesc') }}</p>
        <!-- 群共享作用域是裁定 ④ 的直接后果，必须写在这个面板上（不是只留在代码注释里）：
             用户若不知道"同一个群的成员会看到彼此在这个群里沉淀的记忆"，
             就等于把共享当成技术默认值替他做了决定。 -->
        <p class="nr-cid-scope" data-testid="identity-group-note">{{ t('channel.identityGroupScopeNote') }}</p>
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

      <!-- 观察面（批 6）：面板要列出"可绑的人"只有服务端这一面——人在自己那个渠道里
           抄不到 `ou_xxx`。这里只读：列进这张表不构成任何归属变化，绑定仍只能由
           那个渠道里那句带码的消息完成（持有证明）。 -->
      <div class="nr-cid-obs" data-testid="identity-observed">
        <p class="nr-cid-sub">{{ t('channel.identityObservedTitle') }}</p>
        <div v-if="observed.length === 0 && !errorText" class="nr-cid-empty"
             data-testid="identity-observed-empty">{{ t('channel.identityObservedEmpty') }}</div>
        <ul v-else class="nr-cid-obs-list">
          <li v-for="row in observed" :key="row.channel_type + ':' + row.channel_user_id"
              class="nr-cid-obs-row" data-testid="identity-observed-row">
            <span class="nr-cid-obs-who">{{ row.display_name || row.channel_user_id }}</span>
            <span class="nr-cid-obs-id">{{ row.channel_type }} · {{ row.channel_user_id }}</span>
            <a-tag :color="row.bound_user_id ? (isMine(row) ? 'green' : 'orange') : 'default'"
                   data-testid="identity-observed-state">{{ stateText(row) }}</a-tag>
          </li>
        </ul>
      </div>

      <!-- "我的绑定"取自服务端算出的那一面（响应里带着我这格的 user_id），
           前端不自拼身份——拼错了按钮就打在最不该动的行上。 -->
      <div v-if="mine.length > 0" class="nr-cid-mine" data-testid="identity-mine">
        <span class="nr-cid-sub">{{ t('channel.identityMineTitle') }}</span>
        <a-tag v-for="b in mine" :key="b.channel_type + b.channel_user_id"
               data-testid="identity-mine-chip">{{ b.channel_type }} · {{ b.channel_user_id }}</a-tag>
      </div>
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
  issueChannelBindingCode, listChannelIdentityBindings, listMyChannelIdentityBindings,
  listObservedChannelSenders, revokeChannelIdentityBinding,
  type ChannelBindingCode, type ChannelIdentityBinding, type ObservedChannelSender,
} from '@/api/modules/channel-configs'

const props = defineProps<{ agentId: string; channelTypes: string[] }>()

const { t } = useI18n()

const loading = ref(false)
const issuing = ref(false)
const rows = ref<ChannelIdentityBinding[]>([])
const observed = ref<ObservedChannelSender[]>([])
const mine = ref<{ channel_type: string; channel_user_id: string }[]>([])
const myUserId = ref('')
const issued = ref<ChannelBindingCode | null>(null)
const errorText = ref('')
const channelType = ref('')

const channelOptions = computed(() => props.channelTypes.map((c) => ({ value: c, label: c })))
const visibleRows = computed(() => rows.value)

/** "是不是我的"只比服务端给的 user_id，不读前端登录态缓存（两份身份迟早说两种话）。 */
function isMine(row: ObservedChannelSender): boolean {
  return !!row.bound_user_id && row.bound_user_id === myUserId.value
}

function stateText(row: ObservedChannelSender): string {
  if (!row.bound_user_id) return t('channel.identityObservedUnbound')
  if (isMine(row)) return t('channel.identityObservedBoundMe')
  return t('channel.identityObservedBoundOther', { user: row.bound_user_id })
}

function pickChannel(value: unknown) {
  channelType.value = String(value ?? '')
  issued.value = null
  errorText.value = ''
}

async function load() {
  loading.value = true
  try {
    const [bindingsRes, observedRes, mineRes] = await Promise.all([
      listChannelIdentityBindings(props.agentId),
      listObservedChannelSenders(props.agentId),
      listMyChannelIdentityBindings(props.agentId),
    ])
    rows.value = asList((bindingsRes as any)?.bindings ?? (bindingsRes as any)?.data?.bindings)
    observed.value = asList((observedRes as any)?.senders ?? (observedRes as any)?.data?.senders)
    const mineBody = (mineRes as any)?.data ?? mineRes
    mine.value = asList(mineBody?.bindings)
    myUserId.value = String(mineBody?.user_id ?? '')
    errorText.value = ''
  } catch (e: any) {
    // 403（非属主/非管理员）要说"无权"，不能退化成"还没有绑定"——后者会把
    // 权限问题伪装成空态，用户永远想不到去问属主要权限。
    rows.value = []
    observed.value = []
    mine.value = []
    errorText.value = failureText(e)
  } finally {
    loading.value = false
  }
}

function asList(value: unknown): any[] {
  return Array.isArray(value) ? value : []
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
.nr-cid-scope { margin: 6px 0 0; font-size: 12px; color: var(--nr-text-secondary); max-width: 60ch; }
.nr-cid-issue { display: flex; gap: 8px; align-items: center; }
.nr-cid-issued { margin: 12px 0 0; font-size: 12px; color: var(--nr-accent, #6366f1); }
.nr-cid-error { margin: 12px 0 0; font-size: 12px; color: var(--nr-color-danger, #e11d48); }
.nr-cid-empty { margin-top: 14px; font-size: 12px; color: var(--nr-text-tertiary); }
.nr-cid-table { width: 100%; margin-top: 14px; border-collapse: collapse; font-size: 12px; }
.nr-cid-table th { text-align: left; color: var(--nr-text-tertiary); font-weight: 500; padding: 6px 8px; }
.nr-cid-table td { padding: 8px; color: var(--nr-text-primary); border-top: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.06)); }
.nr-cid-table tr.revoked td { opacity: 0.55; }
.nr-cid-act { text-align: right; }
.nr-cid-sub { margin: 16px 0 6px; font-size: 12px; color: var(--nr-text-secondary); }
.nr-cid-obs-list { margin: 0; padding: 0; list-style: none; }
.nr-cid-obs-row {
  display: flex; align-items: center; gap: 10px; padding: 6px 0;
  border-top: 1px solid var(--nr-border-subtle, rgba(255, 255, 255, 0.06)); font-size: 12px;
}
.nr-cid-obs-who { color: var(--nr-text-primary); font-weight: 600; }
.nr-cid-obs-id { color: var(--nr-text-tertiary); }
.nr-cid-mine { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
