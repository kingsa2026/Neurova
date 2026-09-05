<template>
  <div class="detail-container">
    <a-spin :spinning="loading">
      <a-list
        :data-source="conflicts"
        :pagination="{ pageSize: 5, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta>
              <template #avatar>
                <div class="avatar-icon" :style="{ background: getMethodColor(item.resolution_method) }">
                  <SafetyCertificateOutlined />
                </div>
              </template>
              <template #title>
                <div class="item-title">
                  <span>冲突 ID: {{ item.id }}</span>
                  <a-tag :color="getMethodColor(item.resolution_method)">{{ getMethodLabel(item.resolution_method) }}</a-tag>
                </div>
              </template>
              <template #description>
                <div class="item-description">
                  <div class="conflict-info">
                    <span class="label">冲突记忆数：</span>
                    <span class="value">{{ item.conflicting_memory_ids.length }}</span>
                  </div>
                  <div class="conflict-info">
                    <span class="label">胜出记忆：</span>
                    <span class="value">{{ item.winning_memory_id }}</span>
                  </div>
                  <div class="time">{{ item.resolved_at }}</div>
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
import { SafetyCertificateOutlined } from '@ant-design/icons-vue'
import { sleepAPI, type ConflictResolution } from '@/api/modules/sleep'

const props = defineProps<{
  agentId: string
}>()

const loading = ref(false)
const conflicts = ref<ConflictResolution[]>([])

function getMethodColor(method: string) {
  const colors: Record<string, string> = {
    latest: '#6366f1',
    count: '#8b5cf6',
    consensus: '#10b981',
    importance: '#f59e0b',
  }
  return colors[method] || '#6b7280'
}

function getMethodLabel(method: string) {
  const labels: Record<string, string> = {
    latest: '最新为准',
    count: '数量为准',
    consensus: '共识机制',
    importance: '重要性优先',
  }
  return labels[method] || method
}

async function loadData() {
  loading.value = true
  try {
    const res = await sleepAPI.getConflictResolutions(props.agentId, { limit: 50 })
    conflicts.value = res.items
  } catch (error) {
    console.error('加载冲突解决记录失败:', error)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.detail-container { max-height: 500px; overflow-y: auto; }
.avatar-icon { width: 48px; height: 48px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; }
.item-title { display: flex; align-items: center; gap: 8px; color: #e2e8f0; }
.item-description { padding-top: 8px; }
.conflict-info { color: rgba(255, 255, 255, 0.7); margin-bottom: 6px; font-size: 0.9rem; }
.label { font-weight: 500; color: rgba(255, 255, 255, 0.5); }
.value { color: #10b981; }
.time { color: rgba(255, 255, 255, 0.4); font-size: 0.8rem; margin-top: 8px; }
</style>
