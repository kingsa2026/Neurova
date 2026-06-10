<template>
  <div class="nr-auth-page">
    <StarBackground />
    <div class="nr-auth-container">
      <GlassPanel variant="elevated" :radius="24" padding="40px 36px">
        <div class="nr-auth-header">
          <img src="/img/NEUROVA-LOGO350white.png" alt="Neurova Logo" class="nr-auth-logo-img" />
        </div>

        <a-form
          ref="formRef"
          :model="form"
          :rules="rules"
          @finish="handleRegister"
          layout="vertical"
          class="nr-auth-form"
        >
          <a-form-item :label="t('auth.username')" name="username">
            <GlassInput
              v-model:model-value="form.username"
              :placeholder="t('auth.username')"
              @update:model-value="form.username = $event"
            />
          </a-form-item>

          <a-form-item :label="t('auth.email')" name="email">
            <GlassInput
              v-model:model-value="form.email"
              type="email"
              :placeholder="t('auth.email')"
              @update:model-value="form.email = $event"
            />
          </a-form-item>

          <!-- Verification code row -->
          <a-form-item :label="t('auth.verifyCode')" name="code" class="nr-code-field">
            <div class="nr-code-row">
              <div class="nr-code-input">
                <GlassInput
                  v-model:model-value="form.code"
                  :placeholder="t('auth.verifyCode')"
                  @update:model-value="form.code = $event"
                />
              </div>
              <GlassButton
                variant="secondary"
                size="md"
                :loading="codeSending"
                :disabled="!form.email || codeCooldown > 0"
                @click="handleSendCode"
              >
                {{ codeCooldown > 0 ? `${codeCooldown}s` : t('auth.sendCode') }}
              </GlassButton>
            </div>
          </a-form-item>

          <a-form-item :label="t('auth.password')" name="password">
            <GlassInput
              v-model:model-value="form.password"
              type="password"
              :placeholder="t('auth.password')"
              @update:model-value="form.password = $event"
            />
          </a-form-item>

          <a-form-item :label="t('auth.confirmPassword')" name="confirmPassword">
            <GlassInput
              v-model:model-value="form.confirmPassword"
              type="password"
              :placeholder="t('auth.confirmPassword')"
              @update:model-value="form.confirmPassword = $event"
            />
          </a-form-item>

          <div class="nr-auth-terms">
            <a-checkbox v-model:checked="form.agreedTerms">
              {{ t('auth.agreeTo') }}
              <a href="#" class="nr-auth-link-inline">{{ t('auth.termsOfService') }}</a>
              {{ t('auth.and') }}
              <a href="#" class="nr-auth-link-inline">{{ t('auth.privacyPolicy') }}</a>
            </a-checkbox>
          </div>

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
            :disabled="!form.agreedTerms"
            style="width: 100%"
            @click="handleRegister"
          >
            {{ t('auth.register') }}
          </GlassButton>
        </a-form>

        <div class="nr-auth-footer">
          {{ t('auth.hasAccount') }}
          <router-link to="/login" class="nr-auth-link">
            {{ t('auth.login') }}
          </router-link>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { authAPI } from '@/api/auth'
import StarBackground from '@/components/StarBackground.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const formRef = ref()

const form = reactive({
  username: '',
  email: '',
  code: '',
  password: '',
  confirmPassword: '',
  agreedTerms: false,
})

const loading = ref(false)
const error = ref<string | null>(null)
const codeSending = ref(false)
const codeCooldown = ref(0)

let cooldownTimer: ReturnType<typeof setInterval> | null = null

/** Ant Design form validation rules. */
const rules = {
  username: [
    { required: true, message: t('validation.required') },
    { min: 3, max: 20, message: t('validation.minLength', { min: 3 }) },
    {
      pattern: /^[a-zA-Z0-9_]+$/,
      message: t('validation.username'),
    },
  ],
  email: [
    { required: true, message: t('validation.required') },
    { type: 'email' as const, message: t('validation.email') },
  ],
  password: [
    { required: true, message: t('validation.required') },
    { min: 8, message: t('validation.minLength', { min: 8 }) },
  ],
  confirmPassword: [
    { required: true, message: t('validation.required') },
    {
      validator: (_rule: unknown, value: string) => {
        if (value && value !== form.password) {
          return Promise.reject(t('validation.passwordMismatch'))
        }
        return Promise.resolve()
      },
    },
  ],
}

/** Send a verification code to the user's email. */
async function handleSendCode() {
  if (!form.email || codeCooldown.value > 0) return

  codeSending.value = true
  error.value = null

  try {
    await authAPI.sendCode(form.email)

    // Start cooldown timer (60 seconds)
    codeCooldown.value = 60
    cooldownTimer = setInterval(() => {
      codeCooldown.value -= 1
      if (codeCooldown.value <= 0 && cooldownTimer) {
        clearInterval(cooldownTimer)
        cooldownTimer = null
      }
    }, 1000)
  } catch (err: any) {
    error.value = err?.response?.data?.message || err?.message || 'Failed to send verification code.'
  } finally {
    codeSending.value = false
  }
}

/** Submit the registration form. */
async function handleRegister() {
  // Trigger Ant Design form validation
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  if (!form.agreedTerms) {
    error.value = 'Please agree to the Terms of Service.'
    return
  }

  error.value = null
  loading.value = true

  try {
    const success = await authStore.register({
      username: form.username,
      email: form.email,
      password: form.password,
      confirmPassword: form.confirmPassword,
      code: form.code || undefined,
      agreed_terms: form.agreedTerms,
      agreed_privacy: form.agreedTerms,
      register_source: 'web',
    })

    if (success) {
      router.push('/dashboard')
    } else {
      error.value = authStore.error || t('auth.loginFailed')
    }
  } catch (err: any) {
    error.value = err?.message || 'Registration failed. Please try again.'
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
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
  margin-bottom: 28px;
}

.nr-auth-logo-img {
  max-width: 280px;
  height: auto;
  margin: 0 auto 24px;
  display: block;
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

.nr-code-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.nr-code-input {
  flex: 1;
}

.nr-auth-terms {
  margin-bottom: 20px;
}

.nr-auth-link-inline {
  color: var(--nr-primary-light);
  text-decoration: none;
  font-weight: 500;
}

.nr-auth-link-inline:hover {
  text-decoration: underline;
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

/* Ant Design overrides for glass theme */
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

:deep(.ant-checkbox-wrapper) {
  color: var(--nr-text-secondary);
  font-size: 13px;
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
