<template>
  <div class="detail-container">
    <a-spin :spinning="loading">
      <a-list
        :data-source="dreamLogs"
        :pagination="{ pageSize: 5, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta>
              <template #avatar>
                <div class="avatar-icon" :style="{ background: getEmotionColor(item.emotional_valence) }">
                  <MessageOutlined />
                </div>
              </template>
              <template #title>
                <div class="item-title">
                  <span>{{ item.created_at }}</span>
                  <a-tag v-if="item.is_lucid" color="purple">清醒梦</a-tag>
                </div>
              </template>
              <template #description>
                <div class="item-description">
                  <p class="content">{{ item.content }}</p>
                  <div class="tags">
                    <a-tag v-for="tag in item.tags" :key="tag" size="small">{{ tag }}</a-tag>
                  </div>
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
import { MessageOutlined } from '@ant-design/icons-vue'
import { sleepAPI, type DreamLog } from '@/api/modules/sleep'

const props = defineProps<{
  agentId: string
}>()

const loading = ref(false)
const dreamLogs = ref<DreamLog[]>([])

function getEmotionColor(valence: number) {
  if (valence > 0.6) return '#10b981'
  if (valence > 0.3) return '#f59e0b'
  if (valence > 0) return '#ef4444'
  return '#6b7280'
}

async function loadData() {
  loading.value = true
  try {
    const res = await sleepAPI.getDreamLogs(props.agentId, { limit: 50 })
    dreamLogs.value = res.items
  } catch (error) {
    console.error('加载梦境日志失败:', error)
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
.tags { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
