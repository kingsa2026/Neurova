&lt;template&gt;&lt;div &gt;&lt;div &gt;&lt;h2 &gt;&lt;FileTextOutlined :style="{color:'#94a3b8'}"/&gt; 日志管理&lt;/h2&gt;&lt;div &gt;&lt;a-input-search v-model:value="kw" placeholder="搜索日志..." style="width:280px" @search="searchLogs"/&gt;&lt;/div&gt;&lt;/div&gt;&lt;div &gt;&lt;a-table :columns="cols" :data-source="logs" row-key="id" size="small" :loading="loading" :pagination="{pageSize:12,total:total,current:currentPage,onChange:handlePageChange}"&gt;&lt;template #bodyCell="{column,record}"&gt;&lt;template v-if="column.key==='lvl'"&gt;&lt;a-tag :color="getLevelColor(record.severity)" size="small"&gt;{{ record.severity }}&lt;/a-tag&gt;&lt;/template&gt;&lt;template v-if="column.key==='msg'"&gt;&lt;span :style="{color:record.severity==='ERROR'?'#ef4444':record.severity==='WARNING'?'#fbbf24':'rgba(255,255,255,0.6)'}"&gt;{{ record.message }}&lt;/span&gt;&lt;/template&gt;&lt;/template&gt;&lt;/a-table&gt;&lt;/div&gt;&lt;/div&gt;&lt;/template&gt;
&lt;script setup lang="ts"&gt;import { ref, onMounted } from 'vue';import { FileTextOutlined } from '@ant-design/icons-vue';import { auditAPI, type AuditLogQuery } from '@/api/modules/audit';
import { message } from 'ant-design-vue';
const kw = ref('');
interface LogEntry { id:string;timestamp:string;severity:string;event_type:string;actor_id?:string;message:string }
const logs = ref&lt;LogEntry[]&gt;([]);
const loading = ref(false);
const total = ref(0);
const currentPage = ref(1);
const cols = [
  { title: '时间', dataIndex: 'timestamp', width: 180, customRender: ({ text }: { text: string }) =&gt; new Date(text).toLocaleString() },
  { title: '级别', key: 'lvl', width: 80 },
  { title: '事件类型', dataIndex: 'event_type', width: 120 },
  { title: '操作人', dataIndex: 'actor_id', width: 100 },
  { title: '消息', key: 'msg' }
];
const getLevelColor = (level: string) =&gt; {
  const colorMap: Record&lt;string, string&gt; = {
    'INFO': 'blue',
    'WARNING': 'orange',
    'ERROR': 'red',
    'CRITICAL': 'purple',
    'DEBUG': 'cyan'
  };
  return colorMap[level] || 'default';
};
const loadLogs = async (params?: AuditLogQuery) =&gt; {
  loading.value = true;
  try {
    const res = await auditAPI.getLogs({ page: currentPage.value, page_size: 12, ...params });
    if (res.data) {
      logs.value = res.data.items || res.data.logs || [];
      total.value = res.data.total || 0;
    }
  } catch (err) {
    console.error('加载日志失败:', err);
    message.error('加载日志失败');
  } finally {
    loading.value = false;
  }
};
const searchLogs = () =&gt; {
  currentPage.value = 1;
  if (kw.value) {
    // 使用actor_id字段进行简单搜索
    loadLogs({ actor_id: kw.value });
  } else {
    loadLogs();
  }
};
const handlePageChange = (page: number) =&gt; {
  currentPage.value = page;
  loadLogs();
};
onMounted(() =&gt; {
  loadLogs();
});
&lt;/script&gt;
&lt;style scoped&gt;.pg{display:flex;flex-direction:column;gap:14px;}.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}.tb{padding:20px;border-radius:12px;}&lt;/style&gt;