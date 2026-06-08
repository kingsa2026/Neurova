<template>
  <div class="sub-block-renderer">
    <template v-for="block in visibleBlocks" :key="block.id">
      <a-form-item
        :label="block.title"
        :required="block.required"
        :help="block.description"
        :validate-status="getValidationStatus(block)"
        class="sub-block-item"
      >
        <!-- 输入框 -->
        <a-input
          v-if="block.type === 'input'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />

        <!-- 数字输入框 -->
        <a-input-number
          v-else-if="block.type === 'number'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :min="block.min"
          :max="block.max"
          :step="block.step || 1"
          :disabled="block.disabled"
          style="width: 100%"
          @change="handleChange(block.id, $event)"
        />

        <!-- 文本域 -->
        <a-textarea
          v-else-if="block.type === 'textarea'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          :rows="4"
          @change="handleChange(block.id, $event)"
        />

        <!-- 下拉选择 -->
        <a-select
          v-else-if="block.type === 'select'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          :options="block.options"
          @change="handleChange(block.id, $event)"
        />

        <!-- 滑块 -->
        <a-slider
          v-else-if="block.type === 'slider'"
          v-model:value="values[block.id]"
          :min="block.min || 0"
          :max="block.max || 100"
          :step="block.step || 1"
          :disabled="block.disabled"
          :marks="getSliderMarks(block)"
          @change="handleChange(block.id, $event)"
        />

        <!-- 开关 -->
        <a-switch
          v-else-if="block.type === 'switch'"
          v-model:checked="values[block.id]"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />

        <!-- 代码编辑器 -->
        <div v-else-if="block.type === 'code'" class="code-editor-wrapper">
          <a-select
            v-if="block.language"
            v-model:value="currentLanguage"
            :options="languageOptions"
            size="small"
            class="language-selector"
          />
          <div ref="codeEditorRef" class="code-editor" />
        </div>

        <!-- JSON 编辑器 -->
        <div v-else-if="block.type === 'json'" class="json-editor-wrapper">
          <a-textarea
            v-model:value="jsonText"
            :placeholder="block.placeholder || '输入 JSON 数据'"
            :disabled="block.disabled"
            :rows="6"
            @change="handleJsonChange(block.id, $event)"
          />
          <div v-if="jsonError" class="json-error">{{ jsonError }}</div>
        </div>

        <!-- 模型选择器 -->
        <model-selector
          v-else-if="block.type === 'model-selector'"
          v-model:value="values[block.id]"
          :capability="block.providerCapability"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />

        <!-- 文件上传 -->
        <a-upload
          v-else-if="block.type === 'file'"
          v-model:file-list="fileList"
          :accept="block.fileTypes?.join(',')"
          :disabled="block.disabled"
          :before-upload="handleBeforeUpload"
          @change="handleFileChange(block.id, $event)"
        >
          <a-button>
            <upload-outlined />
            选择文件
          </a-button>
        </a-upload>

        <!-- 颜色选择器 -->
        <input
          v-else-if="block.type === 'color'"
          type="color"
          :value="values[block.id]"
          :disabled="block.disabled"
          class="color-picker"
          @input="handleChange(block.id, $event.target.value)"
        />

        <!-- 日期选择器 -->
        <a-date-picker
          v-else-if="block.type === 'date'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          style="width: 100%"
          @change="handleChange(block.id, $event)"
        />

        <!-- 时间选择器 -->
        <a-time-picker
          v-else-if="block.type === 'time'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          style="width: 100%"
          @change="handleChange(block.id, $event)"
        />

        <!-- 日期时间选择器 -->
        <a-date-picker
          v-else-if="block.type === 'datetime'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          show-time
          style="width: 100%"
          @change="handleChange(block.id, $event)"
        />

        <!-- 范围选择器 -->
        <a-slider
          v-else-if="block.type === 'range'"
          v-model:value="values[block.id]"
          range
          :min="block.min || 0"
          :max="block.max || 100"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />

        <!-- 复选框 -->
        <a-checkbox
          v-else-if="block.type === 'checkbox'"
          v-model:checked="values[block.id]"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        >
          {{ block.title }}
        </a-checkbox>

        <!-- 单选框组 -->
        <a-radio-group
          v-else-if="block.type === 'radio'"
          v-model:value="values[block.id]"
          :disabled="block.disabled"
          :options="block.options"
          @change="handleChange(block.id, $event)"
        />

        <!-- 自动完成 -->
        <a-auto-complete
          v-else-if="block.type === 'autocomplete'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          :options="block.options"
          @change="handleChange(block.id, $event)"
        />

        <!-- 树选择 -->
        <a-tree-select
          v-else-if="block.type === 'tree-select'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          :tree-data="block.options"
          @change="handleChange(block.id, $event)"
        />

        <!-- 级联选择 -->
        <a-cascader
          v-else-if="block.type === 'cascader'"
          v-model:value="values[block.id]"
          :placeholder="block.placeholder"
          :disabled="block.disabled"
          :options="block.options"
          @change="handleChange(block.id, $event)"
        />

        <!-- 穿梭框 -->
        <a-transfer
          v-else-if="block.type === 'transfer'"
          v-model:target-keys="values[block.id]"
          :data-source="block.options"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />

        <!-- 上传 -->
        <a-upload
          v-else-if="block.type === 'upload'"
          v-model:file-list="values[block.id]"
          :accept="block.fileTypes?.join(',')"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        >
          <a-button>
            <upload-outlined />
            上传文件
          </a-button>
        </a-upload>

        <!-- 默认输入框（兜底） -->
        <a-input
          v-else
          v-model:value="values[block.id]"
          :placeholder="block.placeholder || `输入 ${block.title}`"
          :disabled="block.disabled"
          @change="handleChange(block.id, $event)"
        />
      </a-form-item>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { UploadOutlined } from '@ant-design/icons-vue'
