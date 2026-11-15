<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useServersStore } from '@/stores/servers'
import { checkHealth } from '@/api/misc'

const router = useRouter()
const servers = useServersStore()
const draft = reactive({ name: '', baseUrl: '' })
const showForm = ref(false)
const health = ref<Record<string, string>>({})

onMounted(() => servers.load())

async function probe(id?: string) {
  if (id) await servers.switchTo(id)
  health.value[id ?? servers.activeId] = (await checkHealth()) ? '✓ 可达' : '✗ 不可达'
}

async function add() {
  if (!draft.baseUrl) return
  await servers.addProfile({
    name: draft.name || draft.baseUrl.replace(/^https?:\/\//, ''),
    baseUrl: draft.baseUrl,
    entryMode: draft.baseUrl.includes('/t/') ? 'relay' : 'direct',
  })
  draft.name = ''
  draft.baseUrl = ''
  showForm.value = false
}

async function remove(id: string) {
  await servers.removeProfile(id)
  router.replace('/profile')
}

async function use(id: string) {
  await servers.switchTo(id)
  router.replace('/login')
}
</script>

<template>
  <div>
    <h2 class="page-title">服务器档案</h2>
    <p class="muted">每台服务器的地址独立保存；切换档案后需用该服务器的账号重新登录。</p>
    <div v-for="p in servers.profiles" :key="p.id" class="card">
      <div class="row-top">
        <div>
          <div class="p-name" :class="{ active: p.id === servers.activeId }">{{ p.name }}</div>
          <div class="muted p-url">{{ p.baseUrl }}</div>
          <div class="muted">
            {{ p.entryMode === 'relay' ? '经中继' : '直连' }}
            {{ p.lastAccount ? ` · 最近账号 ${p.lastAccount}` : '' }}
            {{ health[p.id] ? ` · ${health[p.id]}` : '' }}
          </div>
        </div>
        <div class="ops">
          <button class="mini" @click="probe(p.id)">探测</button>
          <button class="mini" @click="use(p.id)">使用</button>
          <button class="mini danger" @click="remove(p.id)">删除</button>
        </div>
      </div>
    </div>
    <button class="mini wide" @click="showForm = !showForm">{{ showForm ? '收起' : '+ 新增服务器档案' }}</button>
    <div v-if="showForm" class="card new-form">
      <input v-model="draft.name" placeholder="名称（如：家里 / 公司 / VPS）" />
      <input v-model="draft.baseUrl" placeholder="http://192.168.x.x:9527 或 https://中继域名/t/routeId" />
      <button class="mini" @click="add">保存档案</button>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 10px; }
.row-top { display: flex; justify-content: space-between; gap: 10px; }
.p-name { font-weight: 600; margin-bottom: 2px; }
.p-name.active { color: var(--success); }
.p-url { word-break: break-all; }
.ops { display: flex; flex-direction: column; gap: 6px; }
.mini {
  background: var(--bg-elev); color: var(--primary); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.mini.danger { color: var(--error); }
.mini.wide { width: 100%; padding: 10px; }
.new-form { display: grid; gap: 8px; }
</style>
