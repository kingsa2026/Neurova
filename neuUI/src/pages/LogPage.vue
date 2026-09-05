<template><div class="pg"><div class="hd glass-effect"><h2 class="t"><FileTextOutlined :style="{color:'#94a3b8'}"/> 日志管理</h2><div class="hsearch"><a-input-search v-model:value="kw" placeholder="搜索日志..." style="width:280px" @search="searchLogs"/></div></div><div class="tb glass-effect"><a-table :columns="cols" :data-source="logs" row-key="id" size="small" :loading="loading" :pagination="{pageSize:12,total:total,current:currentPage,onChange:handlePageChange}"><template #bodyCell="{column,record}"><template v-if="column.key==='lvl'"><a-tag :color="getLevelColor(record.severity)" size="small">{{ record.severity }}</a-tag></template><template v-if="column.key==='msg'"><span :style="{color:record.severity==='ERROR'?'#ef4444':record.severity==='WARNING'?'#fbbf24':'rgba(255,255,255,0.6)'}">{{ record.message }}</span></template></template></a-table></div></div></template>

<script setup lang="ts">import { ref, onMounted } from 'vue';import { FileTextOutlined } from '@ant-design/icons-vue';import { auditAPI, type AuditLogQuery } from '@/api/modules/audit';
import { message } from 'ant-design-vue';

const kw = ref('');
interface LogEntry { id:string;timestamp:string;severity:string;event_type:string;actor_id?:string;message:string }
const logs = ref<LogEntry[]>([]);
const loading = ref(false);
const total = ref(0);
const currentPage = ref(1);

const cols = [
  { title: '时间', dataIndex: 'timestamp', width: 180, customRender: ({ text }: { text: string }) => new Date(text).toLocaleString() },
  { title: '级别', key: 'lvl', width: 80 },
  { title: '事件类型', dataIndex: 'event_type', width: 120 },
  { title: '操作人', dataIndex: 'actor_id', width: 100 },
  { title: '消息', key: 'msg' }
];

const getLevelColor = (level: string) => {
  const colorMap: Record<string, string> = {
    'INFO': 'blue',
    'WARNING': 'orange',
    'ERROR': 'red',
    'CRITICAL': 'purple',
    'DEBUG': 'cyan'
  };
  return colorMap[level] || 'default';
};

const loadLogs = async (params?: AuditLogQuery) => {
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

const searchLogs = () => {
  currentPage.value = 1;
  if (kw.value) {
    // 使用actor_id字段进行简单搜索
    loadLogs({ actor_id: kw.value });
  } else {
    loadLogs();
  }
};

const handlePageChange = (page: number) => {
  currentPage.value = page;
  loadLogs();
};

onMounted(() => {
  loadLogs();
});
</script>

<style scoped>.pg{display:flex;flex-direction:column;gap:14px;}.hd{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-radius:12px;}.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}.tb{padding:20px;border-radius:12px;}</style>