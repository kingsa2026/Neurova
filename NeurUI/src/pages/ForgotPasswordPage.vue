<template>
  <div class="nr-auth-page">
    <StarBackground v-if="appStore.isDark" />
    <div class="nr-auth-container">
      <GlassPanel variant="elevated" :radius="24" padding="40px 36px">
        <div class="nr-auth-header">
          <BrandLogo size="lg" />
          <h2 class="nr-auth-title">{{ t('auth.recoverTitle') }}</h2>
          <p class="nr-auth-subtitle">{{ t('auth.recoverSubtitle') }}</p>
        </div>

        <!-- 第一步：身份验证（管理员账号 + 最高权重密码，缺一不可） -->
        <div v-if="step === 'identity'" class="nr-recover-step">
          <h3 class="nr-step-heading">{{ t('auth.recoverStep1') }}</h3>
          <a-form layout="vertical" class="nr-auth-form" @finish="goSetup">
            <a-form-item :label="t('auth.recoverAdminPh')" name="adminAccount">
              <GlassInput
                v-model:model-value="form.adminAccount"
                :placeholder="t('auth.recoverAdminPh')"
                autocomplete="username"
                @update:model-value="form.adminAccount = $event"
              />
            </a-form-item>

            <a-form-item :label="t('auth.recoverMasterPh')" name="masterPassword">
              <GlassInput
                v-model:model-value="form.masterPassword"
                type="password"
                :placeholder="t('auth.recoverMasterPh')"
                autocomplete="off"
                @update:model-value="form.masterPassword = $event"
              />
              <p class="nr-step-hint">{{ t('auth.recoverMasterHint') }}</p>
            </a-form-item>

            <a-alert
              v-if="error"
              :message="error"
              type="error"
              show-icon
              closable
              style="margin-bottom: 16px"
              @close="error = null"
            />

            <GlassButton
              variant="primary"
              size="lg"
              :disabled="!identityComplete"
              style="width: 100%"
              @click="goSetup"
            >
              {{ t('auth.recoverNext') }}
            </GlassButton>
          </a-form>
        </div>

        <!-- 第二步：设置新密码 -->
        <div v-else class="nr-recover-step">
          <h3 class="nr-step-heading">{{ t('auth.recoverStep2') }}</h3>
          <a-form layout="vertical" class="nr-auth-form" @finish="handleRecover">
            <a-form-item :label="t('auth.recoverNewPh')" name="newPassword">
              <GlassInput
                v-model:model-value="form.newPassword"
                type="password"
                :placeholder="t('auth.recoverNewPh')"
                autocomplete="new-password"
                @update:model-value="form.newPassword = $event"
              />
            </a-form-item>

            <a-form-item :label="t('auth.recoverConfirmPh')" name="confirmPassword">
              <GlassInput
                v-model:model-value="form.confirmPassword"
                type="password"
                :placeholder="t('auth.recoverConfirmPh')"
                autocomplete="new-password"
                @update:model-value="form.confirmPassword = $event"
              />
            </a-form-item>

            <a-alert
              v-if="error"
              :message="error"
              type="error"
              show-icon
              closable
              style="margin-bottom: 16px"
              @close="error = null"
            />

            <GlassButton
              variant="primary"
              size="lg"
              :loading="loading"
              :disabled="!newPasswordComplete"
              style="width: 100%"
              @click="handleRecover"
            >
              {{ t('auth.recoverSubmit') }}
            </GlassButton>
          </a-form>

          <GlassButton variant="ghost" size="sm" style="width: 100%" @click="backToIdentity">
            {{ t('auth.recoverBackLogin') }}
          </GlassButton>
        </div>

        <div class="nr-auth-footer">
          <router-link to="/login" class="nr-auth-link">
            {{ t('auth.recoverBackLogin') }}
          </router-link>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { authAPI } from '@/api/auth'
import { useAppStore } from '@/stores/app'
import StarBackground from '@/components/StarBackground.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()
const router = useRouter()
const appStore = useAppStore()

const step = ref<'identity' | 'setup'>('identity')
const loading = ref(false)
const error = ref<string | null>(null)

const form = reactive({
  adminAccount: '',
  masterPassword: '',
  newPassword: '',
  confirmPassword: '',
})

// 双条件缺一不可：管理员账号 + 最高权重密码都必须输入才能进入下一步
const identityComplete = computed(() => !!(form.adminAccount.trim() && form.masterPassword))
const newPasswordComplete = computed(() => !!(form.newPassword && form.confirmPassword))

function goSetup() {
  if (!identityComplete.value) {
    error.value = t('auth.recoverBothRequired')
    return
  }
  error.value = null
  step.value = 'setup'
}

function backToIdentity() {
  error.value = null
  step.value = 'identity'
}

async function handleRecover() {
  if (!newPasswordComplete.value) {
    error.value = t('validation.required')
    return
  }
  error.value = null
  loading.value = true
  try {
    await authAPI.recoverPassword({
      username: form.adminAccount.trim(),
      master_password: form.masterPassword,
      new_password: form.newPassword,
      confirm_password: form.confirmPassword,
    })
    message.success(t('auth.recoverSuccess'))
    router.push('/login')
  } catch (err: any) {
    const detail = err?.response?.data?.detail
    error.value =
      detail === '尝试次数过多，请 15 分钟后再试'
        ? detail
        : err?.response?.data?.detail || t('auth.recoverFailed')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  document.title = `${t('auth.recoverTitle')} · Neurova`
})
</script>

<style scoped>
.nr-auth-page {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--nr-bg-deep);
  overflow: hidden;
  overflow-y: auto;
}

.nr-auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 440px;
  padding: 20px;
  margin: 40px auto;
  animation: auth-enter 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes auth-enter {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.nr-auth-header {
  text-align: center;
  margin-bottom: 24px;
}

.nr-auth-title {
  font-family: var(--nr-font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--nr-text-primary);
  letter-spacing: -0.03em;
  margin: 0 0 6px;
}

.nr-auth-subtitle {
  font-size: 14px;
  color: var(--nr-text-tertiary);
  margin: 0;
}

.nr-auth-form {
  margin-bottom: 20px;
}

.nr-step-heading {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--nr-primary-light);
  margin: 0 0 16px;
}

.nr-step-hint {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  margin: 6px 0 0;
  line-height: 1.6;
}

.nr-auth-footer {
  text-align: center;
  font-size: 13px;
  color: var(--nr-text-tertiary);
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.nr-auth-link {
  color: var(--nr-primary-light);
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
  transition: color 0.2s;
}

.nr-auth-link:hover {
  color: white;
  text-decoration: underline;
}

:deep(.ant-form-item-label > label) {
  color: var(--nr-text-secondary) !important;
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

:deep(.ant-form-item) {
  margin-bottom: 16px;
}

:deep(.ant-alert) {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
}

:deep(.ant-alert-message) {
  color: var(--nr-text-primary) !important;
  font-size: 13px;
}
</style>
