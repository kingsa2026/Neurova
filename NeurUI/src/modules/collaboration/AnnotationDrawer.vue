<script setup lang="ts">
/**
 * AnnotationDrawer.vue — 精准回复命中表管理（P2 标注闭环前端）
 *
 * 列出/新增/编辑/启停/删除标注 + 重训练化集导出（JSONL）。
 * 挂在知识库页：标注是人工修正固化的知识资产。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import {
  listAnnotations,
  createAnnotation,
  updateAnnotation,
  deleteAnnotation,
  exportAnnotationTrainingSet,
  type AnnotationItem,
} from '@/api/modules/knowledge'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', v: boolean): void }>()

const { t } = useI18n()

const items = ref<AnnotationItem[]>([])
const total = ref(0)
const loading = ref(false)
const filter = ref('')

// 新增表单
const creating = ref(false)
const newQuestion = ref('')
const newAnswer = ref('')
const submitLoading = ref(false)

// 编辑
const editing = ref<AnnotationItem | null>(null)
const editAnswer = ref('')

async function reload() {
  loading.value = true
  try {
    const res = await listAnnotations(filter.value, 200)
    const data = (res?.data ?? res) as { items?: AnnotationItem[]; total?: number }
    items.value = data?.items ?? []
    total.value = data?.total ?? items.value.length
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) void reload()
  },
  { immediate: true },
)

async function handleCreate() {
  if (!newQuestion.value.trim() || !newAnswer.value.trim() || submitLoading.value) return
  submitLoading.value = true
  try {
    await createAnnotation(newQuestion.value.trim(), newAnswer.value.trim())
    message.success(t('annotation.created'))
    newQuestion.value = ''
    newAnswer.value = ''
    creating.value = false
    await reload()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitLoading.value = false
  }
}

function openEdit(item: AnnotationItem) {
  editing.value = item
  editAnswer.value = item.answer
}

async function handleSaveEdit() {
  if (!editing.value) return
  try {
    await updateAnnotation(editing.value.id, { answer: editAnswer.value })
    message.success(t('annotation.updated'))
    editing.value = null
    await reload()
  } catch {
    /* 拦截器已提示 */
  }
}

async function handleToggle(item: AnnotationItem) {
  await updateAnnotation(item.id, { enabled: !item.enabled })
  await reload()
}

async function handleDelete(item: AnnotationItem) {
  await deleteAnnotation(item.id)
  message.success(t('annotation.deleted'))
  await reload()
}

async function handleExport() {
  try {
    const res = await exportAnnotationTrainingSet()
    const data = (res?.data ?? res) as { jsonl: string; count: number }
    const blob = new Blob([data.jsonl], { type: 'application/jsonl' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'annotations-training-set.jsonl'
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('annotation.exported', { n: data.count }))
  } catch {
    /* 拦截器已提示 */
  }
}
</script>

<template>
  <a-drawer
    :open="open"
    :title="t('annotation.drawerTitle')"
    :width="640"
    @close="emit('update:open', false)"
  >
    <div class="ann-toolbar">
      <a-input-search
        v-model:value="filter"
        :placeholder="t('annotation.filterPh')"
        style="flex: 1"
        allow-clear
        @search="reload"
      />
      <a-button @click="handleExport">{{ t('annotation.export') }}</a-button>
      <a-button type="primary" @click="creating = !creating">
        {{ creating ? t('common.cancel') : t('annotation.create') }}
      </a-button>
    </div>

    <!-- 新增表单 -->
    <div v-if="creating" class="ann-form" data-testid="annotation-form">
      <a-input v-model:value="newQuestion" :placeholder="t('annotation.questionPh')" />
      <a-textarea v-model:value="newAnswer" :rows="3" :placeholder="t('annotation.answerPh')" />
      <a-button type="primary" block :loading="submitLoading" @click="handleCreate">
        {{ t('annotation.save') }}
      </a-button>
    </div>

    <!-- 编辑态 -->
    <div v-if="editing" class="ann-form" data-testid="annotation-edit">
      <div class="ann-edit-q">{{ editing.question }}</div>
      <a-textarea v-model:value="editAnswer" :rows="3" />
      <div style="display: flex; gap: 8px">
        <a-button type="primary" style="flex: 1" @click="handleSaveEdit">{{ t('annotation.save') }}</a-button>
        <a-button style="flex: 1" @click="editing = null">{{ t('common.cancel') }}</a-button>
      </div>
    </div>

    <a-spin :spinning="loading">
      <div v-if="items.length === 0" class="ann-empty">{{ t('annotation.empty') }}</div>
      <div v-else class="ann-list" data-testid="annotation-list">
        <div v-for="a in items" :key="a.id" class="ann-row">
          <div class="ann-main">
            <div class="ann-q">
              {{ a.question }}
              <a-tag v-if="!a.enabled" color="red">{{ t('annotation.disabled') }}</a-tag>
            </div>
            <div class="ann-a">{{ a.answer }}</div>
            <div class="ann-meta">
              <a-tag color="blue">×{{ a.hit_count }}</a-tag>
              <span>{{ a.source }}</span>
            </div>
          </div>
          <div class="ann-actions">
            <a-button size="small" @click="openEdit(a)">{{ t('common.edit') }}</a-button>
            <a-button size="small" @click="handleToggle(a)">
              {{ a.enabled ? t('annotation.disable') : t('annotation.enable') }}
            </a-button>
            <a-popconfirm :title="t('annotation.deleteConfirm')" @confirm="handleDelete(a)">
              <a-button size="small" danger>{{ t('common.delete') }}</a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>
    </a-spin>
  </a-drawer>
</template>

<style scoped>
.ann-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.ann-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid var(--nr-border, #e5e7eb);
  border-radius: 6px;
}
.ann-edit-q {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
}
.ann-empty {
  color: var(--nr-text-tertiary, #6b7280);
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
.ann-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ann-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--nr-border, #e5e7eb);
  border-radius: 6px;
}
.ann-main {
  min-width: 0;
  flex: 1;
}
.ann-q {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
  word-break: break-all;
}
.ann-a {
  font-size: 12px;
  color: var(--nr-text-secondary);
  margin-top: 4px;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ann-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 4px;
  font-size: 11px;
  color: var(--nr-text-tertiary, #6b7280);
}
.ann-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-shrink: 0;
}
</style>
