<template>
  <div class="nr-auth-page">
    <Galaxy
      v-if="appStore.isDark"
      :hue-shift="140"
      :rotation="[0.8660254, 0.5]"
      :saturation="0.6"
      :glow-intensity="0.4"
      :twinkle-intensity="0.1"
      :rotation-speed="0.1"
      :density="0.6"
      :star-speed="0.4"
      :speed="0.9"
      :repulsion-strength="1.9"
    />
    <div class="nr-auth-container">
      <!-- GlassSurface 采用官方 live demo 字面值（经 /glass-demo 三变量对照实拍定案）：
           组件默认 brightness 50 / opacity 0.93 / blur 11 / distortion -180 / offsets 0·10·20 /
           difference，此处仅覆写 radius 27、bgOpacity 0.12、displace 0.5。
           参数为绝对像素语义，不做任何按尺寸的比例放大（放大位移量会把文字扯飞，见 D 实验）。 -->
      <GlassSurface
        width="100%"
        height="auto"
        :border-radius="27"
        :background-opacity="0.12"
        :displace="0.5"
        padding="40px 36px"
      >
        <div class="nr-auth-header">
          <BrandLogo size="lg" />
        </div>

        <!-- 首启向导：系统中无任何用户时（桌面版首次安装） -->
        <a-form
          v-if="needsSetup"
          :model="setupForm"
          layout="vertical"
          class="nr-auth-form"
        >
          <div class="nr-setup-intro">
            <h2 class="nr-auth-title">{{ t('auth.setupTitle') }}</h2>
            <p class="nr-auth-subtitle">{{ t('auth.setupHint') }}</p>
          </div>

          <a-form-item
            :label="t('auth.username')"
            name="username"
            :rules="[{ required: true, message: t('validation.required') }]"
          >
            <GlassInput
              v-model:model-value="setupForm.username"
              :placeholder="t('auth.username')"
              autocomplete="username"
              @update:model-value="setupForm.username = $event"
            />
          </a-form-item>

          <a-form-item
            :label="t('auth.password')"
            name="password"
            :rules="[{ required: true, message: t('validation.required') }]"
          >
            <GlassInput
              v-model:model-value="setupForm.password"
              type="password"
              :placeholder="t('auth.password')"
              autocomplete="new-password"
              @update:model-value="setupForm.password = $event"
            />
          </a-form-item>

          <a-form-item
            :label="t('auth.confirmPassword')"
            name="confirmPassword"
            :rules="[{ required: true, message: t('validation.required') }]"
          >
            <GlassInput
              v-model:model-value="setupForm.confirmPassword"
              type="password"
              :placeholder="t('auth.confirmPassword')"
              autocomplete="new-password"
              @update:model-value="setupForm.confirmPassword = $event"
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
            style="width: 100%"
            @click="handleSetup"
          >
            {{ t('auth.setupSubmit') }}
          </GlassButton>
        </a-form>

        <a-form
          v-else
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
            <router-link class="nr-auth-forgot" to="/forgot-password">{{ t('auth.forgotPassword') }}</router-link>
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

        <div v-if="!needsSetup" class="nr-auth-footer">
          {{ t('auth.noAccount') }}
          <router-link to="/register" class="nr-auth-link">
            {{ t('auth.register') }}
          </router-link>
        </div>
      </GlassSurface>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { authAPI } from '@/api/auth'
import Galaxy from '@/components/Galaxy.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import GlassSurface from '@/components/GlassSurface.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const appStore = useAppStore()

const form = reactive({
  username: '',
  password: '',
  remember: false,
})

// 首启向导状态：needsSetup=true 表示系统中还没有任何用户
const needsSetup = ref(false)
const setupForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
})

const loading = ref(false)
const error = ref<string | null>(null)

/** Restore remembered username on mount. */
onMounted(async () => {
  const saved = localStorage.getItem('nr_remembered_user')
  if (saved) {
    form.username = saved
    form.remember = true
  }

  // 首启检测：无任何用户 → 展示创建管理员向导（失败时静默回退登录表单）
  try {
    const res = (await authAPI.setupStatus()) as any
    const data = res?.data ?? res
    needsSetup.value = !!data?.needs_setup
  } catch {
    needsSetup.value = false
  }
})

/** 首启向导提交：注册首个用户（后端赋予管理员角色）并直接登录 */
async function handleSetup() {
  if (!setupForm.username.trim() || !setupForm.password || !setupForm.confirmPassword) return

  error.value = null
  if (setupForm.password !== setupForm.confirmPassword) {
    error.value = t('validation.passwordMismatch')
    return
  }

  loading.value = true
  try {
    const res = (await authAPI.setupRegister({
      username: setupForm.username.trim(),
      password: setupForm.password,
    })) as any
    const data = res?.data ?? res
    if (data?.access_token) {
      // 注册响应自带 token，持久化后拉取用户资料再进入主界面
      await authStore.setTokensFromRegistration({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
      })
      await authStore.fetchCurrentUser()
      router.push('/dashboard')
    } else {
      error.value = (res as any)?.message || t('auth.registerFailed')
    }
  } catch (err: any) {
    const netErr = err?.response ? null : await backendDiagnosis()
    error.value = netErr || err?.response?.data?.message || err?.message || t('auth.registerFailed')
  } finally {
    loading.value = false
  }
}

/**
 * 桌面环境网络层失败时的可行动诊断：查询壳的后端子进程状态。
 * - "running"（进程活着但 /health 未就绪）→ 后端仍在启动（首启要建索引）
 * - "exited"/"not started" → 后端启动失败或压根没拉起
 * 浏览器（非 Tauri）环境动态导入失败 → 返回 null，维持原错误文案。
 */
async function backendDiagnosis(): Promise<string | null> {
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const status = await invoke<string>('backend_status')
    if (status === 'running' || status === 'not started') {
      return t('auth.backendStarting')
    }
    if (status.startsWith('exited') || status.startsWith('error')) {
      return t('auth.backendFailed')
    }
  } catch {
    /* 非 Tauri 环境 */
  }
  return null
}

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
    } else if (authStore.lastNetworkFailed) {
      // 仅网络层失败（无 HTTP 响应）才做进程诊断；401 等有响应错误如实显示
      const diag = await backendDiagnosis()
      error.value = diag || authStore.error || t('auth.loginFailed')
    } else {
      error.value = authStore.error || t('auth.loginFailed')
    }
  } catch (err: any) {
    const netErr = err?.response ? null : await backendDiagnosis()
    error.value = netErr || err?.message || t('auth.loginFailed')
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
  /* 深空蓝底色：Galaxy 为透明模式画布，星流叠加在本底色上 */
  background: #090020;
  overflow: hidden;
}

.nr-auth-container {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 420px;
  padding: 20px;
  /* fill 禁用 forwards/both：动画结束后残留的 transform（哪怕恒等矩阵）会把本容器
     变成 backdrop 采样边界，GlassSurface 的折射采不到页面背景（2026-09-15 A/B 实拍定案） */
  animation: auth-enter 0.6s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}

@keyframes auth-enter {
  from {
    opacity: 0;
    transform: translateY(24px) scale(0.96);
  }
  /* to 帧不声明 transform：插值终点取基线值 none，动画结束后常态无 transform */
  to {
    opacity: 1;
  }
}

.nr-auth-header {
  text-align: center;
  margin-bottom: 32px;
}

.nr-setup-intro {
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
  border-top: 1px solid var(--nr-glass-border);
}

.nr-auth-link {
  color: var(--nr-primary-light);
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
  transition: color 0.2s;
}

.nr-auth-link:hover {
  color: var(--nr-primary);
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
