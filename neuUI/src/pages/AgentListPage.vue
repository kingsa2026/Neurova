<template>
  <div class="agent-list-page">
    <div class="page-header glass-effect">
      <h2 class="page-title"><RobotOutlined /> Agent 管理</h2>
      <a-button type="primary" @click="$router.push('/agents/create')"><PlusOutlined /> 创建 Agent</a-button>
    </div>

    <!-- 视图切换 -->
    <div class="toolbar glass-effect">
      <a-input-search v-model:value="kw" placeholder="搜索 Agent..." allow-clear style="width:280px" />
      <a-radio-group v-model:value="view" button-style="solid" size="small">
        <a-radio-button value="card"><AppstoreOutlined /> 卡片</a-radio-button>
        <a-radio-button value="table"><UnorderedListOutlined /> 表格</a-radio-button>
      </a-radio-group>
    </div>

    <!-- 卡片视图 -->
    <div v-if="view==='card'" class="card-grid">
      <div v-for="a in filteredAgents" :key="a.agentId" class="agent-card glass-effect card-hover">
        <div class="card-top" @click="$router.push(`/agents/${a.agentId}`)">
          <a-avatar :size="48" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}">{{ a.name[0] }}</a-avatar>
          <div class="card-meta">
            <h3>{{ a.name }}</h3>
            <a-tag :color="a.status==='active'?'green':'default'">{{ a.status||'active' }}</a-tag>
          </div>
        </div>
        <p class="card-desc" @click="$router.push(`/agents/${a.agentId}`)">{{ a.description || '暂无描述' }}</p>
        <div class="card-stats" @click="$router.push(`/agents/${a.agentId}`)">
          <span><DatabaseOutlined /> {{ a.memoryCount || 0 }}</span>
          <span><ThunderboltOutlined /> {{ a.skillCount || 0 }}</span>
          <span>{{ a.llmModel || '-' }}</span>
        </div>
        <div class="card-actions">
          <a-button size="small" @click.stop="$router.push(`/agents/${a.agentId}`)">编辑</a-button>
          <a-popconfirm title="确定删除?" @confirm="del(a.agentId)" @click.stop>
            <a-button size="small" danger>删除</a-button>
          </a-popconfirm>
        </div>
      </div>
      <div v-if="filteredAgents.length===0" class="empty-state">暂无 Agent，点击上方按钮创建</div>
    </div>

    <!-- 表格视图 -->
    <div v-else class="glass-effect">
      <a-table :columns="cols" :data-source="filteredAgents" :row-key="record => record.agentId" size="middle" :pagination="false">
        <template #bodyCell="{column,record}">
          <template v-if="column.key==='name'"><a @click="$router.push(`/agents/${record.agentId}`)">{{ record.name }}</a></template>
          <template v-if="column.key==='status'"><a-tag :color="record.status==='active'?'green':'default'">{{ record.status||'active' }}</a-tag></template>
          <template v-if="column.key==='actions'">
            <a-button type="link" size="small" @click="$router.push(`/agents/${record.agentId}`)">编辑</a-button>
            <a-popconfirm title="删除?" @confirm="del(record.agentId)"><a-button type="link" size="small" danger>删除</a-button></a-popconfirm>
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useAgentStore } from '@/stores/agents'
import { RobotOutlined, PlusOutlined, AppstoreOutlined, UnorderedListOutlined, DatabaseOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'

const agentStore = useAgentStore()
const view = ref('card')
const kw = ref('')

const filteredAgents = computed(() => {
  if (!kw.value) return agentStore.agents
  return agentStore.agents.filter(a => a.name.includes(kw.value) || (a.agentId && a.agentId.includes(kw.value)))
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
onMounted(async ()=>{ await agentStore.loadAgents() })
</script>

<style scoped>
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
</style>
