<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useServersStore } from '@/stores/servers'
import { usePairingStore } from '@/stores/pairing'
import { APP_VERSION } from '@/config'

const router = useRouter()
const auth = useAuthStore()
const servers = useServersStore()
const pairing = usePairingStore()

const rows = computed(() => [
  { label: '账号', value: auth.user?.username ?? '-' },
  { label: '角色', value: auth.user?.role ?? '-' },
  { label: '所属租户（部门根）', value: auth.tenantLabel || 'default' },
  { label: '当前服务器', value: `${servers.active.name} · ${servers.active.entryMode === 'relay' ? '中继' : '直连'}` },
  { label: '版本', value: APP_VERSION },
])

async function doLogout() {
  const { unregisterPushTokenOnLogout } = await import('@/api/register')
  await unregisterPushTokenOnLogout()
  await auth.logout()
  router.replace('/login')
}
</script>

<template>
  <div>
    <h2 class="page-title">我的</h2>
    <div class="card">
      <div v-for="r in rows" :key="r.label" class="row">
        <span class="muted">{{ r.label }}</span>
        <span class="val">{{ r.value }}</span>
      </div>
    </div>

    <div class="card link-row" @click="router.push('/servers')">
      <span>服务器档案管理</span>
      <span class="muted">{{ servers.profiles.length }} 台 ›</span>
    </div>

    <div class="card link-row" @click="router.push('/pairing')">
      <span>设备配对（WS 备用通道）</span>
      <span class="muted">{{ pairing.paired ? '已配对 ›' : '未配对 ›' }}</span>
    </div>

    <button class="logout" @click="doLogout">退出登录（切换账号/租户）</button>
    <p class="muted tip">租户随账号绑定：退出后用目标租户下的账号重新登录即完成切换。</p>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 14px; }
.row { display: flex; justify-content: space-between; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 14px; }
.row:last-child { border-bottom: none; }
.val { text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.link-row { display: flex; justify-content: space-between; font-size: 14px; }
.logout {
  width: 100%; background: var(--bg-card); color: var(--error);
  border: 1px solid var(--border); border-radius: 10px; padding: 12px; font-size: 14px;
}
.tip { margin-top: 10px; }
</style>
