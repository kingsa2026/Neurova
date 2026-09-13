<script setup lang="ts">
/**
 * 会话内按需 SSH 凭据卡（agent 交互卡片，按当前登录用户隔离）
 *
 * 触发：computer_ssh_exec 发现该主机无凭据 → 结果携带 needs_credential → ChatPage 弹出本卡。
 * 提交：POST /v1/settings/ssh-credentials（后端按当前用户分桶加密落盘），保存后 emit('done')
 * 供 agent 重试。密钥/密码不回显、不落前端存储。
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { upsertSSHCredential } from '@/api/modules/settings'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps<{ host: string }>()
const emit = defineEmits<{ (e: 'done'): void; (e: 'cancel'): void }>()
const { t } = useI18n()

const form = ref({ user: '', port: 22, auth: 'password', key_text: '', password: '' })
const saving = ref(false)

async function save() {
  if (form.value.auth === 'key' ? !form.value.key_text.trim() : !form.value.password) {
    message.warning(t('settings.sshCredentialRequired'))
    return
  }
  saving.value = true
  try {
    await upsertSSHCredential({
      host: props.host,
      user: form.value.user.trim(),
      port: Number(form.value.port) || 22,
      key_text: form.value.auth === 'key' ? form.value.key_text : '',
      password: form.value.auth === 'password' ? form.value.password : '',
    })
    message.success(t('common.success'))
    emit('done')
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <GlassCard :title="t('chat.sshCredentialTitle')" class="ssh-cred-card">
    <p class="ssh-cred-hint">{{ t('chat.sshCredentialHint', { host }) }}</p>
    <a-form layout="vertical">
      <a-form-item :label="t('settings.sshUser')">
        <a-input v-model:value="form.user" placeholder="root" />
      </a-form-item>
      <a-form-item :label="t('settings.sshPort')">
        <a-input-number v-model:value="form.port" :min="1" :max="65535" style="width: 100%" />
      </a-form-item>
      <a-form-item :label="t('settings.sshAuthType')">
        <a-select v-model:value="form.auth" style="width: 100%">
          <a-select-option value="password">{{ t('settings.sshAuthPassword') }}</a-select-option>
          <a-select-option value="key">{{ t('settings.sshAuthKey') }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item v-if="form.auth === 'key'" :label="t('settings.sshPrivateKey')">
        <a-textarea v-model:value="form.key_text" :rows="3" placeholder="-----BEGIN ... PRIVATE KEY-----" />
      </a-form-item>
      <a-form-item v-else :label="t('settings.sshPassword')">
        <a-input-password v-model:value="form.password" />
      </a-form-item>
    </a-form>
    <template #footer>
      <div class="ssh-cred-actions">
        <GlassButton variant="ghost" size="sm" @click="emit('cancel')">{{ t('common.cancel') }}</GlassButton>
        <GlassButton variant="primary" size="sm" :loading="saving" @click="save">{{ t('settings.sshAddHost') }}</GlassButton>
      </div>
    </template>
  </GlassCard>
</template>

<style scoped>
.ssh-cred-card { max-width: 420px; }
.ssh-cred-hint { font-size: 12px; opacity: 0.75; margin: 0 0 8px; }
.ssh-cred-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
