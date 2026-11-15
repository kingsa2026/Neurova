<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useServersStore } from '@/stores/servers'
import { checkHealth } from '@/api/misc'

const router = useRouter()
const auth = useAuthStore()
const servers = useServersStore()

const form = reactive({ username: '', password: '' })
const errorMsg = ref('')
const healthTip = ref('')
const submitting = ref(false)
const showServerForm = ref(false)
const serverDraft = reactive({ name: '', baseUrl: '' })

onMounted(async () => {
  await servers.load()
  form.username = servers.active.lastAccount ?? ''
  await probeHealth()
})

async function probeHealth() {
  healthTip.value = '探测服务端…'
  const ok = await checkHealth()
  healthTip.value = ok ? '✓ 服务端可达' : '⚠ 服务端暂不可达（检查地址/网络）'
}

async function submit() {
  errorMsg.value = ''
  if (!form.username || !form.password) {
    errorMsg.value = '请输入账号与密码'
    return
  }
  submitting.value = true
  try {
    await auth.login(form.username, form.password)
    const { registerPushTokenAfterLogin } = await import('@/api/register')
    await registerPushTokenAfterLogin()
    router.replace('/')
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    submitting.value = false
  }
}

async function addServer() {
  if (!serverDraft.baseUrl) return
  await servers.addProfile({
    name: serverDraft.name || serverDraft.baseUrl.replace(/^https?:\/\//, ''),
    baseUrl: serverDraft.baseUrl,
    entryMode: serverDraft.baseUrl.includes('/t/') ? 'relay' : 'direct',
  })
  serverDraft.name = ''
  serverDraft.baseUrl = ''
  showServerForm.value = false
  await probeHealth()
}

async function removeServer(id: string) {
  await servers.removeProfile(id)
  await probeHealth()
}
</script>

<template>
  <div class="login-page">
    <div class="brand">
      <h1>Neurova</h1>
      <p class="muted">移动工作台 · {{ servers.active.name }}</p>
    </div>

    <div class="card">
      <label class="field-label">账号</label>
      <input v-model="form.username" placeholder="用户名" autocomplete="username" />
      <label class="field-label">密码</label>
      <input v-model="form.password" type="password" placeholder="密码" autocomplete="current-password" />
      <p v-if="healthTip" class="muted">{{ healthTip }}</p>
      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
      <button class="btn-primary" :disabled="submitting" @click="submit">
        {{ submitting ? '登录中…' : '登录' }}
      </button>
      <p class="muted tip">租户随账号自动解析；换租户 = 退出后用其他账号登录。</p>
    </div>

    <div class="card">
      <div class="card-head" @click="showServerForm = !showServerForm">
        <span>服务器档案（{{ servers.profiles.length }}）</span>
        <span class="muted">{{ showServerForm ? '收起' : '管理' }}</span>
      </div>
      <template v-if="showServerForm">
        <div v-for="p in servers.profiles" :key="p.id" class="server-row">
          <span :class="{ active: p.id === servers.activeId }">{{ p.name }} · {{ p.baseUrl }}</span>
          <button class="mini-btn" @click="servers.switchTo(p.id).then(probeHealth)">用</button>
          <button class="mini-btn danger" @click="removeServer(p.id)">删</button>
        </div>
        <div class="server-new">
          <input v-model="serverDraft.name" placeholder="名称（如：家里 / VPS）" />
          <input v-model="serverDraft.baseUrl" placeholder="http://192.168.x.x:9527 或 https://中继/t/routeId" />
          <button class="mini-btn" @click="addServer">+ 添加档案</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.login-page { min-height: 100vh; padding: 48px 20px; background: radial-gradient(1200px 600px at 20% -10%, #1a2338 0%, var(--bg) 55%); }
.brand h1 { margin: 0 0 4px; font-size: 28px; letter-spacing: 1px; }
.brand { margin-bottom: 22px; }
.field-label { display: block; font-size: 13px; color: var(--text-dim); margin: 12px 0 6px; }
.tip { margin-top: 10px; }
.card-head { display: flex; justify-content: space-between; font-size: 14px; }
.server-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 13px; }
.server-row span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.server-row .active { color: var(--success); }
.server-new { margin-top: 10px; display: grid; gap: 8px; }
.mini-btn {
  background: var(--bg-elev); color: var(--primary); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.mini-btn.danger { color: var(--error); }
</style>
