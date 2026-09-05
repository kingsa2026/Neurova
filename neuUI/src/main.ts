import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import 'ant-design-vue/dist/reset.css'
import '@/styles/variables.css'
import '@/styles/global.css'

// 过滤浏览器扩展产生的噪音报错（如 Vue DevTools / Chrome 扩展连接失败）
function isExtensionNoise(err: unknown): boolean {
  const e = err as { message?: string; reason?: { message?: string } } | undefined
  const msg = String(e?.message || e?.reason?.message || err || '')
  return msg.includes('receiving end does not exist')
    || msg.includes('Could not establish connection')
    || msg.includes('Extension context invalidated')
}

// 1. Promise 未捕获异常
window.addEventListener('unhandledrejection', (event) => {
  if (isExtensionNoise(event.reason)) { event.preventDefault() }
})

const app = createApp(App)

// 2. Vue 组件渲染 / 生命周期异常
app.config.errorHandler = (err, _instance, _info) => {
  if (isExtensionNoise(err)) return
  console.error('[Vue Error]', err)
}
app.use(createPinia())
app.use(router)
app.mount('#app')
