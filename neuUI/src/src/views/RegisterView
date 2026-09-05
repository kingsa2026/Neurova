&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 星空背景 --&gt;
    &lt;StarBackground /&gt;
    &lt;!-- 注册表单 --&gt;
    &lt;div &gt;
      &lt;!-- Logo 和标题 --&gt;
      &lt;div &gt;
        &lt;img :src="logoWhite" alt="Neurova"  /&gt;
      &lt;/div&gt;
      &lt;!-- 注册表单 --&gt;
      &lt;a-form
        :model="formState"
        @finish="handleRegister"
        layout="vertical"
      &gt;
        &lt;!-- 用户名 --&gt;
        &lt;a-form-item
          name="username"
          :rules="[
            { required: true, message: '请输入用户名' },
            { min: 3, max: 20, message: '用户名长度为3-20个字符' }
          ]"
        &gt;
          &lt;a-input
            v-model:value="formState.username"
            placeholder="用户名"
            size="large"
          &gt;
            &lt;template #prefix&gt;
              &lt;UserOutlined style="color: rgba(255, 255, 255, 0.4)" /&gt;
            &lt;/template&gt;
          &lt;/a-input&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 邮箱 --&gt;
        &lt;a-form-item
          name="email"
          :rules="[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '请输入有效的邮箱地址' }
          ]"
        &gt;
          &lt;a-input
            v-model:value="formState.email"
            placeholder="邮箱"
            size="large"
          &gt;
            &lt;template #prefix&gt;
              &lt;MailOutlined style="color: rgba(255, 255, 255, 0.4)" /&gt;
            &lt;/template&gt;
          &lt;/a-input&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 密码 --&gt;
        &lt;a-form-item
          name="password"
          :rules="[
            { required: true, message: '请输入密码' },
            { min: 8, message: '密码长度至少为8个字符' }
          ]"
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
        &lt;!-- 确认密码 --&gt;
        &lt;a-form-item
          name="confirmPassword"
          :rules="[
            { required: true, message: '请确认密码' },
            { validator: validateConfirmPassword }
          ]"
        &gt;
          &lt;a-input-password
            v-model:value="formState.confirmPassword"
            placeholder="确认密码"
            size="large"
          &gt;
            &lt;template #prefix&gt;
              &lt;LockOutlined style="color: rgba(255, 255, 255, 0.4)" /&gt;
            &lt;/template&gt;
          &lt;/a-input-password&gt;
        &lt;/a-form-item&gt;
        &lt;!-- 注册按钮 --&gt;
        &lt;a-form-item&gt;
          &lt;a-button
            type="primary"
            html-type="submit"
            size="large"
            :loading="loading"
          &gt;
            注册
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
      &lt;!-- 登录链接 --&gt;
      &lt;div &gt;
        &lt;span &gt;已有账号？&lt;/span&gt;
        &lt;router-link to="/login" &gt;
          立即登录
        &lt;/router-link&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons-vue'
import { useAuthStore } from '@/stores/auth'
import StarBackground from '@/components/StarBackground.vue'
import logoWhite from '@/assets/img/NEUROVA-white.png'
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const error = ref&lt;string | null&gt;(null)
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
    const e = err as { message?: string }
    error.value = e.message || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}
&lt;/script&gt;
&lt;style scoped&gt;
.register-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.register-card {
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
.register-header {
  text-align: center;
  margin-bottom: 2.5rem;
}
.register-logo {
  max-height: 80px;
  max-width: 320px;
  object-fit: contain;
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
  .register-card {
    width: 90%;
    padding: 2rem 1.5rem;
  }
}
&lt;/style&gt;
&nbsp;