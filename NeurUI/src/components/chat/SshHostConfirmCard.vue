<script setup lang="ts">
/**
 * 会话内 SSH 主机确认卡（U1 TOFU：首连主机公钥未经确认时弹出）
 *
 * 触发：computer_ssh_exec 首连新主机 → 后端弹 needs_host_confirmation
 * （WS computer_action 载荷携带 host/port/fingerprint/key_type/agent_id）→ ChatPage 弹出本卡。
 * 确认：POST /v1/settings/ssh-credentials/host-key/confirm（agent 归属校验后按
 * (agent_id, host, port) 落 SshHostStore）；后端执行侧轮询到同指纹记录后原地重连，
 * 前端无需自己重发命令。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { confirmSshHostKey } from '@/api/modules/settings'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps<{
  host: string
  port?: number
  fingerprint?: string
  keyType?: string
  agentId?: string
}>()
const emit = defineEmits<{ (e: 'done'): void; (e: 'cancel'): void }>()
const { t } = useI18n()

const confirming = ref(false)

async function confirm() {
  confirming.value = true
  try {
    await confirmSshHostKey({
      agent_id: props.agentId || 'default',
      host: props.host,
      port: Number(props.port) || 22,
      fingerprint: props.fingerprint || '',
      key_type: props.keyType || '',
    })
    message.success(t('chat.sshHostConfirmPending'))
    emit('done')
  } catch {
    message.error(t('common.error'))
  } finally {
    confirming.value = false
  }
}
</script>

<template>
  <GlassCard :title="t('chat.sshHostConfirmTitle')" class="ssh-host-card">
    <p class="ssh-host-hint">{{ t('chat.sshHostConfirmHint', { host, port: port ?? 22 }) }}</p>
    <div class="ssh-host-rows">
      <div class="ssh-host-row">
        <span class="ssh-host-label">{{ t('chat.sshHostConfirmFingerprint') }}</span>
        <code class="ssh-host-fp" data-testid="ssh-host-fingerprint">{{ fingerprint || '—' }}</code>
      </div>
      <div class="ssh-host-row">
        <span class="ssh-host-label">{{ t('chat.sshHostConfirmKeyType') }}</span>
        <code data-testid="ssh-host-key-type">{{ keyType || '—' }}</code>
      </div>
    </div>
    <template #footer>
      <div class="ssh-host-actions">
        <GlassButton variant="ghost" size="sm" @click="emit('cancel')">{{ t('common.cancel') }}</GlassButton>
        <GlassButton variant="primary" size="sm" :loading="confirming" data-testid="ssh-host-confirm-btn" @click="confirm">
          {{ t('chat.sshHostConfirmConfirm') }}
        </GlassButton>
      </div>
    </template>
  </GlassCard>
</template>

<style scoped>
.ssh-host-card { max-width: 420px; }
.ssh-host-hint { font-size: 12px; opacity: 0.75; margin: 0 0 8px; }
.ssh-host-rows { display: flex; flex-direction: column; gap: 6px; }
.ssh-host-row { display: flex; align-items: baseline; gap: 8px; font-size: 12px; }
.ssh-host-label { flex-shrink: 0; opacity: 0.7; }
.ssh-host-fp { word-break: break-all; }
.ssh-host-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
