<template>
  <div >
    <div >
      <h2 >
        <MonitorOutlined :style="{ color: '#34d399' }" />
        系统监控
      </h2>
      <div >
        <a-button @click="loadData" :loading="loading">
          <ReloadOutlined /> 刷新
        </a-button>
      </div>
    </div>
    <div >
      <div >
        <div ><DashboardOutlined /></div>
        <div >
          <div >{{ systemStats.cpu_usage || 0 }}%</div>
          <div >CPU 使用率</div>
        </div>
      </div>
      <div >
        <div ><DatabaseOutlined /></div>
        <div >
          <div >{{ systemStats.memory_usage || 0 }}%</div>
          <div >内存使用</div>
        </div>
      </div>
      <div >
        <div ><CloudServerOutlined /></div>
        <div >
          <div >{{ systemStats.disk_usage || 0 }}%</div>
          <div >磁盘使用</div>
        </div>
      </div>
      <div >
        <div ><ApiOutlined /></div>
        <div >
          <div >{{ systemStats.uptime || '-' }}</div>
          <div >运行时间</div>
        </div>
      </div>
    </div>
    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <div v-if="!loading" >
      <div  v-for="m in metrics" :key="m.name">
        <div >
          <span>{{ m.name }}</span>
          <span :style="{ color: m.color }">{{ m.value }}</span>
        </div>
        <div >
          <div  :style="{ width: m.val + '%', background: m.color }" />
        </div>
        <div >
          <span v-for="s in m.sub" :key="s.name">{{ s.name }}: {{ s.val }}</span>
        </div>
      </div>
    </div>
    <div  v-if="!loading">
      <h3><InfoCircleOutlined /> 系统信息</h3>
      <a-descriptions bordered :column="2">
        <a-descriptions-item label="系统状态">
          <a-tag :color="systemStats.status === 'healthy' ? 'green' : 'orange'">
            {{ systemStats.status === 'healthy' ? '健康' : '异常' }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="系统版本">{{ systemStats.version || '-' }}</a-descriptions-item>
        <a-descriptions-item label="Agent 数量">{{ systemStats.agents_count || 0 }}</a-descriptions-item>
        <a-descriptions-item label="默认 Agent">{{ systemStats.default_agent_id || '-' }}</a-descriptions-item>
        <a-descriptions-item label="记忆系统">
          <a-tag :color="systemStats.memory_enabled ? 'green' : 'default'">
            {{ systemStats.memory_enabled ? '启用' : '禁用' }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="多用户模式">
          <a-tag :color="systemStats.multi_user_enabled ? 'green' : 'default'">
            {{ systemStats.multi_user_enabled ? '启用' : '禁用' }}
          </a-tag>
        </a-descriptions-item>
      </a-descriptions>
    </div>
    <div  v-if="!loading">
      <h3><DashboardOutlined /> 性能指标</h3>
      <div >
        <div  v-for="perf in performanceMetrics" :key="perf.name">
          <div >
            <component :is="perf.icon" :style="{ color: perf.color }" />
            <span>{{ perf.name }}</span>
          </div>
          <div >{{ perf.value }}</div>
          <div >{{ perf.sub }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
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
      statsAPI.getSystemStats().catch(() => ({ data: null })),
      statsAPI.getControlDashboard().catch(() => ({ data: null })),
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
onMounted(() => {
  loadData()
})
</script>
<style scoped>
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
</style>
 