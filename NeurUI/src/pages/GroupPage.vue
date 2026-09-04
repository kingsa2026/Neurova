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
          <template #footer>
            <div class="group-actions">
              <GlassButton variant="ghost" size="sm" @click="viewMembers(group)">{{ t('collab.members') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="editGroup(group)">{{ t('common.edit') }}</GlassButton>
              <GlassButton variant="danger" size="sm" @click="deleteGroup(group.group_id)">{{ t('common.delete') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-pagination v-if="groups.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="groups.length" size="small" style="margin-top: 16px; text-align: center" />
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
      <div class="members-header">
        <a-input v-model:value="newMemberName" :placeholder="t('collab.addMember')" style="width: 200px" />
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

const groupForm = ref({ name: '', description: '' })
const selectedModules = ref<string[]>([])

const pagedGroups = computed(() =>
  groups.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
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
  groupForm.value = { name: '', description: '' }
  selectedModules.value = []
  showForm.value = true
}

const editGroup = (group: Group) => {
  editingGroup.value = group
  groupForm.value = { name: group.name, description: group.description || '' }
  selectedModules.value = [...(group.allowed_modules || [])]
  showForm.value = true
}

const saveGroup = async () => {
  saving.value = true
  try {
    // 全不勾 = 不限制（后端契约：空数组 = 未配置）
    const payload = {
      ...groupForm.value,
      allowed_modules: [...selectedModules.value],
    }
    if (editingGroup.value) {
      await updateGroup(editingGroup.value.group_id, payload)
    } else {
      await createGroup(payload)
    }
    message.success(t('common.success'))
    showForm.value = false
    await fetchGroups()
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
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
  } catch {
    message.error(t('common.error'))
  }
}

const removeMember = async (username: string) => {
  try {
    await removeGroupMember(selectedGroupId.value, username)
    message.success(t('common.success'))
    await viewMembers({ group_id: selectedGroupId.value } as Group)
    await fetchGroups()
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(fetchGroups)
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
</style>
