<script setup lang="ts">
import { ref } from 'vue'
import { searchKnowledge, type KnowledgeHit } from '@/api/misc'

const query = ref('')
const hits = ref<KnowledgeHit[]>([])
const searching = ref(false)
const searched = ref(false)

async function doSearch() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    hits.value = await searchKnowledge(query.value.trim())
    searched.value = true
  } finally {
    searching.value = false
  }
}
</script>

<template>
  <div>
    <h2 class="page-title">知识检索</h2>
    <div class="search-row">
      <input v-model="query" placeholder="搜索知识库…" @keydown.enter="doSearch" />
      <button class="go" :disabled="searching" @click="doSearch">{{ searching ? '…' : '搜索' }}</button>
    </div>
    <div v-if="searched && !hits.length" class="muted">无结果</div>
    <div v-for="(hit, i) in hits" :key="i" class="card">
      <div class="hit-title">{{ hit.title || hit.knowledge_id || '（无标题）' }}</div>
      <div class="muted hit-content">{{ (hit.content || '').slice(0, 200) }}</div>
      <div class="muted score" v-if="hit.score != null">相关度 {{ hit.score }}</div>
    </div>
  </div>
</template>

<style scoped>
.page-title { font-size: 18px; margin: 4px 0 14px; }
.search-row { display: flex; gap: 8px; margin-bottom: 14px; }
.go { background: var(--primary); color: #fff; border-radius: 8px; padding: 0 16px; }
.hit-title { font-weight: 600; margin-bottom: 6px; }
.hit-content { white-space: pre-wrap; }
.score { margin-top: 6px; }
</style>
