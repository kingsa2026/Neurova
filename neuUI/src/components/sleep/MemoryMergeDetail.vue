<template>
  <div class="detail-container">
    <a-spin :spinning="loading">
      <a-list
        :data-source="merges"
        :pagination="{ pageSize: 5, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta>
              <template #avatar>
                <div class="avatar-icon">
                  <MergeCellsOutlined />
                </div>
              </template>
              <template #title>
                <div class="item-title">
                  <span>合并 ID: {{ item.id }}</span>
                  <a-tag color="blue">相似度: {{ Math.round(item.similarity_score * 100) }}%</a-tag>
                </div>
              </template>
              <template #description>
                <div class="item-description">
                  <div class="merge-info">
                    <span class="label">合并记忆数：</span>
                    <span class="value">{{ item.merged_memory_ids.length }}</span>
                  </div>
                  <div class="merge-info">
                    <span class="label">结果记忆：</span>
                    <span class="value">{{ item.result_memory_id }}</span>
                  </div>
                  <div class="time">{{ item.merged_at }}</div>
                </div>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MergeCellsOutlined } from '@ant-design/icons-vue'
import { sleepAPI, type MemoryMerge } from '@/api/modules/sleep'

const props = defineProps<{
  agentId: string
}>()

const loading = ref(false)
const merges = ref<MemoryMerge[]>([])

async function loadData() {
  loading.value = true
  try {
    const res = await sleepAPI.getMemoryMerges(props.agentId, { limit: 50 })
    merges.value = res.items
  } catch (error) {
    console.error('加载记忆合并记录失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.detail-container { max-height: 500px; overflow-y: auto; }
.avatar-icon { width: 48px; height: 48px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; background: linear-gradient(135deg, #6366f1, #8b5cf6); }
.item-title { display: flex; align-items: center; gap: 8px; color: #e2e8f0; }
.item-description { padding-top: 8px; }
.merge-info { color: rgba(255, 255, 255, 0.7); margin-bottom: 6px; font-size: 0.9rem; }
.label { font-weight: 500; color: rgba(255, 255, 255, 0.5); }
.value { color: #6366f1; }
.time { color: rgba(255, 255, 255, 0.4); font-size: 0.8rem; margin-top: 8px; }
</style>
