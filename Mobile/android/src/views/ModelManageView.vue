<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listModels, type ModelInfo } from '@/api/manage'

const models = ref<ModelInfo[]>([])
const loading = ref(true)
const error = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    models.value = await listModels()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div class="head-row">
      <h2 class="page-title">模型管理</h2>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!models.length" class="muted">暂无模型</p>
    <div v-for="m in models" :key="m.id" class="card">
      <div class="item-title">{{ m.name || m.id }}</div>
      <div class="muted">{{ m.provider }}{{ m.enabled === false ? ' · 未启用' : '' }}{{ m.is_default ? ' · 默认' : '' }}</div>
    </div>
  </div>
</template>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: center; }
.page-title { font-size: 18px; margin: 4px 0 14px; }
.item-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.ghost {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-dim);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
</style>
