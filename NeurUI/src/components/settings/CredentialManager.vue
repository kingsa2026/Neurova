<script setup lang="ts">
/**
 * 凭据管理（SSH 多主机 + RDP 直连端点），按当前登录用户隔离（后端 get_current_user 分桶）。
 *
 * 复用面：设置-高级（管理员）与"我的凭据"页（任意登录用户）都挂本组件。
 * 密钥/密码加密落盘，列表只回显脱敏状态，不回显值。
 * 社交平台凭据段已退役（§6-591）：social_search 登录态归上游 agent-reach CLI。
 */
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listSSHCredentials, upsertSSHCredential, deleteSSHCredential,
  getRdpCredential, upsertRdpCredential, deleteRdpCredential,
  type SshHost, type RdpCredentialStatus,
} from '@/api/modules/settings'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

// ── SSH 多主机凭据（computer_ssh_exec 消费）──
const sshHosts = ref<SshHost[]>([])
const sshForm = ref({ host: '', user: '', port: 22, auth: 'password', key_text: '', password: '' })
const savingSsh = ref(false)

const fetchSSHHosts = async () => {
  try {
    const res = await listSSHCredentials()
    const data = (res as any)?.data?.hosts ?? (res as any)?.hosts
    if (Array.isArray(data)) sshHosts.value = data
  } catch {
    // 非阻断
  }
}

const addSSHHost = async () => {
  const host = sshForm.value.host.trim()
  if (!host) {
    message.warning(t('settings.sshHostRequired'))
    return
  }
  if (sshForm.value.auth === 'key' ? !sshForm.value.key_text.trim() : !sshForm.value.password) {
    message.warning(t('settings.sshCredentialRequired'))
    return
  }
  savingSsh.value = true
  try {
    await upsertSSHCredential({
      host,
      user: sshForm.value.user.trim(),
      port: Number(sshForm.value.port) || 22,
      key_text: sshForm.value.auth === 'key' ? sshForm.value.key_text : '',
      password: sshForm.value.auth === 'password' ? sshForm.value.password : '',
    })
    sshForm.value = { host: '', user: '', port: 22, auth: 'password', key_text: '', password: '' }
    await fetchSSHHosts()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingSsh.value = false
  }
}

