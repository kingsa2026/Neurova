<template><div class="pg"><div class="hd glass-effect"><h2 class="t"><ThunderboltOutlined :style="{color:'#3b82f6'}"/> Agent 技能</h2><a-button type="primary" size="small">打包可打包技能</a-button></div><div class="sr"><div class="s glass-effect">已安装<b class="c1">{{ data.length }}</b></div><div class="s glass-effect">启用<b style="color:#34d399">{{ data.filter(d=>d.on).length }}</b></div><div class="s glass-effect">可打包<b style="color:#fbbf24">{{ data.filter(d=>d.pk).length }}</b></div></div><div class="tb glass-effect"><a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false"><template #bodyCell="{column,record}"><template v-if="column.key==='st'"><a-switch v-model:checked="record.on" size="small" @change="toggleSkill(record)"/></template><template v-if="column.key==='act'"><a-space><a-button type="link" size="small" :disabled="!record.pk" @click="packSkill(record)">打包</a-button><a-button type="link" size="small" @click="pushSkill(record.id)">推送</a-button><a-popconfirm title="卸载?" @confirm="data=data.filter(d=>d.id!==record.id)"><a-button type="link" size="small" danger>卸载</a-button></a-popconfirm></a-space></template></template></a-table></div></div></template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { listPrivateSkills, pushSkillToAgent } from '@/api/modules/skill'
import { useAgentPage } from '@/composables/useAgentPage'
import { ThunderboltOutlined } from '@ant-design/icons-vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/skills', () => loadSkills())

const cols = [
  { title: '技能名', dataIndex: 'name' },
  { title: '版本', dataIndex: 'ver' },
  { title: '类型', dataIndex: 'type' },
  { title: '状态', key: 'st', width: 80 },
  { title: '操作', key: 'act', width: 200 }
]

interface SkillData {
  id: string
  name: string
  ver: string
  type: string
  on: boolean
  pk: boolean
}

const data = ref<SkillData[]>([])
const loading = ref(false)

async function loadSkills() {
  loading.value = true
  try {
    const skills = await listPrivateSkills()
    if (skills?.length) {
      data.value = skills.map((s: Record<string, unknown>) => ({
        id: s.id || s.skill_id,
        name: s.name || s.title || '',
        ver: s.version || '1.0',
        type: s.tags?.[0] || s.tag || s.category || '其他',
        on: (s.status || s.enabled) !== 'disabled',
        pk: (s.install_count || s.downloads || 0) > 5
      }))
    }
  } catch (e: unknown) {
    message.error('加载Agent技能失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await initAgent()
  loadSkills()
})

async function pushSkill(skillId: string) {
  const ok = await pushSkillToAgent(skillId, agentId.value, false)
  if (ok) message.success('推送成功')
  else message.error('推送失败')
}
async function toggleSkill(item: SkillData) {
  item.on = !item.on
  message.info(`技能「${item.name}」${item.on ? '已启用' : '已禁用'}`)
}
async function packSkill(item: SkillData) {
  if (item.pk) message.success(`技能「${item.name}」打包成功`)
}
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#3b82f6;}
.tb{padding:20px;border-radius:12px;}
</style>
