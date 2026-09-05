<template>
  <div class="register-container">
    <!-- 星空背景 -->
    <StarBackground />
    
    <!-- 注册表单 -->
    <GlassContainer class="register-card-inner" :corner-radius="24" :blur-amount="2.5" :saturation="200" :aberration-intensity="0" displacement-scale="10" :glass-size="{ width: 440, height: 700 }">
      <!-- Logo 和标题 -->
      <div class="register-header">
        <img :src="logoWhite" alt="Neurova" class="register-logo" />
      </div>
      
      <!-- 注册表单 -->
      <a-form
        :model="formState"
        @finish="handleRegister"
        layout="vertical"
        class="register-form"
      >
        <!-- 用户名 -->
        <a-form-item
          name="username"
          :rules="[
            { required: true, message: '请输入用户名' },
            { min: 3, max: 20, message: '用户名长度为3-20个字符' }
          ]"
        >
          <a-input
            v-model:value="formState.username"
            placeholder="用户名"
            size="large"
            class="input-dark"
          >
            <template #prefix>
              <UserOutlined style="color: rgba(255, 255, 255, 0.4)" />
            </template>
          </a-input>
        </a-form-item>
        
        <!-- 邮箱 -->
        <a-form-item
          name="email"
          :rules="[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '请输入有效的邮箱地址' }
          ]"
        >
          <a-input
            v-model:value="formState.email"
            placeholder="邮箱"
            size="large"
            class="input-dark"
          >
            <template #prefix>
              <MailOutlined style="color: rgba(255, 255, 255, 0.4)" />
            </template>
          </a-input>
        </a-form-item>
        
        <!-- 密码 -->
        <a-form-item
          name="password"
          :rules="[
            { required: true, message: '请输入密码' },
            { min: 8, message: '密码长度至少为8个字符' }
          ]"
        >
          <a-input-password
            v-model:value="formState.password"
            placeholder="密码"
            size="large"
            class="input-dark"
          >
            <template #prefix>
              <LockOutlined style="color: rgba(255, 255, 255, 0.4)" />
            </template>
          </a-input-password>
        </a-form-item>
        
        <!-- 确认密码 -->
        <a-form-item
          name="confirmPassword"
          :rules="[
            { required: true, message: '请确认密码' },
            { validator: validateConfirmPassword }
          ]"
        >
          <a-input-password
            v-model:value="formState.confirmPassword"
            placeholder="确认密码"
            size="large"
            class="input-dark"
          >
            <template #prefix>
              <LockOutlined style="color: rgba(255, 255, 255, 0.4)" />
            </template>
          </a-input-password>
        </a-form-item>
        
        <!-- 注册按钮 -->
        <a-form-item>
          <a-button
            type="primary"
            html-type="submit"
            size="large"
            :loading="loading"
            class="register-button btn-primary"
          >
            注册
          </a-button>
        </a-form-item>
        
        <!-- 错误提示 -->
        <a-alert
          v-if="error"
          :message="error"
          type="error"
          show-icon
          class="error-alert"
        />
      </a-form>
      
      <!-- 登录链接 -->
      <div class="register-footer">
        <span class="footer-text">已有账号？</span>
        <router-link to="/login" class="login-link">
          立即登录
        </router-link>
      </div>
    </GlassContainer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'
import StarBackground from '@/components/StarBackground.vue'
import { GlassContainer } from '@/components/NeuGlass'
import logoWhite from '@/assets/img/NEUROVA-white.png'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const error = ref<string | null>(null)

const formState = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// 验证确认密码
function validateConfirmPassword(_: unknown, value: string) {
  if (!value) {
    return Promise.reject('请确认密码')
  }
  if (value !== formState.password) {
    return Promise.reject('两次输入的密码不一致')
  }
  return Promise.resolve()
}

async function handleRegister() {
  loading.value = true
  error.value = null
    
  try {
    const result = await authStore.register({
      username: formState.username,
      email: formState.email,
      password: formState.password,
      confirmPassword: formState.confirmPassword
    })
    
    if (result.success) {
      message.success('注册成功')
      router.push('/dashboard')
    } else {
      error.value = result.message || '注册失败'
    }
  } catch (err: unknown) {
    const e = err as {message?:string}
    error.value = e.message || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.register-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.register-card-inner {
  position: relative;
  z-index: 10;
  width: 420px;
  padding: 3rem 2.5rem;
  animation: fadeInUp 0.6s ease-out;
  box-sizing: border-box;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.register-header {
  text-align: center;
  margin-bottom: 2.5rem;
  position: relative;
  z-index: 1;
}

.register-logo {
  max-height: 80px;
  max-width: 320px;
  object-fit: contain;
  filter: brightness(1.2) drop-shadow(0 2px 8px rgba(0,0,0,0.3));
  position: relative;
  z-index: 1;
}

.register-form {
  margin-top: 1rem;
}

:deep(.input-dark) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: white !important;
  border-radius: 0.5rem !important;
}

:deep(.input-dark:hover) {
  border-color: rgba(59, 130, 246, 0.5) !important;
}

:deep(.input-dark:focus) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
}

:deep(.input-dark input) {
  background: transparent !important;
  color: white !important;
}

:deep(.input-dark input::placeholder) {
  color: rgba(255, 255, 255, 0.4) !important;
}

:deep(.ant-input-password-icon) {
  color: rgba(255, 255, 255, 0.4) !important;
}

.register-button {
  width: 100%;
  height: 48px;
  font-size: 1rem;
  margin-top: 0.5rem;
}

.error-alert {
  margin-top: 1rem;
  background: rgba(239, 68, 68, 0.1) !important;
  border: 1px solid rgba(239, 68, 68, 0.3) !important;
}

:deep(.error-alert .ant-alert-message) {
  color: #ef4444 !important;
}

.register-footer {
  text-align: center;
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.footer-text {
  color: rgba(255, 255, 255, 0.6);
  margin-right: 0.5rem;
}

.login-link {
  color: #60a5fa;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.3s;
}

.login-link:hover {
  color: #a78bfa;
}

@media (max-width: 768px) {
  .register-card-inner {
    width: 90%;
    padding: 2rem 1.5rem;
  }
  
}
</style>