const removeSSHHost = async (host: string) => {
  try {
    await deleteSSHCredential(host)
    await fetchSSHHosts()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

// auth ∈ {key,password,agent} → camelCase i18n 键（守卫要求 section.key 无下划线）
const sshAuthLabel = (auth: string) =>
  t('settings.sshAuth' + (auth ? auth[0].toUpperCase() + auth.slice(1) : 'Agent'))

// ── RDP 直连端点（rdp_provider 消费；单记录，token 永不回显）──
const rdpStatus = ref<RdpCredentialStatus>({ configured: false, host: '', port: 8765, token_set: false })
const rdpForm = ref({ host: '', port: 8765, token: '' })
const savingRdp = ref(false)

const fetchRdpCredential = async () => {
  try {
    const res = await getRdpCredential()
    const data = (res as any)?.data ?? (res as any)
    if (data && typeof data === 'object') rdpStatus.value = { ...rdpStatus.value, ...data }
  } catch {
    // 非阻断
  }
}

const saveRdpCredential = async () => {
  if (!rdpForm.value.host.trim()) {
    message.warning(t('settings.rdpHostRequired'))
    return
  }
  if (!rdpForm.value.token && !rdpStatus.value.token_set) {
    message.warning(t('settings.rdpTokenRequired'))
    return
  }
  savingRdp.value = true
  try {
    await upsertRdpCredential({
      host: rdpForm.value.host.trim(),
      port: Number(rdpForm.value.port) || 8765,
      token: rdpForm.value.token,
    })
    rdpForm.value = { host: '', port: 8765, token: '' }
    await fetchRdpCredential()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingRdp.value = false
  }
}

const clearRdpCredential = async () => {
  try {
    await deleteRdpCredential()
    rdpForm.value = { host: '', port: 8765, token: '' }
    await fetchRdpCredential()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(() => {
  fetchSSHHosts()
  fetchRdpCredential()
})

// 测试/父组件可显式刷新与驱动
defineExpose({
  fetchSSHHosts,
  sshHosts, sshForm, addSSHHost, removeSSHHost,
  fetchRdpCredential,
  rdpStatus, rdpForm, saveRdpCredential, clearRdpCredential,
})
</script>

<template>
  <div class="credential-manager">
    <!-- SSH 远程主机凭据 -->
    <GlassCard :title="t('settings.sshHostsTitle')">
      <p class="cred-hint">{{ t('settings.sshHostsHint') }}</p>
      <div v-if="sshHosts.length" class="ssh-host-list">
        <div v-for="h in sshHosts" :key="h.host" class="ssh-host-row">
          <span class="ssh-host-name">{{ h.user ? h.user + '@' : '' }}{{ h.host }}:{{ h.port }}</span>
          <a-tag>{{ sshAuthLabel(h.auth) }}</a-tag>
          <GlassButton variant="ghost" size="sm" @click="removeSSHHost(h.host)">{{ t('common.delete') }}</GlassButton>
        </div>
      </div>
      <p v-else class="cred-hint">{{ t('settings.sshHostsEmpty') }}</p>
      <a-form layout="vertical" class="cred-form">
        <a-form-item :label="t('settings.sshHost')">
          <a-input v-model:value="sshForm.host" placeholder="10.0.0.5" />
        </a-form-item>
        <a-form-item :label="t('settings.sshUser')">
          <a-input v-model:value="sshForm.user" placeholder="root" />
        </a-form-item>
        <a-form-item :label="t('settings.sshPort')">
          <a-input-number v-model:value="sshForm.port" :min="1" :max="65535" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('settings.sshAuthType')">
          <a-select v-model:value="sshForm.auth" style="width: 100%">
            <a-select-option value="password">{{ t('settings.sshAuthPassword') }}</a-select-option>
            <a-select-option value="key">{{ t('settings.sshAuthKey') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-if="sshForm.auth === 'key'" :label="t('settings.sshPrivateKey')">
          <a-textarea v-model:value="sshForm.key_text" :rows="3" placeholder="-----BEGIN ... PRIVATE KEY-----" />
        </a-form-item>
        <a-form-item v-else :label="t('settings.sshPassword')">
          <a-input-password v-model:value="sshForm.password" />
        </a-form-item>
      </a-form>
      <template #footer>
        <GlassButton variant="primary" size="sm" :loading="savingSsh" @click="addSSHHost">{{ t('settings.sshAddHost') }}</GlassButton>
      </template>
    </GlassCard>

    <!-- RDP 直连端点（桌面会话提供者选 rdp 时消费） -->
    <GlassCard :title="t('settings.rdpCredentialsTitle')">
      <p class="cred-hint">{{ t('settings.rdpCredentialsHint') }}</p>
      <div v-if="rdpStatus.configured" class="rdp-status-row">
        <span class="rdp-endpoint-name">{{ rdpStatus.host }}:{{ rdpStatus.port }}</span>
        <a-tag :color="'green'">{{ t('settings.rdpConfigured') }}</a-tag>
        <GlassButton variant="ghost" size="sm" @click="clearRdpCredential">{{ t('settings.rdpClear') }}</GlassButton>
      </div>
      <p v-else class="cred-hint">{{ t('settings.rdpNotConfigured') }}</p>
      <a-form layout="vertical" class="cred-form">
        <a-form-item :label="t('settings.rdpHost')">
          <a-input v-model:value="rdpForm.host" placeholder="192.168.1.9" />
        </a-form-item>
        <a-form-item :label="t('settings.rdpPort')">
          <a-input-number v-model:value="rdpForm.port" :min="1" :max="65535" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('settings.rdpToken')">
          <a-input-password v-model:value="rdpForm.token" :placeholder="rdpStatus.token_set ? t('settings.rdpAlreadySet') : ''" />
        </a-form-item>
      </a-form>
      <template #footer>
        <GlassButton variant="primary" size="sm" :loading="savingRdp" @click="saveRdpCredential">{{ t('settings.rdpSave') }}</GlassButton>
      </template>
    </GlassCard>
  </div>
</template>

<style scoped>
.credential-manager { display: flex; flex-direction: column; gap: 16px; }
.cred-hint { font-size: 12px; opacity: 0.75; margin: 0 0 12px; }
.ssh-host-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.ssh-host-row { display: flex; align-items: center; gap: 10px; }
.ssh-host-name { font-family: 'Consolas', 'Menlo', monospace; flex: 1; }
.cred-form { border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 12px; }
.rdp-status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.rdp-endpoint-name { font-family: 'Consolas', 'Menlo', monospace; flex: 1; }
</style>
