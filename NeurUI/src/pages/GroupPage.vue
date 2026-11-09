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
    <!-- 双栏：左分组树（系统分组/自定义分组两段）× 右成员面板（未选中=未分组用户） -->
    <a-spin :spinning="loading">
      <div class="layout-two-col">
        <GlassCard class="panel-tree">
          <template #header>
            <div class="panel-head">
              <span class="panel-title">{{ t('system.groups') }}</span>
              <GlassButton v-if="treeSelected" variant="ghost" size="sm" @click="clearTreeFilter">{{ t('common.all') }}</GlassButton>
            </div>
          </template>
          <div class="tree-body">
            <a-tree
              :tree-data="groupTreeData"
              :selected-keys="treeSelected ? [treeSelected] : []"
              default-expand-all
              block-node
              @select="onTreeSelect"
            >
              <template #title="{ data }">
                <span class="dept-node">
                  <ApartmentOutlined class="dept-node-icon" />
                  <span class="dept-node-name">{{ data.title }}</span>
                  <span v-if="data.membersCount != null" class="dept-node-badge">{{ data.membersCount }}</span>
                  <span v-if="data.groupId" class="node-actions">
                    <button class="node-action" @click.stop="selectGroup(data.groupId)">{{ t('collab.members') }}</button>
                    <button v-if="!data.isSystem" class="node-action" @click.stop="openRename(data.groupId)">{{ t('common.rename') }}</button>
                    <button class="node-action" @click.stop="editGroupById(data.groupId)">{{ t('common.edit') }}</button>
                    <button v-if="!data.isSystem" class="node-action node-action--danger" @click.stop="deleteGroupById(data.groupId)">{{ t('common.delete') }}</button>
                  </span>
                </span>
              </template>
            </a-tree>
            <a-empty v-if="!groups.length && !loading" :description="t('common.noData')" />
          </div>
        </GlassCard>

        <GlassCard class="panel-members">
          <template #header>
            <div class="panel-head">
              <span class="panel-title">{{ treeSelected && selectedGroup ? selectedGroup.name : t('system.ungroupedUsers') }}</span>
              <a-tag>{{ treeSelected ? selectedMembers.length : ungroupedUsernames.length }}</a-tag>
            </div>
          </template>
          <p class="panel-hint">{{ treeSelected ? t('system.reloginHint') : t('system.ungroupedHint') }}</p>
          <template v-if="treeSelected && selectedGroup">
            <div class="members-header">
              <a-auto-complete
                v-model:value="newMemberName"
                :options="memberNameOptions"
                :placeholder="t('collab.addMember')"
                style="width: 200px"
              />
              <GlassButton variant="primary" size="sm" @click="addMember">{{ t('collab.addMember') }}</GlassButton>
            </div>
            <a-list :data-source="selectedMembers" size="small" style="margin-top: 12px">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="member-item">
                    <span>{{ item }}</span>
                    <a-popconfirm :title="t('common.confirm') + '?'" @confirm="removeMember(item)">
                      <GlassButton variant="ghost" size="sm">{{ t('common.delete') }}</GlassButton>
                    </a-popconfirm>
                  </div>
                </a-list-item>
              </template>
              <template #empty><a-empty :description="t('common.noData')" /></template>
            </a-list>
          </template>
          <template v-else>
            <a-list :data-source="ungroupedUsernames" size="small">
              <template #renderItem="{ item }">
                <a-list-item>
                  <div class="member-item"><span>{{ item }}</span></div>
                </a-list-item>
              </template>
              <template #empty><a-empty :description="t('common.noData')" /></template>
            </a-list>
          </template>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Create/Edit group modal -->
    <a-modal v-model:open="showForm" :title="editingGroup ? t('common.edit') : t('common.create')" @ok="saveGroup" :confirm-loading="saving">
      <a-form layout="vertical" :model="groupForm" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="groupForm.name" :disabled="editingIsSystem" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="groupForm.description" :rows="3" :disabled="editingIsSystem" />
        </a-form-item>
        <a-form-item :label="t('system.parentGroup')">
          <p class="modules-hint">{{ t('system.parentGroupHint') }}</p>
          <a-tree-select
            v-model:value="groupForm.parent_group_id"
            :tree-data="parentTreeData"
            allow-clear
            tree-default-expand-all
            :placeholder="t('system.parentGroupNone')"
            :disabled="editingIsSystem"
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

    <!-- Rename modal（快捷改名：仅自定义组；系统组名称由后端保护） -->
    <a-modal v-model:open="showRename" :title="t('common.rename')" @ok="saveRename" :confirm-loading="renaming">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="renameName" />
        </a-form-item>
      </a-form>
    </a-modal>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { listGroups, updateGroup, createGroup, deleteGroup as deleteGroupApi, addGroupMember, removeGroupMember, type Group } from '@/api/modules/groups'
import { buildDeptTreeData } from '@/utils/deptTree'
import { listKnowledgeCategories, type KnowledgeCategory } from '@/api/modules/knowledge'
import { listUsers } from '@/api/modules/enhanced-users'
import { MODULE_SECTIONS, ALL_MODULE_KEYS } from '@/config/modules'
import { ApartmentOutlined } from '@ant-design/icons-vue'
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
const showForm = ref(false)
const editingGroup = ref<Group | null>(null)
const newMemberName = ref('')

