<script setup lang="ts">
/**
 * MockEditor.vue — 节点 Mock 输出编辑器
 *
 * 输入 JSON 文本 → parse 后回传给父组件。
 * 解析失败时显示错误，不丢失输入。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  nodeId: string
  modelValue: unknown  // 当前 mock_output（null/未设 = 无 mock）
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: unknown): void
  (e: 'clear'): void
}>()

const { t } = useI18n()

const text = ref<string>('')
const error = ref<string>('')

watch(
  () => props.modelValue,
  (v) => {
    if (v === null || v === undefined) {
      text.value = ''
    } else if (typeof v === 'string') {
      text.value = v
    } else {
      text.value = JSON.stringify(v, null, 2)
    }
    error.value = ''
  },
  { immediate: true }
)

function handleChange(value: string) {
  text.value = value
  if (!value.trim()) {
    error.value = ''
    emit('update:modelValue', null)
    return
  }
  try {
    const parsed = JSON.parse(value)
    error.value = ''
    emit('update:modelValue', parsed)
  } catch (e) {
    error.value = (e as Error).message
  }
}

function handleClear() {
  text.value = ''
  error.value = ''
  emit('clear')
}
</script>

<template>
  <div class="mock-editor" data-testid="mock-editor">
    <div class="mock-editor-header">
      <span class="mock-editor-title">{{ t('debug.mockTitle', { nodeId }) }}</span>
    </div>
    <a-textarea
      :value="text"
      :placeholder="t('debug.mockPlaceholder')"
      :auto-size="{ minRows: 4, maxRows: 12 }"
      data-testid="mock-input"
      @update:value="handleChange"
    />
    <div v-if="error" class="mock-editor-error" data-testid="mock-error">{{ error }}</div>
    <div v-else-if="text.trim()" class="mock-editor-ok" data-testid="mock-ok">
      {{ t('debug.mockValid') }}
    </div>
    <a-button
      v-if="text"
      size="small"
      type="text"
      danger
      class="mock-editor-clear"
      data-testid="mock-clear"
      @click="handleClear"
    >
      {{ t('debug.clearMock') }}
    </a-button>
  </div>
</template>

<style scoped>
.mock-editor {
  padding: 8px 0;
}
.mock-editor-header {
  margin-bottom: 6px;
}
.mock-editor-title {
  font-size: 12px;
  font-weight: 600;
}
.mock-editor-error {
  color: var(--nr-error, #ef4444);
  font-size: 11px;
  margin-top: 4px;
}
.mock-editor-ok {
  color: var(--nr-success, #10b981);
  font-size: 11px;
  margin-top: 4px;
}
.mock-editor-clear {
  margin-top: 6px;
}
</style>