&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;RobotOutlined /&gt; Agent 管理&lt;/h2&gt;
      &lt;a-button type="primary" @click="$router.push('/agents/create')"&gt;&lt;PlusOutlined /&gt; 创建 Agent&lt;/a-button&gt;
    &lt;/div&gt;
    &lt;!-- 视图切换 --&gt;
    &lt;div &gt;
      &lt;a-input-search v-model:value="kw" placeholder="搜索 Agent..." allow-clear style="width:280px" /&gt;
      &lt;a-radio-group v-model:value="view" button-style="solid" size="small"&gt;
        &lt;a-radio-button value="card"&gt;&lt;AppstoreOutlined /&gt; 卡片&lt;/a-radio-button&gt;
        &lt;a-radio-button value="table"&gt;&lt;UnorderedListOutlined /&gt; 表格&lt;/a-radio-button&gt;
      &lt;/a-radio-group&gt;
    &lt;/div&gt;
    &lt;!-- 卡片视图 --&gt;
    &lt;div v-if="view==='card'" &gt;
      &lt;div v-for="a in filteredAgents" :key="a.agentId" &gt;
        &lt;div  @click="$router.push(`/agents/${a.agentId}`)"&gt;
          &lt;a-avatar :size="48" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}"&gt;{{ a.name[0] }}&lt;/a-avatar&gt;
          &lt;div &gt;
            &lt;h3&gt;{{ a.name }}&lt;/h3&gt;
            &lt;a-tag :color="a.status==='active'?'green':'default'"&gt;{{ a.status||'active' }}&lt;/a-tag&gt;
          &lt;/div&gt;
        &lt;/div&gt;
        &lt;p  @click="$router.push(`/agents/${a.agentId}`)"&gt;{{ a.description || '暂无描述' }}&lt;/p&gt;
        &lt;div  @click="$router.push(`/agents/${a.agentId}`)"&gt;
          &lt;span&gt;&lt;DatabaseOutlined /&gt; {{ a.memoryCount || 0 }}&lt;/span&gt;
          &lt;span&gt;&lt;ThunderboltOutlined /&gt; {{ a.skillCount || 0 }}&lt;/span&gt;
          &lt;span&gt;{{ a.llmModel || '-' }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;a-button size="small" @click.stop="$router.push(`/agents/${a.agentId}`)"&gt;编辑&lt;/a-button&gt;
          &lt;a-popconfirm title="确定删除?" @confirm="del(a.agentId)" @click.stop&gt;
            &lt;a-button size="small" danger&gt;删除&lt;/a-button&gt;
          &lt;/a-popconfirm&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div v-if="filteredAgents.length===0" &gt;暂无 Agent，点击上方按钮创建&lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 表格视图 --&gt;
    &lt;div v-else &gt;
      &lt;a-table :columns="cols" :data-source="filteredAgents" :row-key="record =&gt; record.agentId" size="middle" :pagination="false"&gt;
        &lt;template #bodyCell="{column,record}"&gt;
          &lt;template v-if="column.key==='name'"&gt;&lt;a @click="$router.push(`/agents/${record.agentId}`)"&gt;{{ record.name }}&lt;/a&gt;&lt;/template&gt;
          &lt;template v-if="column.key==='status'"&gt;&lt;a-tag :color="record.status==='active'?'green':'default'"&gt;{{ record.status||'active' }}&lt;/a-tag&gt;&lt;/template&gt;
          &lt;template v-if="column.key==='actions'"&gt;
            &lt;a-button type="link" size="small" @click="$router.push(`/agents/${record.agentId}`)"&gt;编辑&lt;/a-button&gt;
            &lt;a-popconfirm title="删除?" @confirm="del(record.agentId)"&gt;&lt;a-button type="link" size="small" danger&gt;删除&lt;/a-button&gt;&lt;/a-popconfirm&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import { RobotOutlined, PlusOutlined, AppstoreOutlined, UnorderedListOutlined, DatabaseOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
const agentStore = useAgentStore()
const view = ref('card')
const kw = ref('')
const filteredAgents = computed(() =&gt; {
  if (!kw.value) return agentStore.agents
  return agentStore.agents.filter(a =&gt; a.name.includes(kw.value) || (a.agentId &amp;&amp; a.agentId.includes(kw.value)))
})
const cols = [
  { title:'名称',key:'name',dataIndex:'name' },
  { title:'模型',dataIndex:'llmModel' },
  { title:'状态',key:'status',dataIndex:'status' },
  { title:'记忆',dataIndex:'memoryCount' },
  { title:'技能',dataIndex:'skillCount' },
  { title:'操作',key:'actions',width:160 },
]
async function del(id:string){ const ok=await agentStore.deleteAgent(id); if(ok) message.success('已删除') }
// 每次进入列表页都重新加载，确保数据最新
onMounted(async ()=&gt;{ await agentStore.loadAgents() })
&lt;/script&gt;
&lt;style scoped&gt;
.agent-list-page { display:flex;flex-direction:column;gap:16px; }
.page-header { display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-radius:12px; }
.page-title { font-size:1.25rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px; }
.toolbar { display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-radius:10px; }
.card-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px; }
.agent-card { padding:20px;border-radius:12px;cursor:pointer; }
.card-top { display:flex;align-items:center;gap:12px;margin-bottom:12px; }
.card-meta h3 { color:#e2e8f0;margin:0 0 4px;font-size:1rem; }
.card-desc { color:rgba(255,255,255,0.45);font-size:0.85rem;margin:0 0 12px; }
.card-stats { display:flex;gap:16px;color:rgba(255,255,255,0.35);font-size:0.8rem; }
.empty-state { grid-column:1/-1;text-align:center;padding:64px 0;color:rgba(255,255,255,0.3); }
.card-actions { display:flex;gap:8px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.05);justify-content:flex-end; }
&lt;/style&gt;
&nbsp;