// 快捷改名（仅自定义组；系统组名称/描述由后端 update_group 保护）
const showRename = ref(false)
const renaming = ref(false)
const renameGroupId = ref('')
const renameName = ref('')

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

/** 父组候选：部门层级树（编辑时排除自身整棵子树，防自指/防环；环由后端 400 兜底） */
const parentTreeData = computed(() =>
  buildDeptTreeData(groups.value, { excludeId: editingGroup.value?.group_id }),
)

// ── 分组树视图（用户示意图 2026-11-09：系统分组/自定义分组两段；点选组 → 右面板显示成员）──
const treeSelected = ref<string>('')

/** 两段小节的 key（组 id 是 UUID，冒号前缀保证不与其冲突） */
const SECTION_SYSTEM_KEY = 'section:system'
const SECTION_CUSTOM_KEY = 'section:custom'

const systemGroups = computed(() => groups.value.filter(g => g.is_system))
const customGroups = computed(() => groups.value.filter(g => !g.is_system))

const groupNode = (g: Group) => ({
  title: g.name,
  value: g.group_id,
  key: g.group_id,
  membersCount: g.members_count,
  groupId: g.group_id,
  isSystem: !!g.is_system,
})

const groupTreeData = computed(() => [
  {
    key: SECTION_SYSTEM_KEY,
    title: t('system.builtinGroups'),
    value: SECTION_SYSTEM_KEY,
    membersCount: systemGroups.value.length,
    selectable: false,
    children: systemGroups.value.map(groupNode),
  },
  {
    key: SECTION_CUSTOM_KEY,
    title: t('system.customGroups'),
    value: SECTION_CUSTOM_KEY,
    membersCount: customGroups.value.length,
    selectable: false,
    children: buildDeptTreeData(customGroups.value),
  },
])

const onTreeSelect = (keys: (string | number)[]) => {
  // 点击已选节点 → keys 为空 = 回到未分组视图；小节 key 非组 id，同样视为未选中
  const key = (keys[0] as string) || ''
  treeSelected.value = key && groups.value.some(g => g.group_id === key) ? key : ''
}
const clearTreeFilter = () => {
  treeSelected.value = ''
}
const selectGroup = (groupId: string) => {
  treeSelected.value = groupId
}

/** 右面板（选中组）：成员名直接取 listGroups 契约里的 members（单一事实源），不二次拉成员端点 */
const selectedGroup = computed(() => groups.value.find(g => g.group_id === treeSelected.value) || null)
const selectedMembers = computed(() => selectedGroup.value?.members ?? [])

/** 未分组用户：全部用户 − 各组成员并集 */
const ungroupedUsers = computed(() => {
  const grouped = new Set<string>()
  for (const g of groups.value) {
    for (const m of g.members ?? []) grouped.add(m)
  }
  return users.value.filter(u => u.username && !grouped.has(u.username))
})
const ungroupedUsernames = computed(() => ungroupedUsers.value.map(u => u.username!))

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

/** 系统组名称/描述/父组由后端保护，编辑弹窗内禁用（权限面 allowed_modules/分类仍可改） */
const editingIsSystem = computed(() => !!editingGroup.value?.is_system)

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

const editGroupById = (groupId: string) => {
  const group = groups.value.find(g => g.group_id === groupId)
  if (group) editGroup(group)
}

const openRename = (groupId: string) => {
  const group = groups.value.find(g => g.group_id === groupId)
  if (!group) return
  renameGroupId.value = groupId
  renameName.value = group.name
  showRename.value = true
}

