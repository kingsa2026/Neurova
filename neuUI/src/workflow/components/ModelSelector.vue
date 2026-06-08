<template>
  <div class="model-selector">
    <a-select
      v-model:value="selectedModel"
      :placeholder="placeholder"
      :loading="loading"
      :options="modelOptions"
      show-search
      :filter-option="filterOption"
      @change="handleChange"
    >
      <template #option="{ label, value, provider, description }">
        <div class="model-option">
          <div class="model-header">
            <span class="model-name">{{ label }}</span>
            <a-tag v-if="provider" size="small" color="blue">{{ provider }}</a-tag>
          </div>
          <div v-if="description" class="model-description">{{ description }}</div>
        </div>
      </template>
    </a-select>
    
    <a-button
      v-if="showRefresh"
      type="text"
      size="small"
      :loading="refreshing"
      @click="refreshModels"
    >
      <template #icon><ReloadOutlined /></template>
    </a-button>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ReloadOutlined } from '@ant-design/icons-vue'

interface ModelOption {
  label: string
  value: string
  provider?: string
  description?: string
  capabilities?: string[]
}

interface Props {
  modelValue?: string
  providerCapability?: string
  placeholder?: string
  showRefresh?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: '选择模型',
  showRefresh: true,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'change': [value: string, model: ModelOption | undefined]
}>()

const loading = ref(false)
const refreshing = ref(false)
const models = ref<ModelOption[]>([])

const selectedModel = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const modelOptions = computed(() => {
  if (!props.providerCapability) {
    return models.value
  }
  
  // 按能力过滤
  return models.value.filter(model => {
    if (!model.capabilities) return true
    return model.capabilities.includes(props.providerCapability!)
  })
})

function filterOption(input: string, option: ModelOption) {
  const search = input.toLowerCase()
  return (
    option.label.toLowerCase().includes(search) ||
    option.value.toLowerCase().includes(search) ||
    option.provider?.toLowerCase().includes(search) ||
    option.description?.toLowerCase().includes(search)
  )
}

function handleChange(value: string) {
  const model = models.value.find(m => m.value === value)
  emit('change', value, model)
}

async function fetchModels() {
  loading.value = true
  
  try {
    // 从后端获取可用模型
    const response = await fetch('/api/v1/providers/models')
    const data = await response.json()
    
    models.value = data.models.map((model: any) => ({
      label: model.name || model.model,
      value: model.model,
      provider: model.provider,
      description: model.description,
      capabilities: model.capabilities,
    }))
  } catch (error) {
    console.error('Failed to fetch models:', error)
    // 使用默认模型列表
    models.value = [
      { label: 'GPT-4o', value: 'gpt-4o', provider: 'OpenAI', capabilities: ['text', 'vision', 'tool_use'] },
      { label: 'GPT-4o Mini', value: 'gpt-4o-mini', provider: 'OpenAI', capabilities: ['text', 'tool_use'] },
      { label: 'Claude 3.5 Sonnet', value: 'claude-3-5-sonnet', provider: 'Anthropic', capabilities: ['text', 'vision', 'tool_use'] },
      { label: 'Claude 3 Haiku', value: 'claude-3-haiku', provider: 'Anthropic', capabilities: ['text', 'tool_use'] },
      { label: 'DeepSeek V3', value: 'deepseek-v3', provider: 'DeepSeek', capabilities: ['text', 'tool_use'] },
      { label: 'Qwen2.5 72B', value: 'qwen2.5-72b-instruct', provider: 'Alibaba', capabilities: ['text', 'tool_use'] },
      { label: 'GLM-4', value: 'glm-4', provider: 'Zhipu', capabilities: ['text', 'tool_use'] },
    ]
  } finally {
    loading.value = false
  }
}

async function refreshModels() {
  refreshing.value = true
  
  try {
    await fetch('/api/v1/providers/refresh', { method: 'POST' })
    await fetchModels()
  } catch (error) {
    console.error('Failed to refresh models:', error)
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  fetchModels()
})

// 监听 providerCapability 变化
watch(() => props.providerCapability, () => {
  // 如果当前选择的模型不在过滤后的列表中，清空选择
  if (selectedModel.value && props.providerCapability) {
    const exists = modelOptions.value.some(m => m.value === selectedModel.value)
    if (!exists) {
      selectedModel.value = undefined
    }
  }
})
</script>

<style scoped>
.model-selector {
  display: flex;
  gap: 8px;
  align-items: center;
}

.model-selector .ant-select {
  flex: 1;
}

.model-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.model-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.model-name {
  font-weight: 500;
}

.model-description {
  font-size: 12px;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>