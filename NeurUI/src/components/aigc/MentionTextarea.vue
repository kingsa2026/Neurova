<script setup lang="ts">
/**
 * MentionTextarea：
 * 提示词编辑器输入 @ 弹出资产候选（角色/道具），选中插入 @名称 并回报映射，
 * 后端 generate_shot_images 依据映射注入参考图（一致性）。
 */
import { computed, nextTick, ref } from 'vue'

interface Candidate { name: string; id: string }

const props = defineProps<{
  modelValue: string
  candidates: Candidate[]
  rows?: number
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'refs', v: Candidate[]): void
}>()

const el = ref<HTMLTextAreaElement | null>(null)
const showPicker = ref(false)
const query = ref('')
const caret = ref(0)

const filtered = computed(() => {
  const q = query.value.toLowerCase()
  return props.candidates.filter((c) => !q || c.name.toLowerCase().includes(q))
})

const selected = ref<Candidate[]>([])

function onInput(ev: Event) {
  const target = ev.target as HTMLTextAreaElement
  const value = target.value
  emit('update:modelValue', value)
  const pos = target.selectionStart ?? value.length
  caret.value = pos
  const before = value.slice(0, pos)
  const at = before.lastIndexOf('@')
  if (at !== -1 && !/[\s@]/.test(before.slice(at + 1))) {
    query.value = before.slice(at + 1)
    showPicker.value = props.candidates.length > 0
  } else {
    showPicker.value = false
  }
  syncSelected(value)
}

/** 解析文本中的 @名称 → 资产映射（去重） */
function syncSelected(value: string) {
  const found = props.candidates.filter((c) => value.includes(`@${c.name}`))
  const changed = JSON.stringify(found) !== JSON.stringify(selected.value)
  selected.value = found
  if (changed) emit('refs', found)
}

async function pick(c: Candidate) {
  const target = el.value
  if (!target) return
  const value = target.value
  const pos = target.selectionStart ?? value.length
  const at = value.slice(0, pos).lastIndexOf('@')
  const next = value.slice(0, at) + `@${c.name} ` + value.slice(pos)
  emit('update:modelValue', next)
  showPicker.value = false
  await nextTick()
  target.focus()
  const cur = target.value.length
  target.setSelectionRange(cur, cur)
  syncSelected(next)
}

defineExpose({ syncSelected, pick, showPicker, filtered })
</script>

<template>
  <div class="mention-wrap">
    <textarea
      ref="el"
      class="mention-input"
      :rows="rows ?? 2"
      :value="modelValue"
      :placeholder="placeholder"
      @input="onInput"
    />
    <div v-if="showPicker" class="mention-picker">
      <button
        v-for="c in filtered"
        :key="c.id"
        type="button"
        class="mention-option"
        @click="pick(c)"
      >@{{ c.name }}</button>
      <div v-if="!filtered.length" class="mention-empty">—</div>
    </div>
  </div>
</template>

<style scoped>
.mention-wrap { position: relative; }
.mention-input {
  width: 100%;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
  border-radius: 8px;
  background: transparent;
  color: var(--nr-text-primary);
  padding: 6px 10px;
  font-size: 13px;
  resize: vertical;
}
.mention-picker {
  position: absolute;
  z-index: 30;
  top: 100%;
  left: 8px;
  max-height: 160px;
  overflow: auto;
  min-width: 140px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
  background: var(--nr-bg-elevated, #1c1f2a);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  padding: 4px;
}
.mention-option {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--nr-text-primary);
  padding: 5px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.mention-option:hover { background: rgba(125, 125, 125, 0.18); }
.mention-empty { padding: 6px 8px; color: var(--nr-text-secondary); font-size: 12px; }
</style>
