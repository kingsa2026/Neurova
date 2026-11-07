<template>
  <div class="group-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('system.groups') }}</h2>
        <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>
      </div>
      <GlassButton v-if="isAdmin" variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- 非管理员:仅提示 -->
    <template v-if="!isAdmin">
      <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
    </template>
    <template v-else>
    <!-- 部门层级树（specs/2026-11-07 §3：parent_group_id 驱动；点选节点过滤卡片到该子树） -->
    <GlassCard v-if="groups.length" style="margin-bottom: 16px">
      <div class="tree-toolbar">
        <span class="tree-title">{{ t('system.groups') }}</span>
        <GlassButton v-if="treeSelected" variant="ghost" size="sm" @click="clearTreeFilter">{{ t('common.all') }}</GlassButton>
      </div>
      <a-tree
        :tree-data="groupTreeData"
        :selected-keys="treeSelected ? [treeSelected] : []"
        default-expand-all
        @select="onTreeSelect"
      />
    </GlassCard>
    <!-- Group list -->
    <a-spin :spinning="loading">
      <div class="groups-grid">
        <GlassCard v-for="group in pagedGroups" :key="group.group_id" :title="group.name" variant="default">
          <template #header>
            <div class="group-header">
              <span class="group-name">{{ group.name }}</span>
              <a-tag>{{ group.members_count ?? 0 }} {{ t('collab.members') }}</a-tag>
            </div>
          </template>
          <p class="group-desc">{{ group.description || '-' }}</p>
          <p class="group-modules" v-if="group.allowed_modules?.length">
            {{ t('system.allowedModules') }}: {{ formatModules(group.allowed_modules) }}
          </p>
          <p class="group-modules" v-if="group.parent_group_id">
            {{ t('system.parentGroup') }}: {{ groupNameById(group.parent_group_id) }}
          </p>
          <p class="group-modules" v-if="group.allowed_categories?.length">
            {{ t('system.allowedCategories') }}: {{ formatCategories(group.allowed_categories) }}
          </p>
          <p class="group-modules" v-else-if="group.allowed_categories">
            {{ t('system.allowedCategories') }}: {{ t('system.categoriesUnrestricted') }}
          </p>
          <p class="group-modules" v-if="group.default_category">
            {{ t('system.defaultCategory') }}: {{ categoryName(group.default_category) }}
          </p>
          <template #footer>
            <div class="group-actions">
              <GlassButton variant="ghost" size="sm" @click="viewMembers(group)">{{ t('collab.members') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="editGroup(group)">{{ t('common.edit') }}</GlassButton>
              <GlassButton variant="danger" size="sm" @click="deleteGroup(group.group_id)">{{ t('common.delete') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-pagination v-if="visibleGroups.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="visibleGroups.length" size="small" style="margin-top: 16px; text-align: center" />
      <a-empty v-if="!groups.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Create/Edit group modal -->
    <a-modal v-model:open="showForm" :title="editingGroup ? t('common.edit') : t('common.create')" @ok="saveGroup" :confirm-loading="saving">
      <a-form layout="vertical" :model="groupForm" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="groupForm.name" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="groupForm.description" :rows="3" />
        </a-form-item>
        <a-form-item :label="t('system.parentGroup')">
          <p class="modules-hint">{{ t('system.parentGroupHint') }}</p>
          <a-tree-select
            v-model:value="groupForm.parent_group_id"
            :tree-data="parentTreeData"
            allow-clear
            tree-default-expand-all
            :placeholder="t('system.parentGroupNone')"
            style="width: 100%"
          />
        </a-form-item>
        <a-form-item :label="t('system.allowedCategories')">
          <p class="modules-hint">{{ t('system.allowedCategoriesHint') }}</p>
          <div class="modules-checklist">
            <a-checkbox
              v-for="cat in categories"
              :key="cat.category_id"
              :checked="selectedCategories.includes(cat.category_id)"
              @change="toggleCategory(cat.category_id)"
            >{{ cat.name }}（{{ cat.category_id }}）</a-checkbox>
            <a-empty v-if="!categories.length" :description="t('common.noData')" />
          </div>
          <div class="modules-toolbar">
            <GlassButton variant="ghost" size="sm" @click="selectedCategories = categories.map(c => c.category_id)">{{ t('common.all') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="selectedCategories = []">{{ t('common.none') }}</GlassButton>
          </div>
        </a-form-item>
        <a-form-item :label="t('system.defaultCategory')">
          <p class="modules-hint">{{ t('system.defaultCategoryHint') }}</p>
          <a-select
            v-model:value="groupForm.default_category"
            :options="defaultCategoryOptions"
            allow-clear
            :placeholder="t('common.none')"
          />
        </a-form-item>
        <a-form-item :label="t('system.allowedModules')">
          <p class="modules-hint">{{ t('system.allowedModulesHint') }}</p>
          <div class="modules-checklist">
            <div v-for="section in MODULE_SECTIONS" :key="section.zone" class="module-section">
              <div class="module-section-title">
                <a-checkbox
                  :checked="isZoneAllSelected(section)"
                  :indeterminate="isZoneIndeterminate(section)"
                  :data-zone="section.zone"
                  @change="toggleZone(section)"
                >{{ t(`nav.${section.zoneLabelKey}`) }}</a-checkbox>
              </div>
              <div class="module-section-items">
                <a-checkbox
                  v-for="item in section.items"
                  :key="item.key"
                  :checked="selectedModules.includes(item.key)"
                  :value="item.key"
                  @change="toggleModule(item.key)"
                >{{ t(`nav.${item.labelKey}`) }}</a-checkbox>
              </div>
            </div>
          </div>
          <div class="modules-toolbar">
            <GlassButton variant="ghost" size="sm" @click="setAllModules(true)">{{ t('common.all') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="setAllModules(false)">{{ t('common.none') }}</GlassButton>
          </div>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Members modal -->
    <a-modal v-model:open="showMembers" :title="t('collab.members')" :footer="null" width="560px">
      <p class="modules-hint">{{ t('system.reloginHint') }}</p>
      <div class="members-header">
        <a-auto-complete
          v-model:value="newMemberName"
          :options="memberNameOptions"
          :placeholder="t('collab.addMember')"
          style="width: 200px"
        />
        <GlassButton variant="primary" size="sm" @click="addMember">{{ t('collab.addMember') }}</GlassButton>
      </div>
      <a-list :data-source="members" size="small" style="margin-top: 12px">
        <template #renderItem="{ item }">
          <a-list-item>
            <div class="member-item">
              <span>{{ item.username }}</span>
              <a-popconfirm :title="t('common.confirm') + '?'" @confirm="removeMember(item.username)">
                <GlassButton variant="ghost" size="sm">{{ t('common.delete') }}</GlassButton>
              </a-popconfirm>
            </div>
          </a-list-item>
        </template>
        <template #empty><a-empty :description="t('common.noData')" /></template>
      </a-list>
    </a-modal>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { listGroups, updateGroup, createGroup, deleteGroup as deleteGroupApi, listGroupMembers, addGroupMember, removeGroupMember, type Group } from '@/api/modules/groups'
import { buildDeptTreeData } from '@/utils/deptTree'
import { listKnowledgeCategories, type KnowledgeCategory } from '@/api/modules/knowledge'
import { listUsers } from '@/api/modules/enhanced-users'
import { MODULE_SECTIONS, ALL_MODULE_KEYS } from '@/config/modules'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message, Modal } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
/** 分组为全局管理数据; 仅管理员可访问与操作 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const saving = ref(false)
const groups = ref<Group[]>([])
const members = ref<any[]>([])
const showForm = ref(false)
const showMembers = ref(false)
const editingGroup = ref<Group | null>(null)
const selectedGroupId = ref<string>('')
const newMemberName = ref('')
const currentPage = ref(1)
const pageSize = ref(12)

const groupForm = ref<{ name: string; description: string; parent_group_id: string; default_category: string }>({ name: '', description: '', parent_group_id: '', default_category: '' })
const selectedModules = ref<string[]>([])
// 部门化（specs/2026-11-07 批 F1）：分类注册表与父组选择
const categories = ref<KnowledgeCategory[]>([])
const selectedCategories = ref<string[]>([])
const users = ref<{ id: string; username?: string }[]>([])

const categoryLabelMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const cat of categories.value) map[cat.category_id] = cat.name
  return map
})
const categoryName = (id: string) => categoryLabelMap.value[id] || id
const formatCategories = (ids: string[]) => ids.map(categoryName).join('、')
const groupNameById = (id: string) => groups.value.find(g => g.group_id === id)?.name || id

/** 父组候选：部门层级树（编辑时排除自身整棵子树，防自指/防环；环由后端 400 兜底） */
const parentTreeData = computed(() =>
  buildDeptTreeData(groups.value, { excludeId: editingGroup.value?.group_id }),
)

// ── 部门层级树视图（specs/2026-11-07 §3：树形展示＋子树过滤）──────────
const treeSelected = ref<string>('')
const groupTreeData = computed(() => buildDeptTreeData(groups.value))

const onTreeSelect = (keys: (string | number)[]) => {
  // 点击已选节点 → keys 为空 = 取消过滤
  treeSelected.value = (keys[0] as string) || ''
  currentPage.value = 1
}
const clearTreeFilter = () => {
  treeSelected.value = ''
}

/** 选中节点的整棵子树（含自身与全部后代；孤儿父链由后端禁环兜底） */
const subtreeIds = computed<Set<string> | null>(() => {
  if (!treeSelected.value) return null
  const ids = new Set<string>([treeSelected.value])
  let grew = true
  while (grew) {
    grew = false
    for (const g of groups.value) {
      if (g.parent_group_id && ids.has(g.parent_group_id) && !ids.has(g.group_id)) {
        ids.add(g.group_id)
        grew = true
      }
    }
  }
  return ids
})
const visibleGroups = computed(() => {
  const ids = subtreeIds.value
  return ids ? groups.value.filter((g) => ids.has(g.group_id)) : groups.value
})

/** 缺省分类候选：本组已勾选的白名单分类 */
const defaultCategoryOptions = computed(() =>
  selectedCategories.value.map(id => ({ label: categoryName(id), value: id })),
)

/** 成员候选（用户选择器数据源） */
const memberNameOptions = computed(() =>
  users.value
    .map(u => ({ value: u.username || '' }))
    .filter(o => o.value),
)

const toggleCategory = (id: string) => {
  const idx = selectedCategories.value.indexOf(id)
  if (idx >= 0) selectedCategories.value.splice(idx, 1)
  else selectedCategories.value.push(id)
  // 缺省分类若被移出白名单，随勾选失效
  if (groupForm.value.default_category && !selectedCategories.value.includes(groupForm.value.default_category)) {
    groupForm.value.default_category = ''
  }
}

const fetchCategories = async () => {
  try {
    const res: any = await listKnowledgeCategories()
    categories.value = res?.data ?? res ?? []
  } catch {
    categories.value = []
  }
}

const fetchUsers = async () => {
  try {
    const res = await listUsers({ page: 1, page_size: 500 })
    users.value = [...(res?.items ?? []), ...(res?.users ?? [])]
  } catch {
    users.value = []
  }
}

const pagedGroups = computed(() =>
  visibleGroups.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

/** 模块 key → 已翻译菜单名（卡片摘要展示用） */
const moduleLabelMap = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const section of MODULE_SECTIONS) {
    for (const item of section.items) {
      map[item.key] = t(`nav.${item.labelKey}`)
    }
  }
  return map
})

const formatModules = (keys: string[]) =>
  keys.map(k => moduleLabelMap.value[k] || k).join('、')

const toggleModule = (key: string) => {
  const idx = selectedModules.value.indexOf(key)
  if (idx >= 0) selectedModules.value.splice(idx, 1)
  else selectedModules.value.push(key)
}

/** 分区全选判定：分区内全部模块已勾选 */
const isZoneAllSelected = (section: (typeof MODULE_SECTIONS)[number]) =>
  section.items.every(item => selectedModules.value.includes(item.key))

/** 分区半选判定：部分选中（antd indeterminate 展示用） */
const isZoneIndeterminate = (section: (typeof MODULE_SECTIONS)[number]) =>
  !isZoneAllSelected(section) && section.items.some(item => selectedModules.value.includes(item.key))

/** 分区全选/清空：已全选则清空该分区，否则补齐该分区全部模块 */
const toggleZone = (section: (typeof MODULE_SECTIONS)[number]) => {
  if (isZoneAllSelected(section)) {
    const keys = new Set(section.items.map(item => item.key))
    selectedModules.value = selectedModules.value.filter(k => !keys.has(k))
  } else {
    const add = section.items.map(item => item.key).filter(k => !selectedModules.value.includes(k))
    selectedModules.value = [...selectedModules.value, ...add]
  }
}

const setAllModules = (all: boolean) => {
  selectedModules.value = all ? [...ALL_MODULE_KEYS] : []
}

const fetchGroups = async () => {
  loading.value = true
  try {
    const res = await listGroups()
    groups.value = res ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingGroup.value = null
  groupForm.value = { name: '', description: '', parent_group_id: '', default_category: '' }
  selectedModules.value = []
  selectedCategories.value = []
  showForm.value = true
}

const editGroup = (group: Group) => {
  editingGroup.value = group
  groupForm.value = {
    name: group.name,
    description: group.description || '',
    parent_group_id: group.parent_group_id || '',
    default_category: group.default_category || '',
  }
  selectedModules.value = [...(group.allowed_modules || [])]
  selectedCategories.value = [...(group.allowed_categories || [])]
  showForm.value = true
}

const saveGroup = async () => {
  saving.value = true
  try {
    // 全不勾 = 不限制（后端契约：空数组 = 未配置）
    const payload = {
      ...groupForm.value,
      parent_group_id: groupForm.value.parent_group_id || null,
      default_category: groupForm.value.default_category || null,
      allowed_modules: [...selectedModules.value],
      allowed_categories: [...selectedCategories.value],
    }
    if (editingGroup.value) {
      await updateGroup(editingGroup.value.group_id, payload)
    } else {
      await createGroup(payload)
    }
    message.success(t('common.success'))
    showForm.value = false
    await fetchGroups()
  } catch (err) {
    message.error(extractDetail(err))
  } finally {
    saving.value = false
  }
}

/** 后端业务错误原文（环校验 400/单主组 409 的 detail 优先于通用文案） */
const extractDetail = (err: unknown) => {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || t('common.error')
}

const deleteGroup = (id: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await deleteGroupApi(id)
        message.success(t('common.success'))
        await fetchGroups()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const viewMembers = async (group: Group) => {
  selectedGroupId.value = group.group_id
  showMembers.value = true
  try {
    const res = await listGroupMembers(group.group_id)
    members.value = res ?? []
  } catch {
    members.value = []
  }
}

const addMember = async () => {
  if (!newMemberName.value) return
  try {
    await addGroupMember(selectedGroupId.value, { username: newMemberName.value })
    message.success(t('common.success'))
    newMemberName.value = ''
    await viewMembers({ group_id: selectedGroupId.value } as Group)
    await fetchGroups()
  } catch (err) {
    message.error(extractDetail(err))
  }
}

const removeMember = async (username: string) => {
  try {
    await removeGroupMember(selectedGroupId.value, username)
    message.success(t('common.success'))
    await viewMembers({ group_id: selectedGroupId.value } as Group)
    await fetchGroups()
  } catch (err) {
    message.error(extractDetail(err))
  }
}

onMounted(() => {
  fetchGroups()
  fetchCategories()
  fetchUsers()
})
</script>

<style scoped>
.group-page { display: flex; flex-direction: column; gap: 20px; }
/* 全局说明与权限提示 */
.page-global-hint { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, #8a8a92); }
.admin-gate { margin: 24px auto; max-width: 480px; padding: 16px; border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12)); border-radius: 10px; text-align: center; font-size: 13px; color: var(--nr-text-secondary, #8a8a92); }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.groups-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.group-header { display: flex; justify-content: space-between; align-items: center; }
.group-name { font-weight: 600; color: var(--nr-text-primary); }
.group-desc { font-size: 13px; color: var(--nr-text-secondary); }
.group-modules { font-size: 12px; color: var(--nr-text-muted); margin-top: 6px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.group-actions { display: flex; gap: 6px; }
.members-header { display: flex; gap: 8px; align-items: center; }
.member-item { display: flex; align-items: center; gap: 8px; width: 100%; }
/* 功能模块勾选清单 */
.modules-hint { font-size: 12px; color: var(--nr-text-secondary); margin: 0 0 8px; }
.modules-checklist { max-height: 260px; overflow-y: auto; border: 1px solid var(--nr-glass-border, rgba(255,255,255,0.12)); border-radius: 10px; padding: 10px 12px; }
.module-section + .module-section { margin-top: 10px; }
.module-section-title { display: flex; align-items: center; margin-bottom: 4px; }
.module-section-title :deep(.ant-checkbox) { font-size: 11px; }
.module-section-title :deep(.ant-checkbox + span) { font-weight: 600; color: var(--nr-text-muted); text-transform: uppercase; letter-spacing: 0.06em; }
.module-section-items { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.modules-toolbar { display: flex; gap: 8px; margin-top: 8px; }
/* 部门层级树 */
.tree-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.tree-title { font-weight: 600; color: var(--nr-text-primary); font-size: 13px; }
</style>