import type { SubBlockConfig } from '../types'

// ==================== Props ====================

interface Props {
  blocks: SubBlockConfig[]
  values: Record<string, any>
  disabled?: boolean
  readonly?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  readonly: false,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'update:values', values: Record<string, any>): void
  (e: 'change', blockId: string, value: any): void
  (e: 'validate', valid: boolean, errors: Record<string, string>): void
}>()

// ==================== 状态 ====================

const codeEditorRef = ref<HTMLElement | null>(null)
const currentLanguage = ref('javascript')
const jsonText = ref('')
const jsonError = ref('')
const fileList = ref<any[]>([])

// ==================== 计算属性 ====================

/**
 * 过滤可见的 blocks（根据 condition 和 hidden）
 */
const visibleBlocks = computed(() => {
  return props.blocks.filter(block => {
    // 隐藏的块
    if (block.hidden) {
      return false
    }
    
    // 条件判断
    if (block.condition) {
      const { field, operator, value } = block.condition
      const fieldValue = props.values[field]
      
      switch (operator) {
        case 'eq':
          return fieldValue === value
        case 'ne':
          return fieldValue !== value
        case 'gt':
          return fieldValue > value
        case 'lt':
          return fieldValue < value
        case 'gte':
          return fieldValue >= value
        case 'lte':
          return fieldValue <= value
        case 'in':
          return Array.isArray(value) && value.includes(fieldValue)
        case 'nin':
          return Array.isArray(value) && !value.includes(fieldValue)
        case 'contains':
          return String(fieldValue).includes(String(value))
        case 'startsWith':
          return String(fieldValue).startsWith(String(value))
        case 'endsWith':
          return String(fieldValue).endsWith(String(value))
        default:
          return true
      }
    }
    
    return true
  })
})

/**
 * 语言选项
 */
const languageOptions = [
  { label: 'JavaScript', value: 'javascript' },
  { label: 'TypeScript', value: 'typescript' },
  { label: 'Python', value: 'python' },
  { label: 'JSON', value: 'json' },
  { label: 'HTML', value: 'html' },
  { label: 'CSS', value: 'css' },
  { label: 'SQL', value: 'sql' },
  { label: 'Shell', value: 'shell' },
]

// ==================== 方法 ====================

/**
 * 处理值变化
 */
function handleChange(blockId: string, value: any) {
  const newValues = { ...props.values, [blockId]: value }
  emit('update:values', newValues)
  emit('change', blockId, value)
  validateBlock(blockId, value)
}

