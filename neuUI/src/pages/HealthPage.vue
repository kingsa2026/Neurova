<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><MedicineBoxOutlined :style="{color:'#34d399'}"/> 健康管理</h2>
      <a-button type="primary" size="small" :loading="loading" @click="runAllChecks">
        <SyncOutlined/> 一键检查
      </a-button>
    </div>
    <div class="sr">
      <div class="s glass-effect">
        健康<b class="c1">{{ healthPercent }}%</b>
      </div>
      <div class="s glass-effect">
        检查<b class="c1">{{ totalChecks }}</b>
      </div>
      <div class="s glass-effect">
        告警<b class="c2">{{ warningCount }}</b>
      </div>
    </div>
    <div class="tb glass-effect">
      <a-table
        :columns="cols"
        :data-source="data"
        row-key="name"
        size="middle"
        :loading="loading"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key==='st'">
            <a-tag :color="getStatusColor(record.status)" size="small">
              {{ getStatusText(record.status) }}
            </a-tag>
          </template>
          <template v-if="column.key==='act'">
            <a-button type="link" size="small" @click="runSingleCheck(record.name)">
              运行检查
            </a-button>
          </template>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { MedicineBoxOutlined, SyncOutlined } from '@ant-design/icons-vue';
import { systemAPI } from '@/api/modules/system';
import { message } from 'ant-design-vue';

const loading = ref(false);
interface HealthStatus { healthy: boolean; [key: string]: unknown }
interface CheckResult { status: string; duration_ms?: number; timestamp?: string }
interface HealthCheck { last_result?: CheckResult; [key: string]: unknown }
const healthData = ref<HealthStatus | null>(null);
const checks = ref<Record<string, HealthCheck>>({});

const cols = [
  { title: '检查项', dataIndex: 'name' },
  { title: '状态', key: 'st', width: 80 },
  { 
    title: '耗时', 
    dataIndex: 'duration_ms', 
    width: 100,
    customRender: ({ text }: { text: number }) => `${text}ms`
  },
  { title: '上次检查', dataIndex: 'last', width: 160 },
  { title: '操作', key: 'act', width: 100 }
];

const data = computed(() => {
  const items: Array<{ name: string; status: string; duration_ms?: number; last: string; [key: string]: unknown }> = [];
  Object.entries(checks.value).forEach(([name, check]) => {
    if (check.last_result) {
      items.push({
        name,
        status: check.last_result.status,
        duration_ms: check.last_result.duration_ms,
        last: new Date(check.last_result.timestamp).toLocaleString(),
        ...check
      });
    }
  });
  return items;
});

const healthPercent = computed(() => {
  if (!healthData.value) return 99.8;
  return healthData.value.healthy ? 100 : 80;
});

const totalChecks = computed(() => Object.keys(checks.value).length);

const warningCount = computed(() => {
  return Object.values(checks.value).filter((c) => 
    c.last_result && (c.last_result.status === 'warning' || c.last_result.status === 'unhealthy')
  ).length;
});

const getStatusColor = (status: string) => {
  const colorMap: Record<string, string> = {
    healthy: 'green',
    degraded: 'orange',
    warning: 'orange',
    unhealthy: 'red'
  };
  return colorMap[status] || 'default';
};

const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    healthy: '正常',
    degraded: '降级',
    warning: '警告',
    unhealthy: '异常'
  };
  return textMap[status] || status;
};

const loadHealthData = async () => {
  loading.value = true;
  try {
    const [healthRes, checksRes] = await Promise.all([
      systemAPI.getHealth(),
      systemAPI.getHealthChecks()
    ]);
    healthData.value = healthRes.data;
    checks.value = checksRes.data.checks || {};
  } catch (err) {
    console.error('加载健康数据失败:', err);
    message.error('加载健康数据失败');
  } finally {
    loading.value = false;
  }
};

const runAllChecks = async () => {
  loading.value = true;
  try {
    await systemAPI.triggerRecovery();
    message.success('健康检查完成');
    await loadHealthData();
  } catch (err) {
    console.error('健康检查失败:', err);
    message.error('健康检查失败');
  } finally {
    loading.value = false;
  }
};

const runSingleCheck = async (checkName: string) => {
  try {
    await systemAPI.runHealthCheck(checkName);
    message.success(`${checkName} 检查完成`);
    await loadHealthData();
  } catch (err) {
    console.error('检查失败:', err);
    message.error('检查失败');
  }
};

onMounted(() => {
  loadHealthData();
});
</script>

<style scoped>
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.s { padding: 20px; text-align: center; font-size: 1.1rem; }
.s b { font-size: 1.8rem; }
.s .c1 { color: #34d399; }
.s .c2 { color: #ef4444; }
.tb { padding: 20px; border-radius: 12px; }
</style>
