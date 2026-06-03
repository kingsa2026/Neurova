&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;FolderOpenOutlined :style="{color:'#34d399'}"/&gt; 文件管理&lt;/h2&gt;
      &lt;a-button type="primary" size="small"&gt;&lt;UploadOutlined/&gt;上传文件&lt;/a-button&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;文件&lt;b &gt;{{ stats.count }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;大小&lt;b &gt;{{ stats.size }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;类型&lt;b &gt;{{ stats.types }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table :columns="cols" :data-source="files" row-key="id" size="middle" :pagination="{pageSize:8}"&gt;
        &lt;template #bodyCell="{column,record}"&gt;
          &lt;template v-if="column.key==='type'"&gt;
            &lt;a-tag :color="record.tc" size="small"&gt;{{ record.type }}&lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-if="column.key==='act'"&gt;
            &lt;a-space&gt;
              &lt;a-button type="link" size="small"&gt;预览&lt;/a-button&gt;
              &lt;a-button type="link" size="small"&gt;下载&lt;/a-button&gt;
              &lt;a-popconfirm title="删除?" @confirm="files=files.filter(f=&gt;f.id!==record.id)"&gt;
                &lt;a-button type="link" size="small" danger&gt;删除&lt;/a-button&gt;
              &lt;/a-popconfirm&gt;
            &lt;/a-space&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { FolderOpenOutlined, UploadOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/files', () =&gt; loadData())
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
const files = ref&lt;FileItem[]&gt;([])
const stats = ref({ count: 0, size: '0MB', types: 0 })
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/files`)
    if (res.code === 0 &amp;&amp; res.data) {
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
onMounted(async () =&gt; {
  await initAgent()
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#34d399;}
.tb{padding:20px;border-radius:12px;}
&lt;/style&gt;
&nbsp;