/**
 * 处理 JSON 变化
 */
function handleJsonChange(blockId: string, event: Event) {
  const target = event.target as HTMLTextAreaElement
  const text = target.value
  
  try {
    const parsed = JSON.parse(text)
    jsonError.value = ''
    handleChange(blockId, parsed)
  } catch (error) {
    jsonError.value = '无效的 JSON 格式'
  }
}

/**
 * 处理文件上传前
 */
function handleBeforeUpload(file: File) {
  // 这里可以添加文件验证逻辑
  return false // 阻止自动上传
}

/**
 * 处理文件变化
 */
function handleFileChange(blockId: string, info: any) {
  handleChange(blockId, info.fileList)
}

/**
 * 获取验证状态
 */
function getValidationStatus(block: SubBlockConfig): '' | 'success' | 'warning' | 'error' {
  if (!block.required) {
    return ''
  }
  
  const value = props.values[block.id]
  if (value === undefined || value === null || value === '') {
    return 'error'
  }
  
  return 'success'
}

/**
 * 获取滑块标记
 */
function getSliderMarks(block: SubBlockConfig) {
  if (block.min === undefined || block.max === undefined) {
    return undefined
  }
  
  return {
    [block.min]: String(block.min),
    [block.max]: String(block.max),
  }
}

/**
 * 验证单个块
 */
function validateBlock(blockId: string, value: any) {
  const block = props.blocks.find(b => b.id === blockId)
  if (!block) return
  
  const errors: Record<string, string> = {}
  
  // 必填验证
  if (block.required && (value === undefined || value === null || value === '')) {
    errors[blockId] = `${block.title} 是必填项`
  }
  
  // 自定义验证
  if (block.validation?.validator && value !== undefined && value !== null && value !== '') {
    const result = block.validation.validator(value)
    if (result !== true) {
      errors[blockId] = typeof result === 'string' ? result : block.validation.message || '验证失败'
    }
  }
  
  // 正则验证
  if (block.validation?.pattern && value) {
    const regex = new RegExp(block.validation.pattern)
    if (!regex.test(String(value))) {
      errors[blockId] = block.validation.message || '格式不正确'
    }
  }
  
  emit('validate', Object.keys(errors).length === 0, errors)
}

/**
 * 验证所有块
 */
function validateAll(): boolean {
  const errors: Record<string, string> = {}
  
  props.blocks.forEach(block => {
    if (block.hidden) return
    
    const value = props.values[block.id]
    
    if (block.required && (value === undefined || value === null || value === '')) {
      errors[block.id] = `${block.title} 是必填项`
    }
    
    if (block.validation?.validator && value !== undefined && value !== null && value !== '') {
      const result = block.validation.validator(value)
      if (result !== true) {
        errors[block.id] = typeof result === 'string' ? result : block.validation.message || '验证失败'
      }
    }
  })
  
  emit('validate', Object.keys(errors).length === 0, errors)
  return Object.keys(errors).length === 0
}

// ==================== 生命周期 ====================

onMounted(() => {
  // 初始化 JSON 文本
  const jsonBlock = props.blocks.find(b => b.type === 'json')
  if (jsonBlock && props.values[jsonBlock.id]) {
    try {
      jsonText.value = JSON.stringify(props.values[jsonBlock.id], null, 2)
    } catch {
      jsonText.value = String(props.values[jsonBlock.id])
    }
  }
})

// ==================== 暴露方法 ====================

defineExpose({
  validateAll,
  validateBlock,
})
</script>

<style scoped>
.sub-block-renderer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sub-block-item {
  margin-bottom: 0;
}

.code-editor-wrapper {
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  overflow: hidden;
}

.language-selector {
  width: 120px;
  margin: 8px;
}

.code-editor {
  min-height: 200px;
  padding: 8px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 14px;
  line-height: 1.5;
  background: #fafafa;
}

.json-editor-wrapper {
  position: relative;
}

.json-error {
  position: absolute;
  bottom: -20px;
  left: 0;
  color: #ff4d4f;
  font-size: 12px;
}

.color-picker {
  width: 100%;
  height: 32px;
  padding: 0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
}
</style>
