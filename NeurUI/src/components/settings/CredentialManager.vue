<script setup lang="ts">
/**
 * 凭据管理（SSH 多主机 + 社交平台），按当前登录用户隔离（后端 get_current_user 分桶）。
 *
 * 复用面：设置-高级（管理员）与"我的凭据"页（任意登录用户）都挂本组件。
 * 密钥/密码加密落盘，列表只回显脱敏状态，不回显值。
 */
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listSSHCredentials, upsertSSHCredential, deleteSSHCredential,
  listSocialCredentials, setSocialCredential, clearSocialCredential,
  type SshHost, type SocialPlatformStatus,
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

// ── 社交平台凭据（web_reach social_exec 消费）──
const socialPlatforms = ref<SocialPlatformStatus[]>([])
const socialForm = ref<{ platform: string; credentials: Record<string, string> }>({ platform: '', credentials: {} })
const savingSocial = ref(false)

const fetchSocialCredentials = async () => {
  try {
    const res = await listSocialCredentials()
    const data = (res as any)?.data?.platforms ?? (res as any)?.platforms
    if (Array.isArray(data)) socialPlatforms.value = data
  } catch {
    // 非阻断
  }
}

const selectSocialPlatform = (platform: string) => {
  socialForm.value = { platform, credentials: {} }
}

const saveSocialCredentials = async () => {
  if (!socialForm.value.platform) {
    message.warning(t('settings.socialPlatformRequired'))
    return
  }
  if (!Object.values(socialForm.value.credentials).some((v) => v)) {
    message.warning(t('settings.socialCredentialRequired'))
    return
  }
  savingSocial.value = true
  try {
    await setSocialCredential(socialForm.value.platform, socialForm.value.credentials)
    socialForm.value = { platform: '', credentials: {} }
    await fetchSocialCredentials()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingSocial.value = false
  }
}

const clearSocialPlatform = async (platform: string) => {
  try {
    await clearSocialCredential(platform)
    await fetchSocialCredentials()
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(() => {
  fetchSSHHosts()
  fetchSocialCredentials()
})

// 测试/父组件可显式刷新与驱动
defineExpose({
  fetchSSHHosts, fetchSocialCredentials,
  sshHosts, sshForm, addSSHHost, removeSSHHost,
  socialPlatforms, socialForm, selectSocialPlatform, saveSocialCredentials, clearSocialPlatform,
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

    <!-- 社交平台凭据 -->
    <GlassCard :title="t('settings.socialCredentialsTitle')">
      <p class="cred-hint">{{ t('settings.socialCredentialsHint') }}</p>
      <div class="social-status-list">
        <div v-for="p in socialPlatforms" :key="p.platform" class="social-status-row">
          <span class="social-platform-name">{{ p.platform }}</span>
          <a-tag :color="p.configured ? 'green' : 'default'">
            {{ p.configured ? t('settings.socialConfigured') : t('settings.socialNotConfigured') }}
          </a-tag>
          <GlassButton v-if="p.configured" variant="ghost" size="sm" @click="clearSocialPlatform(p.platform)">{{ t('settings.socialClear') }}</GlassButton>
        </div>
      </div>
      <a-form layout="vertical" class="cred-form">
        <a-form-item :label="t('settings.socialPlatform')">
          <a-select :value="socialForm.platform" style="width: 100%" @change="selectSocialPlatform">
            <a-select-option v-for="p in socialPlatforms" :key="p.platform" :value="p.platform">{{ p.platform }}</a-select-option>
          </a-select>
        </a-form-item>
        <template v-if="socialForm.platform">
          <a-form-item v-for="k in (socialPlatforms.find(p => p.platform === socialForm.platform)?.keys || [])" :key="k.key" :label="k.key">
            <a-input-password v-model:value="socialForm.credentials[k.key]" :placeholder="k.set ? t('settings.socialAlreadySet') : ''" />
          </a-form-item>
        </template>
      </a-form>
      <template #footer>
        <GlassButton variant="primary" size="sm" :loading="savingSocial" @click="saveSocialCredentials">{{ t('settings.socialSave') }}</GlassButton>
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
.social-status-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.social-status-row { display: flex; align-items: center; gap: 10px; }
.social-platform-name { font-family: 'Consolas', 'Menlo', monospace; flex: 1; text-transform: capitalize; }
</style>
