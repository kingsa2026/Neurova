&lt;template&gt;&lt;div &gt;&lt;div &gt;&lt;h2 &gt;&lt;ThunderboltOutlined :style="{color:'#3b82f6'}"/&gt; Agent 技能&lt;/h2&gt;&lt;a-button type="primary" size="small"&gt;打包可打包技能&lt;/a-button&gt;&lt;/div&gt;&lt;div &gt;&lt;div &gt;已安装&lt;b &gt;{{ data.length }}&lt;/b&gt;&lt;/div&gt;&lt;div &gt;启用&lt;b style="color:#34d399"&gt;{{ data.filter(d=&gt;d.on).length }}&lt;/b&gt;&lt;/div&gt;&lt;div &gt;可打包&lt;b style="color:#fbbf24"&gt;{{ data.filter(d=&gt;d.pk).length }}&lt;/b&gt;&lt;/div&gt;&lt;/div&gt;&lt;div &gt;&lt;a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="false"&gt;&lt;template #bodyCell="{column,record}"&gt;&lt;template v-if="column.key==='st'"&gt;&lt;a-switch v-model:checked="record.on" size="small" @change="toggleSkill(record)"/&gt;&lt;/template&gt;&lt;template v-if="column.key==='act'"&gt;&lt;a-space&gt;&lt;a-button type="link" size="small" :disabled="!record.pk" @click="packSkill(record)"&gt;打包&lt;/a-button&gt;&lt;a-button type="link" size="small" @click="pushSkill(record.id)"&gt;推送&lt;/a-button&gt;&lt;a-popconfirm title="卸载?" @confirm="data=data.filter(d=&gt;d.id!==record.id)"&gt;&lt;a-button type="link" size="small" danger&gt;卸载&lt;/a-button&gt;&lt;/a-popconfirm&gt;&lt;/a-space&gt;&lt;/template&gt;&lt;/template&gt;&lt;/a-table&gt;&lt;/div&gt;&lt;/div&gt;&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { listPrivateSkills, pushSkillToAgent } from '@/api/modules/skill'
import { useAgentPage } from '@/composables/useAgentPage'
import { ThunderboltOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/skills', () =&gt; loadSkills())
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
const data = ref&lt;SkillData[]&gt;([])
const loading = ref(false)
async function loadSkills() {
  loading.value = true
  try {
    const skills = await listPrivateSkills()
    if (skills?.length) {
      data.value = skills.map((s: Record&lt;string, unknown&gt;) =&gt; ({
        id: s.id || s.skill_id,
        name: s.name || s.title || '',
        ver: s.version || '1.0',
        type: s.tags?.[0] || s.tag || s.category || '其他',
        on: (s.status || s.enabled) !== 'disabled',
        pk: (s.install_count || s.downloads || 0) &gt; 5
      }))
    }
  } catch (e: unknown) {
    message.error('加载Agent技能失败')
  } finally {
    loading.value = false
  }
}
onMounted(async () =&gt; {
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
&lt;/script&gt;
&lt;style scoped&gt;
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#3b82f6;}
.tb{padding:20px;border-radius:12px;}
&lt;/style&gt;
&nbsp;