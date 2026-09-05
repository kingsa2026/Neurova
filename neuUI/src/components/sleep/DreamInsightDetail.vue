<template>
  <div class="detail-container">
    <a-spin :spinning="loading">
      <a-list
        :data-source="insights"
        :pagination="{ pageSize: 5, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta>
              <template #avatar>
                <div class="avatar-icon" :style="{ background: getTypeColor(item.type) }">
                  <BulbOutlined />
                </div>
              </template>
              <template #title>
                <div class="item-title">
                  <span>{{ item.title }}</span>
                  <a-tag :color="getTypeColor(item.type)">{{ getTypeLabel(item.type) }}</a-tag>
                </div>
              </template>
              <template #description>
                <div class="item-description">
                  <p class="content">{{ item.content }}</p>
                  <div class="related-dreams" v-if="item.related_dream_ids?.length">
                    <span class="label">相关梦境：</span>
                    <span class="dreams">{{ item.related_dream_ids.join(', ') }}</span>
                  </div>
                  <div class="time">{{ item.created_at }}</div>
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
import { BulbOutlined } from '@ant-design/icons-vue'
import { sleepAPI, type DreamInsight } from '@/api/modules/sleep'

const props = defineProps<{
  agentId: string
}>()

const loading = ref(false)
const insights = ref<DreamInsight[]>([])

function getTypeColor(type: string) {
  const colors: Record<string, string> = {
    pattern: '#6366f1',
    theme: '#8b5cf6',
    suggestion: '#10b981',
    summary: '#f59e0b',
  }
  return colors[type] || '#6b7280'
}

function getTypeLabel(type: string) {
  const labels: Record<string, string> = {
    pattern: '模式发现',
    theme: '主题分析',
    suggestion: '建议',
    summary: '总结',
  }
  return labels[type] || type
}

async function loadData() {
  loading.value = true
  try {
    const res = await sleepAPI.getDreamInsights(props.agentId, { limit: 50 })
    insights.value = res.items
  } catch (error) {
    console.error('加载梦境洞察失败:', error)
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
.content { color: rgba(255, 255, 255, 0.75); margin: 0 0 12px; line-height: 1.6; }
.related-dreams { color: rgba(255, 255, 255, 0.5); font-size: 0.85rem; margin-bottom: 8px; }
.label { font-weight: 500; }
.time { color: rgba(255, 255, 255, 0.4); font-size: 0.8rem; }
</style>
