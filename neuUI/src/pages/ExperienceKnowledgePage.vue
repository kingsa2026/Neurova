<template>
  <div class="exp-page">
    <div class="page-hd glass-effect">
      <h2 class="page-tit"><BulbOutlined :style="{color:'#f59e0b'}" /> 经验知识库</h2>
      <a-tag>Agent: {{ agentId }}</a-tag>
    </div>
    <div class="stat-row">
      <div class="stat glass-effect">经验记录<b class="c-orange">{{ stats.count }}</b></div>
      <div class="stat glass-effect">最佳实践<b class="c-orange">{{ stats.bestPractices }}</b></div>
      <div class="stat glass-effect">技能排名<b class="c-orange">{{ stats.topRank }}</b></div>
    </div>
    <div class="card glass-effect">
      <a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="{pageSize:5}">
        <template #bodyCell="{column,record}">
          <template v-if="column.key==='type'"><a-tag :color="record.tc">{{ record.type }}</a-tag></template>
          <template v-if="column.key==='score'"><span :style="{color:record.sc>7?'#34d399':record.sc>4?'#fbbf24':'#ef4444'}"><StarFilled /> {{ record.sc }}/10</span></template>
          <template v-if="column.key==='act'"><a-button type="link" size="small" @click="msg.info(record.desc)">详情</a-button></template>
        </template>
      </a-table>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { BulbOutlined, StarFilled } from '@ant-design/icons-vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/experience-knowledge', () => loadData())

const msg = message
const cols = [
  { title: '经验ID', dataIndex: 'id', width: 100 },
  { title: '标题', dataIndex: 'title' },
  { title: '类型', key: 'type', width: 100 },
  { title: '评分', key: 'score', width: 100 },
  { title: '操作', key: 'act', width: 100 }
]
interface ExperienceItem {
  id: string
  title: string
  type: string
  tc: string
  sc: number
  desc: string
}
const data = ref<ExperienceItem[]>([])
const stats = ref({ count: 0, bestPractices: 0, topRank: '--' })
const loading = ref(false)

async function loadData() {
  loading.value = true
  try {
    const res = await request.get(`/agents/${agentId.value}/experience/list`)
    if (res.code === 0 && res.data) {
      const items = res.data.experiences || res.data || []
      data.value = items.map((e: Record<string, unknown>) => ({
        id: (e.id || e.experience_id) as string,
        title: (e.title || e.name || '') as string,
        type: (e.type || e.category || '经验') as string,
        tc: e.type === '检索优化' ? 'blue' : e.type === '对话策略' ? 'purple' : e.type === '技能优化' ? 'cyan' : e.type === '模型微调' ? 'green' : 'orange',
        sc: Math.min(10, Math.round(((e.score || e.rating || 5) as number) * 1)),
        desc: (e.description || e.desc || e.content || '') as string,
      }))
      stats.value = {
        count: res.data.total || data.value.length,
        bestPractices: res.data.best_practices || data.value.filter((d: ExperienceItem) => d.sc >= 8).length,
        topRank: res.data.top_rank || 'Top5',
      }
    }
  } catch { /* keep empty */ }
  finally { loading.value = false }
}

onMounted(async () => {
  await initAgent()
  loadData()
})
</script>
<style scoped>
.exp-page{display:flex;flex-direction:column;gap:16px;}
.page-hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.page-tit{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.stat-row{display:flex;gap:12px;}
.stat{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:0.85rem;}
.stat b{font-size:1.4rem;}
.c-orange{color:#f59e0b;}
.card{padding:20px;border-radius:12px;}
</style>
