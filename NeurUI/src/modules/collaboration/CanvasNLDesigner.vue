<template>
  <div class="nl-designer" :class="{ collapsed }">
    <!-- 收缩态：角落小按钮 -->
    <button v-if="collapsed" class="nl-fab" @click="collapsed = false" :title="t('canvas.aiDesign')">
      💬
    </button>

    <!-- 展开态：对话面板 -->
    <div v-else class="nl-panel">
      <div class="nl-header">
        <span class="nl-title">{{ t('canvas.aiDesign') }}</span>
        <span class="nl-min" @click="collapsed = true">—</span>
      </div>
      <!-- R-8: 指定 agent + 切换模型 -->
      <div class="nl-selects">
        <a-select
          v-model:value="agentId"
          :options="agentOptions"
          size="small"
          style="flex: 1"
          :placeholder="t('canvas.nlSelectAgent')"
          show-search
          option-filter-prop="label"
        />
        <a-select
          v-model:value="modelId"
          :options="modelOptions"
          size="small"
          style="flex: 1"
          :placeholder="t('canvas.nlSelectModel')"
          show-search
          option-filter-prop="label"
          allow-clear
        />
      </div>
      <div ref="listRef" class="nl-messages">
        <div v-for="(m, i) in messages" :key="i" class="nl-msg" :class="'nl-msg--' + m.role">
          <div class="nl-bubble">{{ m.text }}</div>
        </div>
        <div v-if="loading" class="nl-msg nl-msg--agent">
          <div class="nl-bubble nl-bubble--loading">设计流程中…</div>
        </div>
      </div>
      <div class="nl-input">
        <a-input
          v-model:value="input"
          :placeholder="t('canvas.nlDesignerPlaceholder')"
          size="small"
          @keydown.enter="send"
        />
        <a-button type="primary" size="small" :loading="loading" @click="send">
          {{ t('canvas.nlSend') }}
        </a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { canvasFromNl } from '@/api/modules/collaboration'
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'
import { useAgentStore } from '@/stores/agents'
import { useReachableModels, buildModelOptions } from '@/composables/useReachableModels'

const { t } = useI18n()

const props = defineProps<{ agentId?: string }>()
const emit = defineEmits<{
  (e: 'apply', payload: { nodes: CanvasNodeSnapshot[]; edges: CanvasEdgeSnapshot[]; name: string; description: string }): void
}>()

const collapsed = ref(false)
const input = ref('')
const loading = ref(false)
const messages = ref<{ role: 'user' | 'agent'; text: string }[]>([])
const listRef = ref<HTMLElement | null>(null)

// R-8: 可指定已有 agent 与切换模型
const agentStore = useAgentStore()
const agentId = ref(props.agentId || 'default')
const agentOptions = computed(() =>
  agentStore.agentOptions.map((a: any) => ({ label: a.label ?? a.name ?? a.agent_id, value: a.value ?? a.agent_id ?? a.id })),
)
const { models: reachableModels, load: loadReachableModels } = useReachableModels()
const modelId = ref<string>('')
const modelOptions = computed(() => buildModelOptions(reachableModels.value))

onMounted(() => {
  agentStore.loadAgents().catch(() => undefined)
  loadReachableModels().catch(() => undefined)
})

function addMessage(role: 'user' | 'agent', text: string) {
  messages.value.push({ role, text })
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

async function send() {
  const prompt = input.value.trim()
  if (!prompt || loading.value) return
  input.value = ''
  addMessage('user', prompt)
  loading.value = true
  try {
    const res: any = await canvasFromNl(prompt, agentId.value || 'default', modelId.value || undefined)
    const data = res?.data ?? res
    if (data?.status === 'failed' || !data?.nodes?.length) {
      addMessage('agent', (data?.error as string) || t('canvas.designFailed'))
      return
    }
    emit('apply', {
      nodes: data.nodes,
      edges: data.edges,
      name: data.name || '',
      description: data.description || '',
    })
    addMessage(
      'agent',
      t('canvas.generateSuccess', { nodes: data.nodes.length, edges: data.edges.length, name: data.name || t('canvas.workflowNamePrefix') }),
    )
  } catch (err: any) {
    addMessage('agent', t('canvas.generateFailed', { error: err?.message || t('canvas.unknownError') }))
  } finally {
    loading.value = false
  }
}

defineExpose({ collapsed })
</script>

<style scoped>
.nl-designer {
  position: absolute;
  right: 18px;
  bottom: 18px;
  z-index: 30;
}
.nl-fab {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.14));
  background: var(--nr-bg-elevated);
  color: var(--nr-text-primary, #e8e9f0);
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}
.nl-panel {
  width: 320px;
  max-height: 420px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.14));
  border-radius: 12px;
  background: var(--nr-bg-elevated);
  overflow: hidden;
}
.nl-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
  font-size: 13px;
  font-weight: 600;
}
.nl-selects {
  display: flex;
  gap: 6px;
  padding: 8px 10px 4px;
}
.nl-min {
  cursor: pointer;
  opacity: 0.7;
}
.nl-messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  max-height: 300px;
  min-height: 120px;
}
.nl-msg {
  display: flex;
  margin-bottom: 8px;
}
.nl-msg--user {
  justify-content: flex-end;
}
.nl-msg--agent {
  justify-content: flex-start;
}
.nl-bubble {
  max-width: 82%;
  padding: 6px 10px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.nl-msg--user .nl-bubble {
  background: #6366f1;
  color: #fff;
}
.nl-msg--agent .nl-bubble {
  background: var(--nr-glass-bg);
  color: var(--nr-text-primary, #e8e9f0);
}
.nl-bubble--loading {
  opacity: 0.7;
}
.nl-input {
  display: flex;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
}
</style>
