<template>
  <a-modal
    :open="open"
    :title="t('knowledge.catMgmtTitle')"
    :footer="null"
    width="640px"
    @cancel="close"
  >
    <!-- 注册/编辑表单（编辑态 id 只读——注册表主键不可改） -->
    <div class="cat-form">
      <div class="cat-form-row">
        <div class="cat-field cat-field-id">
          <span class="cat-field-label">{{ t('knowledge.catMgmtId') }}</span>
          <a-input v-model:value="categoryId" :disabled="editingId !== ''" />
          <span class="cat-field-hint">{{ t('knowledge.catMgmtIdHint') }}</span>
        </div>
        <div class="cat-field">
          <span class="cat-field-label">{{ t('common.name') }}</span>
          <a-input v-model:value="name" />
        </div>
      </div>
      <div class="cat-field">
        <span class="cat-field-label">{{ t('common.description') }}</span>
        <a-input v-model:value="description" />
      </div>
      <div class="cat-form-actions">
        <GlassButton variant="ghost" size="sm" v-if="editingId" @click="resetForm">{{ t('common.cancel') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="submit">{{ editingId ? t('common.save') : t('knowledge.catMgmtNew') }}</GlassButton>
      </div>
    </div>

    <!-- 注册表清单（include_inactive 全量：停用可复用，删除白名单如实剔除） -->
    <a-spin :spinning="loading">
      <div class="cat-list">
        <div v-for="cat in categories" :key="cat.category_id" class="cat-row">
          <div class="cat-main">
            <span class="cat-name">{{ cat.name }}</span>
            <a-tag v-if="cat.is_active === false" class="cat-inactive-tag">{{ t('knowledge.catMgmtInactiveTag') }}</a-tag>
          </div>
          <div class="cat-meta">{{ cat.category_id }}<template v-if="cat.description"> · {{ cat.description }}</template></div>
          <div class="cat-ops">
            <GlassButton variant="ghost" size="sm" @click="startEdit(cat)">{{ t('common.edit') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="toggleActive(cat)">
              {{ cat.is_active === false ? t('knowledge.catMgmtEnable') : t('knowledge.catMgmtDisable') }}
            </GlassButton>
            <a-popconfirm :title="t('knowledge.catMgmtDeleteConfirm')" @confirm="removeCategory(cat)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </div>
        <a-empty v-if="!categories.length && !loading" :description="t('common.noData')" />
      </div>
    </a-spin>
  </a-modal>
</template>

<script setup lang="ts">
// ---------------------------------------------------------------------------
// 知识库分类管理弹窗（分类注册表管理面，specs/2026-11-07 批 A 端点的 UI 接线）
//
// 事实源：neurova/knowledge/categories_registry.py（经 /v1/knowledge/categories）。
// 本组件只做 admin 管理动作的承载：注册/改名/停用复用/删除；变更后 emit changed
// 供父页刷新分类下拉（写入→读取→反馈闭环）。
// ---------------------------------------------------------------------------
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  listKnowledgeCategories,
  createKnowledgeCategory,
  updateKnowledgeCategory,
  deleteKnowledgeCategory,
  type KnowledgeCategory,
} from '@/api/modules/knowledge'
import { extractApiDetail } from '@/utils/error'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'changed'): void }>()

const { t } = useI18n()

const loading = ref(false)
const categories = ref<KnowledgeCategory[]>([])
const editingId = ref('')
const categoryId = ref('')
const name = ref('')
const description = ref('')

/** 全量清单（include_inactive=true 仅 admin——本组件只挂 admin 入口） */
const fetchCategories = async () => {
  loading.value = true
  try {
    const res: any = await listKnowledgeCategories(true)
    categories.value = res?.data ?? res ?? []
  } catch {
    categories.value = []
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  editingId.value = ''
  categoryId.value = ''
  name.value = ''
  description.value = ''
}

const close = () => {
  resetForm()
  emit('update:open', false)
}

watch(
  () => props.open,
  (open) => {
    if (open) void fetchCategories()
  },
  // 挂载时已处于打开态（测试/复用场景）也要拉清单
  { immediate: true },
)

const submit = async () => {
  if (editingId.value) {
    if (!name.value.trim()) {
      message.error(t('common.required'))
      return
    }
    try {
      await updateKnowledgeCategory(editingId.value, { name: name.value.trim(), description: description.value })
      message.success(t('knowledge.catMgmtUpdated'))
      resetForm()
      await fetchCategories()
      emit('changed')
    } catch (e) {
      message.error(extractApiDetail(e) || t('common.error'))
    }
    return
  }
  const trimmedId = categoryId.value.trim()
  if (!trimmedId || !name.value.trim()) {
    message.error(t('common.required'))
    return
  }
  try {
    await createKnowledgeCategory({ category_id: trimmedId, name: name.value.trim(), description: description.value })
    message.success(t('knowledge.catMgmtCreated'))
    resetForm()
    await fetchCategories()
    emit('changed')
  } catch (e) {
    message.error(extractApiDetail(e) || t('common.error'))
  }
}

const startEdit = (cat: KnowledgeCategory) => {
  editingId.value = cat.category_id
  categoryId.value = cat.category_id
  name.value = cat.name
  description.value = cat.description || ''
}

const toggleActive = async (cat: KnowledgeCategory) => {
  try {
    await updateKnowledgeCategory(cat.category_id, { is_active: cat.is_active === false })
    await fetchCategories()
    emit('changed')
  } catch (e) {
    message.error(extractApiDetail(e) || t('common.error'))
  }
}

const removeCategory = async (cat: KnowledgeCategory) => {
  try {
    await deleteKnowledgeCategory(cat.category_id)
    message.success(t('knowledge.catMgmtDeleted'))
    // 正在编辑被删对象时回退注册态，防悬挂
    if (editingId.value === cat.category_id) resetForm()
    await fetchCategories()
    emit('changed')
  } catch (e) {
    message.error(extractApiDetail(e) || t('common.error'))
  }
}
</script>

<style scoped>
.cat-form { margin-bottom: 16px; }
.cat-form-row { display: flex; gap: 12px; }
.cat-field { flex: 1; display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; min-width: 0; }
.cat-field-id { flex: 0 0 220px; }
.cat-field-label { font-size: 12px; color: var(--nr-text-secondary); }
.cat-field-hint { font-size: 11px; color: var(--nr-text-muted); }
.cat-form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 2px; }
.cat-list { max-height: 380px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.cat-row { border: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.12)); border-radius: var(--nr-radius-sm, 6px); padding: 10px 12px; }
.cat-main { display: flex; align-items: center; gap: 8px; }
.cat-name { font-weight: 600; color: var(--nr-text-primary); font-size: 13px; }
.cat-inactive-tag { font-size: 11px; }
.cat-meta { font-size: 12px; color: var(--nr-text-tertiary); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cat-ops { display: flex; gap: 6px; margin-top: 8px; }
</style>
