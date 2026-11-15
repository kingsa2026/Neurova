<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listSkills, type SkillInfo } from '@/api/manage'

const skills = ref<SkillInfo[]>([])
const loading = ref(true)
const error = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    skills.value = await listSkills()
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
      <h2 class="page-title">技能</h2>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!skills.length" class="muted">暂无技能</p>
    <div v-for="(s, i) in skills" :key="s.skill_id ?? s.id ?? i" class="card">
      <div class="item-title">{{ s.name || s.skill_id || s.id }}</div>
      <div class="muted">{{ s.description || '' }}</div>
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
