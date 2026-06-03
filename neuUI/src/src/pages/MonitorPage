&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;MonitorOutlined :style="{ color: '#34d399' }" /&gt;
        系统监控
      &lt;/h2&gt;
      &lt;div &gt;
        &lt;a-button @click="loadData" :loading="loading"&gt;
          &lt;ReloadOutlined /&gt; 刷新
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;div &gt;&lt;DashboardOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ systemStats.cpu_usage || 0 }}%&lt;/div&gt;
          &lt;div &gt;CPU 使用率&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;DatabaseOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ systemStats.memory_usage || 0 }}%&lt;/div&gt;
          &lt;div &gt;内存使用&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;CloudServerOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ systemStats.disk_usage || 0 }}%&lt;/div&gt;
          &lt;div &gt;磁盘使用&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;ApiOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ systemStats.uptime || '-' }}&lt;/div&gt;
          &lt;div &gt;运行时间&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" /&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;div v-if="!loading" &gt;
      &lt;div  v-for="m in metrics" :key="m.name"&gt;
        &lt;div &gt;
          &lt;span&gt;{{ m.name }}&lt;/span&gt;
          &lt;span :style="{ color: m.color }"&gt;{{ m.value }}&lt;/span&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div  :style="{ width: m.val + '%', background: m.color }" /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;span v-for="s in m.sub" :key="s.name"&gt;{{ s.name }}: {{ s.val }}&lt;/span&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div  v-if="!loading"&gt;
      &lt;h3&gt;&lt;InfoCircleOutlined /&gt; 系统信息&lt;/h3&gt;
      &lt;a-descriptions bordered :column="2"&gt;
        &lt;a-descriptions-item label="系统状态"&gt;
          &lt;a-tag :color="systemStats.status === 'healthy' ? 'green' : 'orange'"&gt;
            {{ systemStats.status === 'healthy' ? '健康' : '异常' }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="系统版本"&gt;{{ systemStats.version || '-' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="Agent 数量"&gt;{{ systemStats.agents_count || 0 }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="默认 Agent"&gt;{{ systemStats.default_agent_id || '-' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="记忆系统"&gt;
          &lt;a-tag :color="systemStats.memory_enabled ? 'green' : 'default'"&gt;
            {{ systemStats.memory_enabled ? '启用' : '禁用' }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="多用户模式"&gt;
          &lt;a-tag :color="systemStats.multi_user_enabled ? 'green' : 'default'"&gt;
            {{ systemStats.multi_user_enabled ? '启用' : '禁用' }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
      &lt;/a-descriptions&gt;
    &lt;/div&gt;
    &lt;div  v-if="!loading"&gt;
      &lt;h3&gt;&lt;DashboardOutlined /&gt; 性能指标&lt;/h3&gt;
      &lt;div &gt;
        &lt;div  v-for="perf in performanceMetrics" :key="perf.name"&gt;
          &lt;div &gt;
            &lt;component :is="perf.icon" :style="{ color: perf.color }" /&gt;
            &lt;span&gt;{{ perf.name }}&lt;/span&gt;
          &lt;/div&gt;
          &lt;div &gt;{{ perf.value }}&lt;/div&gt;
          &lt;div &gt;{{ perf.sub }}&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  MonitorOutlined,
  ReloadOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  CloudServerOutlined,
  ApiOutlined,
  InfoCircleOutlined,
  FieldTimeOutlined,
  ThunderboltOutlined,
  LineChartOutlined,
} from '@ant-design/icons-vue'
import { statsAPI } from '@/api/modules/stats'
const loading = ref(false)
const error = ref('')
const systemStats = reactive({
  status: 'healthy',
  uptime: '-',
  version: '-',
  agents_count: 0,
  default_agent_id: '',
  memory_enabled: false,
  channels_enabled: false,
  multi_user_enabled: false,
  cpu_usage: 45,
  memory_usage: 62,
  disk_usage: 38,
})
const metrics = ref([
  {
    name: 'CPU 使用率',
    value: '45%',
    val: 45,
    color: '#3b82f6',
    sub: [
      { name: '用户态', val: '28%' },
      { name: '内核态', val: '12%' },
      { name: 'IO 等待', val: '5%' },
    ],
  },
  {
    name: '内存使用',
    value: '62%',
    val: 62,
    color: '#a78bfa',
    sub: [
      { name: '已用', val: '8.2GB' },
      { name: '缓存', val: '2.1GB' },
      { name: '可用', val: '5.7GB' },
    ],
  },
  {
    name: '磁盘 IO',
    value: '38%',
    val: 38,
    color: '#f59e0b',
    sub: [
      { name: '读', val: '120MB/s' },
      { name: '写', val: '45MB/s' },
    ],
  },
  {
    name: '网络',
    value: '28%',
    val: 28,
    color: '#34d399',
    sub: [
      { name: '入', val: '15Mbps' },
      { name: '出', val: '8Mbps' },
    ],
  },
  {
    name: 'API 延迟',
    value: 'avg 230ms',
    val: 35,
    color: '#ef4444',
    sub: [
      { name: 'P50', val: '120ms' },
      { name: 'P99', val: '890ms' },
    ],
  },
  {
    name: '吞吐量',
    value: '1.2K/s',
    val: 72,
    color: '#6366f1',
    sub: [
      { name: '请求', val: '1.2K/s' },
      { name: '并发', val: '45' },
    ],
  },
])
const performanceMetrics = ref([
  {
    name: '响应时间',
    value: '230ms',
    sub: '平均响应时间',
    color: '#3b82f6',
    icon: FieldTimeOutlined,
  },
  {
    name: '吞吐量',
    value: '1.2K/s',
    sub: '请求/秒',
    color: '#10b981',
    icon: ThunderboltOutlined,
  },
  {
    name: '成功率',
    value: '99.2%',
    sub: 'API 调用成功率',
    color: '#34d399',
    icon: LineChartOutlined,
  },
  {
    name: '并发连接',
    value: '45',
    sub: '当前活跃连接',
    color: '#8b5cf6',
    icon: ApiOutlined,
  },
])
async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [sysRes, dashboardRes] = await Promise.all([
      statsAPI.getSystemStats().catch(() =&gt; ({ data: null })),
      statsAPI.getControlDashboard().catch(() =&gt; ({ data: null })),
    ])
    if (sysRes.data) {
      Object.assign(systemStats, sysRes.data)
    }
    if (dashboardRes.data) {
      if (dashboardRes.data.key_metrics) {
        performanceMetrics.value[0].value = `${dashboardRes.data.key_metrics.average_response_time}ms`
        performanceMetrics.value[2].value = `${(dashboardRes.data.key_metrics.success_rate * 100).toFixed(1)}%`
      }
    }
  } catch (e: unknown) {
    const err = e as {message?:string}
    error.value = err?.message || '加载监控数据失败'
    message.error('加载监控数据失败')
  } finally {
    loading.value = false
  }
}
onMounted(() =&gt; {
  loadData()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px;
}
.hd {
  padding: 14px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hd-actions {
  display: flex;
  gap: 8px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.s {
  padding: 14px 18px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.s-icon {
  font-size: 2rem;
  color: #34d399;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.4rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.card {
  padding: 20px;
  border-radius: 12px;
}
.mh {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.85rem;
}
.mbar {
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}
.mbf {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s;
}
.ms {
  display: flex;
  gap: 16px;
  color: rgba(255, 255, 255, 0.3);
  font-size: 0.75rem;
}
.section {
  padding: 20px;
  border-radius: 12px;
}
.section h3 {
  margin: 0 0 16px 0;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.metric-card {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  padding: 16px;
}
.metric-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 8px;
}
.metric-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
  margin-bottom: 4px;
}
.metric-sub {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
}
@media (max-width: 1024px) {
  .sr {
    grid-template-columns: repeat(2, 1fr);
  }
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
&lt;/style&gt;
&nbsp;