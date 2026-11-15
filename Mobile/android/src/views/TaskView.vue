<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listTaskBoards, type TaskBoard } from '@/api/misc'

const boards = ref<TaskBoard[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    boards.value = await listTaskBoards()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <h2 class="page-title">任务看板</h2>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!boards.length" class="muted">暂无看板</p>
    <div v-for="b in boards" :key="b.id ?? b.name" class="card">
      <div class="board-name">{{ b.name || b.id }}</div>
      <div class="muted">{{ (b.tasks ?? []).length }} 个任务</div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 14px; }
.board-name { font-weight: 600; margin-bottom: 4px; }
</style>
