<template>
  <div >
    <div >
      <h2 ><ShopOutlined /> 技能市场</h2>
      <a-button type="primary" @click="$router.push('/skill-pool')"><AppstoreOutlined /> 技能池</a-button>
    </div>
    <div >
      <a-input-search v-model:value="kw" placeholder="搜索技能..." style="width:300px" />
      <div >
        <a-tag v-for="t in allTags" :key="t" :color="selTag===t?'blue':undefined" style="cursor:pointer" @click="selTag=selTag===t?'':t">{{ t }}</a-tag>
      </div>
    </div>
    <div  v-if="filtered.length">
      <div v-for="s in filtered" :key="s.id"  @click="openDetail(s)">
        <div >
          <div  :style="{background: colorFor(s.tag)}">{{ s.name[0] }}</div>
          <div >
            <h4>{{ s.name }}</h4>
            <span >v{{ s.version }}</span>
          </div>
        </div>
        <p >{{ s.desc }}</p>
        <div >
          <span><StarFilled  /> {{ s.rating }}</span>
          <span><DownloadOutlined /> {{ s.downloads }}</span>
          <a-button size="small" type="primary" @click.stop="install(s)">安装</a-button>
        </div>
      </div>
    </div>
    <div v-else  style="text-align:center;padding:64px 0;color:rgba(255,255,255,0.3)">暂无匹配技能</div>
    <a-drawer v-model:open="detailOpen" title="技能详情" placement="right" :width="420">
      <template v-if="detailSkill">
        <div >
          <div  :style="{background: colorFor(detailSkill.tag)}">{{ detailSkill.name[0] }}</div>
          <h3>{{ detailSkill.name }}</h3>
          <a-tag>{{ detailSkill.tag }}</a-tag>
        </div>
        <p >{{ detailSkill.desc }}</p>
        <div >
          <span><StarFilled  /> {{ detailSkill.rating }} 分</span>
          <span><DownloadOutlined /> {{ detailSkill.downloads }} 次安装</span>
        </div>
        <a-divider />
        <a-button type="primary" block @click="install(detailSkill!)">安装到当前 Agent</a-button>
      </template>
    </a-drawer>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import { listPublicSkills, installPublicSkill } from '@/api/modules/skill'
import { ShopOutlined, AppstoreOutlined, StarFilled, DownloadOutlined } from '@ant-design/icons-vue'
const agentStore = useAgentStore()
const kw = ref('')
const selTag = ref('')
const detailOpen = ref(false)
const detailSkill = ref<Skill|null>(null)
const allTags = ['对话','搜索','文档','代码','分析','图像']
interface Skill { id:string;name:string;desc:string;version:string;tag:string;rating:number;downloads:number }
const skills = ref<Skill[]>([])
const loading = ref(false)
const errorMsg = ref('')
// 从 API 加载公共技能
onMounted(async () => {
  loading.value = true
  try {
    const data = await listPublicSkills()
    if (data?.length) {
      const allKnownTags = new Set(allTags)
      skills.value = data.map((s: Record<string,unknown>) => {
        const tag = s.tags?.[0] || s.tag || s.category || s.type || '其他'
        if (tag && !allKnownTags.has(tag)) allTags.push(tag)
        return {
          id: s.id || s.skill_id,
          name: s.name || s.title || '',
          desc: s.description || s.desc || '',
          version: s.version || '1.0',
          tag,
          rating: s.rating || s.score || 4.0,
          downloads: s.downloads || s.install_count || 0,
        }
      })
    }
  } catch (e: unknown) {
    const err = e as {message?:string}
    errorMsg.value = err?.message || '加载技能市场失败'
  } finally { loading.value = false }
})
const filtered = computed(() => skills.value.filter(s => (!kw.value||s.name.includes(kw.value)) && (!selTag.value||s.tag===selTag.value)))
function colorFor(tag: string) {
  const colors: Record<string,string> = { '对话':'#3b82f6','搜索':'#8b5cf6','文档':'#10b981','代码':'#f59e0b','分析':'#ef4444','图像':'#06b6d4' }
  return colors[tag] || '#60a5fa'
}
function openDetail(s: Skill) { detailSkill.value = s; detailOpen.value = true }
async function install(s: Skill) {
  const targetAgentId = agentStore.currentAgentId || agentStore.agents[0]?.id || 'default'
  const ok = await installPublicSkill(s.id, targetAgentId)
  if (ok) message.success(`技能「${s.name}」安装成功`)
  else message.error(`技能「${s.name}」安装失败`)
}
</script>
<style scoped>
.skill-page { display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px; }
.search-bar { display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:10px;flex-wrap:wrap; }
.tag-filters { display:flex;gap:6px; }
.skill-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px; }
.skill-card { padding:20px;border-radius:12px;cursor:pointer; }
.skill-top { display:flex;align-items:center;gap:12px;margin-bottom:10px; }
.skill-avatar { width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700; }
.skill-meta h4 { color:#e2e8f0;margin:0; }
.skill-ver { color:rgba(255,255,255,0.3);font-size:0.75rem; }
.skill-desc { color:rgba(255,255,255,0.45);font-size:0.85rem;margin:0 0 12px; }
.skill-bottom { display:flex;align-items:center;gap:16px;color:rgba(255,255,255,0.35);font-size:0.8rem; }
.star { color:#fbbf24; }
.detail-header { text-align:center;margin-bottom:16px; }
.detail-avatar { width:56px;height:56px;border-radius:14px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.5rem;font-weight:700;margin:0 auto 12px; }
.detail-desc { color:rgba(255,255,255,0.5); }
.detail-stats { display:flex;gap:24px;color:rgba(255,255,255,0.4);margin:16px 0; }
</style>
 