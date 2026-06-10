<template>
  <div class="nr-auth-page">
    <StarBackground />
    <div class="nr-auth-container">
      <GlassPanel variant="elevated" :radius="24" padding="40px 36px">
        <div class="nr-auth-header">
          <img src="/img/NEUROVA-LOGO350white.png" alt="Neurova Logo" class="nr-auth-logo-img" />
        </div>

        <a-form
          :model="form"
          @finish="handleLogin"
          layout="vertical"
          class="nr-auth-form"
        >
          <a-form-item
            :label="t('auth.username')"
            name="username"
            :rules="[{ required: true, message: t('validation.required') }]"
          >
            <GlassInput
              v-model:model-value="form.username"
              :placeholder="t('auth.username')"
              autocomplete="username"
              @update:model-value="form.username = $event"
            />
          </a-form-item>

          <a-form-item
            :label="t('auth.password')"
            name="password"
            :rules="[{ required: true, message: t('validation.required') }]"
          >
            <GlassInput
              v-model:model-value="form.password"
              type="password"
              :placeholder="t('auth.password')"
              autocomplete="current-password"
              @update:model-value="form.password = $event"
            />
          </a-form-item>

          <div class="nr-auth-options">
            <a-checkbox v-model:checked="form.remember">
              {{ t('auth.rememberMe') }}
            </a-checkbox>
            <a class="nr-auth-forgot" href="#">{{ t('auth.forgotPassword') }}</a>
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
            style="width: 100%"
            @click="handleLogin"
          >
            {{ t('auth.login') }}
          </GlassButton>
        </a-form>

        <div class="nr-auth-footer">
          {{ t('auth.noAccount') }}
          <router-link to="/register" class="nr-auth-link">
            {{ t('auth.register') }}
          </router-link>
        </div>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import StarBackground from '@/components/StarBackground.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const form = reactive({
  username: '',
  password: '',
  remember: false,
})

const loading = ref(false)
const error = ref<string | null>(null)

/** Restore remembered username on mount. */
onMounted(() => {
  const saved = localStorage.getItem('nr_remembered_user')
  if (saved) {
    form.username = saved
    form.remember = true
  }
})

async function handleLogin() {
  if (!form.username.trim() || !form.password) return

  error.value = null
  loading.value = true

  try {
    const success = await authStore.login({
      username: form.username,
      password: form.password,
      remember: form.remember,
    })

    if (success) {
      // Persist remembered username
      if (form.remember) {
        localStorage.setItem('nr_remembered_user', form.username)
      } else {
        localStorage.removeItem('nr_remembered_user')
      }

      // Navigate to the originally requested page, or dashboard
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } else {
      error.value = authStore.error || t('auth.loginFailed')
    }
  } catch (err: any) {
    error.value = err?.message || t('auth.loginFailed')
  } finally {
    loading.value = false
  }
}
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
}

.nr-auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
  padding: 20px;
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
  margin-bottom: 32px;
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

.nr-auth-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.nr-auth-forgot {
  font-size: 13px;
  color: var(--nr-primary-light);
  text-decoration: none;
  transition: color 0.2s;
}

.nr-auth-forgot:hover {
  color: var(--nr-primary);
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

/* Override Ant Design form styling to blend with glass theme */
:deep(.ant-form-item-label > label) {
  color: var(--nr-text-secondary) !important;
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

:deep(.ant-form-item) {
  margin-bottom: 18px;
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
