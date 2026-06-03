&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;BulbOutlined :style="{color:'#f59e0b'}" /&gt; 经验知识库&lt;/h2&gt;
      &lt;a-tag&gt;Agent: {{ agentId }}&lt;/a-tag&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;经验记录&lt;b &gt;{{ stats.count }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;最佳实践&lt;b &gt;{{ stats.bestPractices }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;技能排名&lt;b &gt;{{ stats.topRank }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="data" row-key="id" size="middle" :pagination="{pageSize:5}"&gt;
        &lt;template #bodyCell="{column,record}"&gt;
          &lt;template v-if="column.key==='type'"&gt;&lt;a-tag :color="record.tc"&gt;{{ record.type }}&lt;/a-tag&gt;&lt;/template&gt;
          &lt;template v-if="column.key==='score'"&gt;&lt;span :style="{color:record.sc&gt;7?'#34d399':record.sc&gt;4?'#fbbf24':'#ef4444'}"&gt;&lt;StarFilled /&gt; {{ record.sc }}/10&lt;/span&gt;&lt;/template&gt;
          &lt;template v-if="column.key==='act'"&gt;&lt;a-button type="link" size="small" @click="msg.info(record.desc)"&gt;详情&lt;/a-button&gt;&lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { BulbOutlined, StarFilled } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/experience-knowledge', () =&gt; loadData())
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
const data = ref&lt;ExperienceItem[]&gt;([])
const stats = ref({ count: 0, bestPractices: 0, topRank: '--' })
const loading = ref(false)
async function loadData() {
  loading.value = true
  try {
    const res = await request.get(`/agents/${agentId.value}/experience/list`)
    if (res.code === 0 &amp;&amp; res.data) {
      const items = res.data.experiences || res.data || []
      data.value = items.map((e: Record&lt;string, unknown&gt;) =&gt; ({
        id: (e.id || e.experience_id) as string,
        title: (e.title || e.name || '') as string,
        type: (e.type || e.category || '经验') as string,
        tc: e.type === '检索优化' ? 'blue' : e.type === '对话策略' ? 'purple' : e.type === '技能优化' ? 'cyan' : e.type === '模型微调' ? 'green' : 'orange',
        sc: Math.min(10, Math.round(((e.score || e.rating || 5) as number) * 1)),
        desc: (e.description || e.desc || e.content || '') as string,
      }))
      stats.value = {
        count: res.data.total || data.value.length,
        bestPractices: res.data.best_practices || data.value.filter((d: ExperienceItem) =&gt; d.sc &gt;= 8).length,
        topRank: res.data.top_rank || 'Top5',
      }
    }
  } catch { /* keep empty */ }
  finally { loading.value = false }
}
onMounted(async () =&gt; {
  await initAgent()
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.exp-page{display:flex;flex-direction:column;gap:16px;}
.page-hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.page-tit{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.stat-row{display:flex;gap:12px;}
.stat{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:0.85rem;}
.stat b{font-size:1.4rem;}
.c-orange{color:#f59e0b;}
.card{padding:20px;border-radius:12px;}
&lt;/style&gt;
&nbsp;