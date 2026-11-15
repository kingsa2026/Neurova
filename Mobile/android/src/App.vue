<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useServersStore } from '@/stores/servers'
import { useAgentsStore } from '@/stores/agents'
import { unreadNotificationCount } from '@/api/misc'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const servers = useServersStore()
const agents = useAgentsStore()

const showChrome = computed(() => route.name !== 'login')
const unreadCount = ref(0)
const showAgentMenu = ref(false)

const tabs = [
  { name: 'chat', label: '对话', icon: '💬' },
  { name: 'knowledge', label: '知识', icon: '📚' },
  { path: '/tasks', name: 'tasks', label: '任务', icon: '✅' },
  { path: '/files', name: 'files', label: '文件', icon: '📁' },
  { name: 'profile', label: '我的', icon: '👤' },
] as Array<{ path?: string; name: string; label: string; icon: string }>

function go(t: { path?: string; name: string }) {
  router.push(t.path ?? `/${t.name}`)
}

onMounted(async () => {
  if (auth.isLoggedIn) {
    await agents.load()
    try { unreadCount.value = await unreadNotificationCount() } catch { /* 角标失败不阻塞 */ }
  }
})

async function pickAgent(id: string) {
  showAgentMenu.value = false
  await agents.switchTo(id)
}
</script>

<template>
  <div class="app-shell">
    <header v-if="showChrome" class="top-bar">
      <div class="top-left">
        <div class="agent-chip" @click="showAgentMenu = !showAgentMenu">
          Agent · {{ agents.currentName }} ▾
        </div>
        <div class="tenant-chip" v-if="auth.tenantLabel">租户 · {{ auth.tenantLabel }}</div>
      </div>
      <div class="top-right">
        <span class="server-chip" :title="servers.active.baseUrl">{{ servers.active.name }}</span>
        <span class="bell" @click="router.push('/notifications')">🔔<span v-if="unreadCount > 0" class="badge">{{ unreadCount > 9 ? '9+' : unreadCount }}</span></span>
      </div>
      <div v-if="showAgentMenu" class="agent-menu">
        <div
          v-for="a in agents.agents"
          :key="a.agent_id"
          class="agent-option"
          :class="{ active: a.agent_id === agents.currentId }"
          @click="pickAgent(a.agent_id)"
        >
          {{ a.name || a.agent_id }}
        </div>
        <div v-if="!agents.agents.length" class="muted agent-option">暂无 Agent</div>
      </div>
    </header>

    <main class="page" :class="{ 'no-chrome': !showChrome }">
      <router-view />
    </main>

    <nav v-if="showChrome" class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.name"
        class="tab-item"
        :class="{ active: route.name === t.name }"
        @click="go(t)"
      >
        <span class="tab-icon">{{ t.icon }}</span>
        <span class="tab-label">{{ t.label }}</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: flex; flex-direction: column; }
.top-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; background: var(--bg-elev); border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 10;
}
.top-left { display: flex; gap: 8px; align-items: center; overflow: hidden; position: relative; }
.agent-chip, .tenant-chip, .server-chip {
  font-size: 12px; color: var(--text-dim);
  background: var(--bg-card); border: 1px solid var(--border);
  padding: 4px 8px; border-radius: 999px; white-space: nowrap;
}
.agent-chip { color: var(--text); cursor: pointer; }
.server-chip { color: var(--primary); }
.bell { position: relative; cursor: pointer; font-size: 16px; margin-left: 8px; }
.badge {
  position: absolute; top: -6px; right: -8px; background: var(--error); color: #fff;
  font-size: 10px; border-radius: 999px; padding: 1px 4px; min-width: 14px; text-align: center;
}
.agent-menu {
  position: absolute; top: 40px; left: 14px; min-width: 200px; z-index: 30;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4); overflow: hidden;
}
.agent-option { padding: 9px 12px; font-size: 13px; cursor: pointer; }
.agent-option:hover { background: var(--bg-elev); }
.agent-option.active { color: var(--primary); }
.page { flex: 1; padding: 14px 14px 80px; }
.page.no-chrome { padding: 0; }
.tab-bar {
  position: fixed; bottom: 0; left: 0; right: 0;
  display: flex; background: var(--bg-elev); border-top: 1px solid var(--border);
  padding: 6px 0 calc(6px + env(safe-area-inset-bottom));
}
.tab-item {
  flex: 1; background: none; color: var(--text-dim);
  display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 4px 0;
}
.tab-item.active { color: var(--primary); }
.tab-icon { font-size: 20px; }
.tab-label { font-size: 11px; }
</style>
