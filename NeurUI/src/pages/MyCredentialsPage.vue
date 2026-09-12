<script setup lang="ts">
/**
 * 我的凭据 —— 任意登录用户自管 SSH 主机 / 社交平台凭据（按当前用户隔离）。
 *
 * 与设置-高级（管理员）共用 CredentialManager；后端按 get_current_user 分桶加密存储，
 * 用户之间互不可见。非管理员无需进 admin 设置页即可在此管理自己的凭据。
 */
import { useI18n } from 'vue-i18n'
import CredentialManager from '@/components/settings/CredentialManager.vue'

const { t } = useI18n()
</script>

<template>
  <div class="my-credentials-page">
    <h2 class="page-title">{{ t('nav.myCredentials') }}</h2>
    <p class="page-hint">{{ t('settings.myCredentialsHint') }}</p>
    <CredentialManager />
  </div>
</template>

<style scoped>
.my-credentials-page { padding: 4px; }
.page-title { margin: 0 0 4px; }
.page-hint { font-size: 13px; opacity: 0.75; margin: 0 0 16px; }
</style>
