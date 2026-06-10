<template>
  <div class="nr-glass-input" :class="{ 'is-focused': focused, 'has-error': error, 'is-disabled': disabled }">
    <label v-if="label" class="nr-glass-input-label">{{ label }}</label>
    <div class="nr-glass-input-wrap">
      <span v-if="$slots.prefix" class="nr-glass-input-prefix"><slot name="prefix" /></span>
      <input
        ref="inputRef"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :autocomplete="autocomplete"
        class="nr-glass-input-field"
        @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @focus="focused = true"
        @blur="focused = false"
      />
      <span v-if="$slots.suffix" class="nr-glass-input-suffix"><slot name="suffix" /></span>
    </div>
    <span v-if="error" class="nr-glass-input-error">{{ error }}</span>
    <span v-if="hint && !error" class="nr-glass-input-hint">{{ hint }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

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

defineEmits<{ 'update:modelValue': [value: string] }>()

const inputRef = ref<HTMLInputElement | null>(null)
const focused = ref(false)

defineExpose({ focus: () => inputRef.value?.focus() })
</script>

<style scoped>
.nr-glass-input { display: flex; flex-direction: column; gap: 6px; }
.nr-glass-input-label {
  font-size: 12px; font-weight: 500; color: var(--nr-text-secondary);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.nr-glass-input-wrap {
  display: flex; align-items: center; gap: 8px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px; padding: 0 14px; height: 42px;
  transition: all 0.25s ease;
  backdrop-filter: blur(10px);
}
.nr-glass-input-wrap:hover { border-color: rgba(255,255,255,0.14); }
.is-focused .nr-glass-input-wrap {
  border-color: var(--nr-primary); background: rgba(99,102,241,0.06);
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
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
