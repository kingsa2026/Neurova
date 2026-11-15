<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { searchMemories, memoryStats, type MemoryItem, type MemoryStats } from '@/api/manage'

const keyword = ref('')
const items = ref<MemoryItem[]>([])
const stats = ref<MemoryStats | null>(null)
const loading = ref(false)
const searched = ref(false)

onMounted(async () => {
  stats.value = await memoryStats().catch(() => null)
  await doSearch()
})

async function doSearch() {
  loading.value = true
  try {
    items.value = await searchMemories(keyword.value.trim())
    searched.value = true
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div class="head-row">
      <h2 class="page-title">记忆管理</h2>
      <span v-if="stats" class="muted">共 {{ stats.total ?? 0 }} 条</span>
    </div>
    <div class="search-row">
      <input v-model="keyword" placeholder="按关键词搜索记忆…" @keydown.enter="doSearch" />
      <button class="go" :disabled="loading" @click="doSearch">{{ loading ? '…' : '搜索' }}</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="searched && !items.length" class="muted">无匹配记忆</p>
    <div v-for="(m, i) in items" :key="i" class="card">
      <div class="mem-content">{{ m.content || m.keyword || '（空）' }}</div>
      <div class="muted">{{ m.created_at ?? '' }}</div>
    </div>
  </div>
</template>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: center; }
.page-title { font-size: 18px; margin: 4px 0 14px; }
.search-row { display: flex; gap: 8px; margin-bottom: 14px; }
.go { background: var(--primary); color: #fff; border-radius: 8px; padding: 0 16px; }
.mem-content { font-size: 13px; white-space: pre-wrap; margin-bottom: 6px; }
</style>