const saveRename = async () => {
  if (!renameName.value.trim()) {
    message.error(t('common.required'))
    return
  }
  renaming.value = true
  try {
    await updateGroup(renameGroupId.value, { name: renameName.value.trim() })
    message.success(t('common.success'))
    showRename.value = false
    await fetchGroups()
  } catch (err) {
    message.error(extractDetail(err))
  } finally {
    renaming.value = false
  }
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

const deleteGroupById = (groupId: string) => {
  Modal.confirm({
    title: t('common.confirm'),
    content: t('agent.deleteConfirm'),
    onOk: async () => {
      try {
        await deleteGroupApi(groupId)
        message.success(t('common.success'))
        if (treeSelected.value === groupId) treeSelected.value = ''
        await fetchGroups()
      } catch {
        message.error(t('common.error'))
      }
    },
  })
}

const addMember = async () => {
  if (!treeSelected.value || !newMemberName.value) return
  try {
    await addGroupMember(treeSelected.value, { username: newMemberName.value })
    message.success(t('common.success'))
    newMemberName.value = ''
    await fetchGroups()
  } catch (err) {
    message.error(extractDetail(err))
  }
}

const removeMember = async (username: string) => {
  if (!treeSelected.value) return
  try {
    await removeGroupMember(treeSelected.value, username)
    message.success(t('common.success'))
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
/* 双栏布局：左分组树 × 右成员面板（窄屏折叠单栏） */
.layout-two-col { display: grid; grid-template-columns: minmax(380px, 2fr) 3fr; gap: 16px; }
@media (max-width: 1024px) { .layout-two-col { grid-template-columns: 1fr; } }
.panel-tree, .panel-members { min-height: 480px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.panel-title { font-weight: 600; color: var(--nr-text-primary); font-size: 13px; }
.panel-hint { font-size: 12px; color: var(--nr-text-secondary); margin: 0 0 10px; }
.members-header { display: flex; gap: 8px; align-items: center; }
.member-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; }
/* 功能模块勾选清单 */
.modules-hint { font-size: 12px; color: var(--nr-text-secondary); margin: 0 0 8px; }
.modules-checklist { max-height: 260px; overflow-y: auto; border: 1px solid var(--nr-glass-border, rgba(255,255,255,0.12)); border-radius: 10px; padding: 10px 12px; }
.module-section + .module-section { margin-top: 10px; }
.module-section-title { display: flex; align-items: center; margin-bottom: 4px; }
.module-section-title :deep(.ant-checkbox) { font-size: 11px; }
.module-section-title :deep(.ant-checkbox + span) { font-weight: 600; color: var(--nr-text-muted); text-transform: uppercase; letter-spacing: 0.06em; }
.module-section-items { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.modules-toolbar { display: flex; gap: 8px; margin-top: 8px; }
/* 部门层级树（玻璃拟态贴合：圆角行、悬停/选中主色化、缩进引导线） */
.tree-body :deep(.ant-tree) { background: transparent; }
.tree-body :deep(.ant-tree-treenode) {
  padding: 2px 4px;
  border-radius: var(--nr-radius-sm);
  transition: background-color var(--nr-transition-fast);
}
/* 悬停整行亮起节点背景（含缩进区），圆角与卡片语言一致 */
.tree-body :deep(.ant-tree-treenode:hover) { background: var(--nr-glass-bg-hover); }
/* 缩进引导线：虚线垂直线贯穿每层缩进单元 */
.tree-body :deep(.ant-tree-indent-unit) { position: relative; }
.tree-body :deep(.ant-tree-indent-unit::before) {
  content: '';
  position: absolute;
  inset-block: -4px;
  inset-inline-end: 8px;
  border-inline-end: 1px dashed var(--nr-border);
}
/* 切换箭头：弱化静态色，悬停提亮 */
.tree-body :deep(.ant-tree-switcher) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--nr-text-tertiary);
  transition: color var(--nr-transition-fast);
}
.tree-body :deep(.ant-tree-switcher:hover) { color: var(--nr-text-secondary); }
.tree-body :deep(.ant-tree-node-content-wrapper) {
  flex: 1;
  min-width: 0;
  padding: 3px 8px;
  border-radius: var(--nr-radius-sm);
  transition: background-color var(--nr-transition-fast), color var(--nr-transition-fast), box-shadow var(--nr-transition-fast);
}
.tree-body :deep(.ant-tree-node-content-wrapper.ant-tree-node-selected) {
  background: var(--nr-primary-soft);
  color: var(--nr-primary);
  box-shadow: inset 0 0 0 1px var(--nr-primary-soft-border);
}
/* 节点内容：图标 + 名称 + 成员数徽章 + 行内操作（占满整行，操作推到最右） */
.dept-node { display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; }
.dept-node-icon { flex: none; font-size: 12px; color: var(--nr-text-tertiary); transition: color var(--nr-transition-fast); }
.dept-node-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--nr-text-primary); transition: color var(--nr-transition-fast); }
.dept-node-badge {
  flex: none;
  min-width: 18px;
  height: 16px;
  padding: 0 6px;
  border-radius: 8px;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
  background: var(--nr-glass-bg-active);
  color: var(--nr-text-tertiary);
  transition: background-color var(--nr-transition-fast), color var(--nr-transition-fast), box-shadow var(--nr-transition-fast);
}
/* 选中态：图标/名称转主色，徽章随选中面浮一层主色描边 */
.tree-body :deep(.ant-tree-node-selected) .dept-node-icon { color: var(--nr-primary); }
.tree-body :deep(.ant-tree-node-selected) .dept-node-name { color: var(--nr-primary); font-weight: 600; }
.tree-body :deep(.ant-tree-node-selected) .dept-node-badge {
  background: var(--nr-primary-soft);
  color: var(--nr-primary);
  box-shadow: inset 0 0 0 1px var(--nr-primary-soft-border);
}
/* 选中行悬停不再叠加玻璃底，保持选中面纯净 */
.tree-body :deep(.ant-tree-treenode:has(.ant-tree-node-selected):hover) { background: transparent; }
/* 行内操作：纯文本小按钮，悬停提亮（危险项悬停转红） */
.node-actions { display: inline-flex; gap: 12px; margin-left: auto; flex: none; }
.node-action {
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
  color: var(--nr-text-secondary);
  transition: color var(--nr-transition-fast);
}
.node-action:hover { color: var(--nr-primary); }
.node-action--danger:hover { color: var(--nr-error); }
</style>
