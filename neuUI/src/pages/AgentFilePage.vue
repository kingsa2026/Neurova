<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><FolderOpenOutlined :style="{color:'#34d399'}"/> 文件管理</h2>
      <a-button type="primary" size="small"><UploadOutlined/>上传文件</a-button>
    </div>
    <div class="sr">
      <div class="s glass-effect">文件<b class="c1">{{ stats.count }}</b></div>
      <div class="s glass-effect">大小<b class="c1">{{ stats.size }}</b></div>
      <div class="s glass-effect">类型<b class="c1">{{ stats.types }}</b></div>
    </div>
    <div class="tb glass-effect">
      <a-table :columns="cols" :data-source="files" row-key="id" size="middle" :pagination="{pageSize:8}">
        <template #bodyCell="{column,record}">
          <template v-if="column.key==='type'">
            <a-tag :color="record.tc" size="small">{{ record.type }}</a-tag>
          </template>
          <template v-if="column.key==='act'">
            <a-space>
              <a-button type="link" size="small">预览</a-button>
              <a-button type="link" size="small">下载</a-button>
              <a-popconfirm title="删除?" @confirm="files=files.filter(f=>f.id!==record.id)">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { FolderOpenOutlined, UploadOutlined } from '@ant-design/icons-vue'

const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/files', () => loadData())

const cols = [
  {title:'文件名',dataIndex:'name'},
  {title:'类型',key:'type',width:80},
  {title:'大小',dataIndex:'size',width:100},
  {title:'上传时间',dataIndex:'time',width:160},
  {title:'操作',key:'act',width:200}
]
interface FileItem {
  id: string
  name: string
  type: string
  tc: string
  size: string
  time: string
}
const files = ref<FileItem[]>([])
const stats = ref({ count: 0, size: '0MB', types: 0 })

async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/files`)
    if (res.code === 0 && res.data) {
      if (res.data.files?.length) {
        files.value = res.data.files
        stats.value = {
          count: res.data.files.length,
          size: res.data.total_size || '0MB',
          types: res.data.type_count || 0
        }
      }
    }
  } catch {
    // 使用静态数据作为后备
    files.value = [
      {id:'1',name:'API设计规范.md',type:'MD',tc:'blue',size:'12KB',time:'2026-05-20 14:30'},
      {id:'2',name:'architecture.pdf',type:'PDF',tc:'red',size:'2.4MB',time:'2026-05-19 10:15'},
      {id:'3',name:'data.csv',type:'CSV',tc:'green',size:'845KB',time:'2026-05-18 16:45'},
    ]
    stats.value = { count: 3, size: '3.2MB', types: 3 }
  }
}

onMounted(async () => {
  await initAgent()
  loadData()
})
</script>

<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#34d399;}
.tb{padding:20px;border-radius:12px;}
</style>
