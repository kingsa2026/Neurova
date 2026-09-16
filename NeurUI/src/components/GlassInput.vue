<template>
  <div class="nr-glass-input" :class="{ 'is-focused': focused, 'has-error': error, 'is-disabled': disabled }">
    <label v-if="label" :for="inputId" class="nr-glass-input-label">{{ label }}</label>
    <div class="nr-glass-input-wrap">
      <span v-if="$slots.prefix" class="nr-glass-input-prefix"><slot name="prefix" /></span>
      <input
        ref="inputRef"
        :id="inputId"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :autocomplete="autocomplete"
        class="nr-glass-input-field"
        @input="onInput"
        @focus="focused = true"
        @blur="onBlur"
      />
      <span v-if="$slots.suffix" class="nr-glass-input-suffix"><slot name="suffix" /></span>
    </div>
    <span v-if="error" class="nr-glass-input-error">{{ error }}</span>
    <span v-if="hint && !error" class="nr-glass-input-hint">{{ hint }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Form } from 'ant-design-vue'

// 根入口未导出该 hook（4.2.6 实测），官方模式：Form.useInjectFormItemContext
const useInjectFormItemContext = Form.useInjectFormItemContext

withDefaults(defineProps<{
  modelValue?: string
  type?: string
  label?: string
  placeholder?: string
  error?: string
  hint?: string
  disabled?: boolean
  autocomplete?: string
}>(), {
  modelValue: '',
  type: 'text',
  disabled: false,
  autocomplete: 'off',
})

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

// Ant Design FormItem 契约接线（2026-09-16 根修，契约见 GlassInput.formItem.test.ts）：
// 内置 a-input 把 FormItem 生成的 id 绑到 input 上，<label for> 由此命中；
// 独立使用时（无 FormItem，id 为 undefined）自生成 uid 关联自带 label prop。
const formItemContext = useInjectFormItemContext()
const uid = `nr-glass-input-${Math.random().toString(36).slice(2, 8)}`
const inputId = computed(() => formItemContext.id.value ?? uid)

const inputRef = ref<HTMLInputElement | null>(null)
const focused = ref(false)

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
  formItemContext.onFieldChange()
}
function onBlur(): void {
  focused.value = false
  formItemContext.onFieldBlur()
}

defineExpose({ focus: () => inputRef.value?.focus() })
</script>

<style scoped>
.nr-glass-input { display: flex; flex-direction: column; gap: 6px; }
.nr-glass-input-label {
  font-size: 13px; font-weight: 600; color: var(--nr-text-secondary);
  letter-spacing: -0.01em;
}
.nr-glass-input-wrap {
  display: flex; align-items: center; gap: 8px;
  background: var(--nr-glass-bg); border: 1px solid var(--nr-glass-border);
  border-radius: 12px; padding: 0 14px; height: 42px;
  transition: all 0.25s ease;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.nr-glass-input-wrap:hover { border-color: var(--nr-glass-border-hover); background: var(--nr-glass-bg-hover); }
.is-focused .nr-glass-input-wrap {
  border-color: var(--nr-primary); background: var(--nr-primary-soft);
  box-shadow: 0 0 0 3px var(--nr-primary-ring);
}
.has-error .nr-glass-input-wrap { border-color: var(--nr-error); }
.is-disabled .nr-glass-input-wrap { opacity: 0.4; pointer-events: none; }
.nr-glass-input-field {
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--nr-text-primary); font-size: 14px; font-family: var(--nr-font-body);
  height: 100%;
}
.nr-glass-input-field::placeholder { color: var(--nr-text-muted); }
.nr-glass-input-prefix, .nr-glass-input-suffix { color: var(--nr-text-tertiary); display: flex; }
.nr-glass-input-error { font-size: 11px; color: var(--nr-error); }
.nr-glass-input-hint { font-size: 11px; color: var(--nr-text-muted); }
</style>
