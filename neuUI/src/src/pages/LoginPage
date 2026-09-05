&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 星空背景 --&gt;
    &lt;StarBackground /&gt;
    &lt;!-- 登录表单 --&gt;
    &lt;div &gt;
      &lt;!-- Logo 和标题 --&gt;
      &lt;div &gt;
        &lt;img :src="logoWhite" alt="Neurova"  /&gt;
      &lt;/div&gt;
      &lt;!-- 登录表单 --&gt;
      &lt;a-form
        :model="formState"
        @finish="handleLogin"
        layout="vertical"
      &gt;
        &lt;!-- 用户名/邮箱 --&gt;
        &lt;a-form-item
          name="username"
          :rules="[{ required: true, message: '请输入用户名或邮箱' }]"
        &gt;
          &lt;a-input
            v-model:value="formState.username"
            placeholder="用户名 / 邮箱"
            size="large"
          &gt;
            &lt;template #prefix&gt;
              &lt;UserOutlined style="color: rgba(255, 255, 255, 0.4)" /&gt;
            &lt;/template&gt;
          &lt;/a-input&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 密码 --&gt;
        &lt;a-form-item
          name="password"
          :rules="[{ required: true, message: '请输入密码' }]"
        &gt;
          &lt;a-input-password
            v-model:value="formState.password"
            placeholder="密码"
            size="large"
          &gt;
            &lt;template #prefix&gt;
              &lt;LockOutlined style="color: rgba(255, 255, 255, 0.4)" /&gt;
            &lt;/template&gt;
          &lt;/a-input-password&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 记住我和忘记密码 --&gt;
        &lt;div &gt;
          &lt;a-checkbox v-model:checked="formState.remember" &gt;
            记住我
          &lt;/a-checkbox&gt;
          &lt;a &gt;忘记密码？&lt;/a&gt;
        &lt;/div&gt;
        &lt;!-- 登录按钮 --&gt;
        &lt;a-form-item&gt;
          &lt;a-button
            type="primary"
            html-type="submit"
            size="large"
            :loading="loading"
          &gt;
            登录
          &lt;/a-button&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 错误提示 --&gt;
        &lt;a-alert
          v-if="error"
          :message="error"
          type="error"
          show-icon
        /&gt;
      &lt;/a-form&gt;
      &lt;!-- 注册链接 --&gt;
      &lt;div &gt;
        &lt;span &gt;还没有账号？&lt;/span&gt;
        &lt;router-link to="/register" &gt;
          立即注册
        &lt;/router-link&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'
import StarBackground from '@/components/StarBackground.vue'
import logoWhite from '@/assets/img/NEUROVA-white.png'
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const error = ref&lt;string | null&gt;(null)
const formState = reactive({
  username: '',
  password: '',
  remember: false
})
async function handleLogin() {
  loading.value = true
  error.value = null
  try {
    const result = await authStore.login({
      username: formState.username,
      password: formState.password,
      remember: formState.remember
    })
    if (result.success) {
      message.success('登录成功')
      router.push('/dashboard')
    } else {
      error.value = result.message || '登录失败'
    }
  } catch (err: unknown) {
    const e = err as {message?:string}
    error.value = e.message || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}
&lt;/script&gt;
&lt;style scoped&gt;
.login-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.login-card {
  position: relative;
  z-index: 10;
  width: 420px;
  padding: 3rem 2.5rem;
  animation: fadeInUp 0.6s ease-out;
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
.login-header {
  text-align: center;
  margin-bottom: 2.5rem;
}
.login-logo {
  max-height: 80px;
  max-width: 320px;
  object-fit: contain;
}
.login-form {
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
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}
:deep(.remember-me) {
  color: rgba(255, 255, 255, 0.8) !important;
}
:deep(.remember-me .ant-checkbox-inner) {
  background: rgba(255, 255, 255, 0.05) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
}
:deep(.remember-me .ant-checkbox-checked .ant-checkbox-inner) {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
  border-color: transparent !important;
}
.forgot-password {
  color: #60a5fa;
  font-size: 0.9rem;
  text-decoration: none;
  transition: color 0.3s;
}
.forgot-password:hover {
  color: #a78bfa;
}
.login-button {
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
.login-footer {
  text-align: center;
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
.footer-text {
  color: rgba(255, 255, 255, 0.6);
  margin-right: 0.5rem;
}
.register-link {
  color: #60a5fa;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.3s;
}
.register-link:hover {
  color: #a78bfa;
}
@media (max-width: 768px) {
  .login-card {
    width: 90%;
    padding: 2rem 1.5rem;
  }
  .login-header h1 {
    font-size: 2.5rem;
  }
}
&lt;/style&gt;
&nbsp;