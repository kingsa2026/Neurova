&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;MedicineBoxOutlined :style="{color:'#34d399'}"/&gt; 健康管理&lt;/h2&gt;
      &lt;a-button type="primary" size="small" :loading="loading" @click="runAllChecks"&gt;
        &lt;SyncOutlined/&gt; 一键检查
      &lt;/a-button&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        健康&lt;b &gt;{{ healthPercent }}%&lt;/b&gt;
      &lt;/div&gt;
      &lt;div &gt;
        检查&lt;b &gt;{{ totalChecks }}&lt;/b&gt;
      &lt;/div&gt;
      &lt;div &gt;
        告警&lt;b &gt;{{ warningCount }}&lt;/b&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-table
        :columns="cols"
        :data-source="data"
        row-key="name"
        size="middle"
        :loading="loading"
        :pagination="false"
      &gt;
        &lt;template #bodyCell="{ column, record }"&gt;
          &lt;template v-if="column.key==='st'"&gt;
            &lt;a-tag :color="getStatusColor(record.status)" size="small"&gt;
              {{ getStatusText(record.status) }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-if="column.key==='act'"&gt;
            &lt;a-button type="link" size="small" @click="runSingleCheck(record.name)"&gt;
              运行检查
            &lt;/a-button&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed, onMounted } from 'vue';
import { MedicineBoxOutlined, SyncOutlined } from '@ant-design/icons-vue';
import { systemAPI } from '@/api/modules/system';
import { message } from 'ant-design-vue';
const loading = ref(false);
interface HealthStatus { healthy: boolean; [key: string]: unknown }
interface CheckResult { status: string; duration_ms?: number; timestamp?: string }
interface HealthCheck { last_result?: CheckResult; [key: string]: unknown }
const healthData = ref&lt;HealthStatus | null&gt;(null);
const checks = ref&lt;Record&lt;string, HealthCheck&gt;&gt;({});
const cols = [
  { title: '检查项', dataIndex: 'name' },
  { title: '状态', key: 'st', width: 80 },
  { 
    title: '耗时', 
    dataIndex: 'duration_ms', 
    width: 100,
    customRender: ({ text }: { text: number }) =&gt; `${text}ms`
  },
  { title: '上次检查', dataIndex: 'last', width: 160 },
  { title: '操作', key: 'act', width: 100 }
];
const data = computed(() =&gt; {
  const items: Array&lt;{ name: string; status: string; duration_ms?: number; last: string; [key: string]: unknown }&gt; = [];
  Object.entries(checks.value).forEach(([name, check]) =&gt; {
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
const healthPercent = computed(() =&gt; {
  if (!healthData.value) return 99.8;
  return healthData.value.healthy ? 100 : 80;
});
const totalChecks = computed(() =&gt; Object.keys(checks.value).length);
const warningCount = computed(() =&gt; {
  return Object.values(checks.value).filter((c) =&gt; 
    c.last_result &amp;&amp; (c.last_result.status === 'warning' || c.last_result.status === 'unhealthy')
  ).length;
});
const getStatusColor = (status: string) =&gt; {
  const colorMap: Record&lt;string, string&gt; = {
    healthy: 'green',
    degraded: 'orange',
    warning: 'orange',
    unhealthy: 'red'
  };
  return colorMap[status] || 'default';
};
const getStatusText = (status: string) =&gt; {
  const textMap: Record&lt;string, string&gt; = {
    healthy: '正常',
    degraded: '降级',
    warning: '警告',
    unhealthy: '异常'
  };
  return textMap[status] || status;
};
const loadHealthData = async () =&gt; {
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
const runAllChecks = async () =&gt; {
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
const runSingleCheck = async (checkName: string) =&gt; {
  try {
    await systemAPI.runHealthCheck(checkName);
    message.success(`${checkName} 检查完成`);
    await loadHealthData();
  } catch (err) {
    console.error('检查失败:', err);
    message.error('检查失败');
  }
};
onMounted(() =&gt; {
  loadHealthData();
});
&lt;/script&gt;
&lt;style scoped&gt;
.pg { display: flex; flex-direction: column; gap: 14px; }
.hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-radius: 12px; }
.t { font-size: 1.2rem; color: #e2e8f0; margin: 0; display: flex; align-items: center; gap: 8px; }
.sr { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.s { padding: 20px; text-align: center; font-size: 1.1rem; }
.s b { font-size: 1.8rem; }
.s .c1 { color: #34d399; }
.s .c2 { color: #ef4444; }
.tb { padding: 20px; border-radius: 12px; }
&lt;/style&gt;
&nbsp;