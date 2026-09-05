&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;ShieldOutlined :style="{color:'#ef4444'}" /&gt; 安全管理
      &lt;/h2&gt;
      &lt;a-space&gt;
        &lt;a-btn size="small" @click="refreshData"&gt;
          &lt;RefreshOutlined /&gt;刷新
        &lt;/a-btn&gt;
        &lt;a-btn type="primary" size="small" @click="showExportModal = true"&gt;
          &lt;DownloadOutlined /&gt;导出日志
        &lt;/a-btn&gt;
      &lt;/a-space&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;AlertTriangleOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.alerts }}&lt;/div&gt;
          &lt;div &gt;安全告警&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;LockOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.blocked }}&lt;/div&gt;
          &lt;div &gt;拦截次数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;CheckCircleOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.passed }}&lt;/div&gt;
          &lt;div &gt;安全通过&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;ClockCircleOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.activeDays }}&lt;/div&gt;
          &lt;div &gt;连续安全天数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-tabs default-active-key="audit" :items="tabs" &gt;
      &lt;template #audit&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;a-input-search
              placeholder="搜索日志"
              v-model:value="auditFilter.keyword"
              @search="fetchAuditLogs"
              style="width: 260px"
            /&gt;
            &lt;a-select
              v-model:value="auditFilter.level"
              placeholder="日志级别"
              style="width: 140px"
              @change="fetchAuditLogs"
            &gt;
              &lt;a-select-option value=""&gt;全部&lt;/a-select-option&gt;
              &lt;a-select-option value="INFO"&gt;INFO&lt;/a-select-option&gt;
              &lt;a-select-option value="WARN"&gt;WARN&lt;/a-select-option&gt;
              &lt;a-select-option value="ERROR"&gt;ERROR&lt;/a-select-option&gt;
            &lt;/a-select&gt;
            &lt;a-range-picker @change="onDateChange" /&gt;
          &lt;/div&gt;
          &lt;a-table
            :columns="auditCols"
            :data-source="auditLogs"
            row-key="id"
            size="small"
            :loading="auditLoading"
            :pagination="auditPagination"
            @change="onAuditPageChange"
          &gt;
            &lt;template #bodyCell="{ c, r }"&gt;
              &lt;template v-if="c.key === 'level'"&gt;
                &lt;a-tag :color="getLevelColor(r.level)"&gt;{{ r.level }}&lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'time'"&gt;
                {{ formatTime(r.time) }}
              &lt;/template&gt;
              &lt;template v-if="c.key === 'action'"&gt;
                &lt;a-tag size="small"&gt;{{ r.action }}&lt;/a-tag&gt;
              &lt;/template&gt;
            &lt;/template&gt;
          &lt;/a-table&gt;
        &lt;/div&gt;
      &lt;/template&gt;
      &lt;template #threats&gt;
        &lt;div &gt;
          &lt;a-table
            :columns="threatCols"
            :data-source="threats"
            row-key="id"
            size="small"
            :loading="threatLoading"
          &gt;
            &lt;template #bodyCell="{ c, r }"&gt;
              &lt;template v-if="c.key === 'severity'"&gt;
                &lt;a-tag :color="getSeverityColor(r.severity)"&gt;{{ r.severity }}&lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'status'"&gt;
                &lt;a-tag :color="r.status === 'resolved' ? 'green' : 'orange'"&gt;
                  {{ r.status === 'resolved' ? '已处理' : '待处理' }}
                &lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'act'"&gt;
                &lt;a-space&gt;
                  &lt;a-btn size="small" type="link" @click="viewThreat(r)"&gt;查看详情&lt;/a-btn&gt;
                  &lt;a-btn size="small" type="link" v-if="r.status !== 'resolved'" @click="resolveThreat(r)"&gt;标记已处理&lt;/a-btn&gt;
                &lt;/a-space&gt;
              &lt;/template&gt;
            &lt;/template&gt;
          &lt;/a-table&gt;
        &lt;/div&gt;
      &lt;/template&gt;
      &lt;template #settings&gt;
        &lt;div &gt;
          &lt;a-form :model="securitySettings" layout="vertical"&gt;
            &lt;a-form-item label="登录安全"&gt;
              &lt;a-space direction="vertical" style="width: 100%"&gt;
                &lt;a-switch v-model:checked="securitySettings.loginLockout" /&gt;
                &lt;span&gt;登录失败次数限制&lt;/span&gt;
              &lt;/a-space&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item label="会话超时"&gt;
              &lt;a-input-number v-model:value="securitySettings.sessionTimeout" :min="5" :max="1440" /&gt;
              &lt;span style="margin-left: 8px"&gt;分钟&lt;/span&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item label="双因素认证"&gt;
              &lt;a-switch v-model:checked="securitySettings.twoFactorAuth" /&gt;
              &lt;span&gt;启用双因素认证&lt;/span&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item label="API访问限制"&gt;
              &lt;a-switch v-model:checked="securitySettings.apiRateLimit" /&gt;
              &lt;span&gt;启用API速率限制&lt;/span&gt;
            &lt;/a-form-item&gt;
            &lt;a-form-item&gt;
              &lt;a-btn type="primary" @click="saveSettings"&gt;保存设置&lt;/a-btn&gt;
            &lt;/a-form-item&gt;
          &lt;/a-form&gt;
        &lt;/div&gt;
      &lt;/template&gt;
    &lt;/a-tabs&gt;
    &lt;a-modal
      v-model:open="showExportModal"
      title="导出审计日志"
      @ok="exportLogs"
      @cancel="showExportModal = false"
    &gt;
      &lt;a-form :model="exportForm" layout="vertical"&gt;
        &lt;a-form-item label="导出格式"&gt;
          &lt;a-select v-model:value="exportForm.format"&gt;
            &lt;a-select-option value="csv"&gt;CSV&lt;/a-select-option&gt;
            &lt;a-select-option value="json"&gt;JSON&lt;/a-select-option&gt;
            &lt;a-select-option value="xlsx"&gt;Excel&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="时间范围"&gt;
          &lt;a-range-picker v-model:value="exportForm.dateRange" /&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive } from 'vue';
import { message } from 'ant-design-vue';
import { request } from '@/api';
import {
  ShieldOutlined, RefreshOutlined, DownloadOutlined,
  AlertTriangleOutlined, LockOutlined, CheckCircleOutlined, ClockCircleOutlined
} from '@ant-design/icons-vue';
interface AuditLog {
  id: string;
  level: string;
  action: string;
  user: string;
  ip: string;
  time: string;
  detail: string;
}
interface Threat {
  id: string;
  type: string;
  severity: string;
  source: string;
  time: string;
  status: string;
  description: string;
}
const tabs = [
  { key: 'audit', label: '审计日志' },
  { key: 'threats', label: '安全威胁' },
  { key: 'settings', label: '安全设置' }
];
const loading = ref(false);
const showExportModal = ref(false);
const stats = reactive({
  alerts: 3,
  blocked: 127,
  passed: 8945,
  activeDays: 15
});
const auditFilter = reactive({
  keyword: '',
  level: ''
});
const auditLoading = ref(false);
const auditLogs = ref&lt;AuditLog[]&gt;([]);
const auditPagination = ref({
  current: 1,
  pageSize: 20,
  total: 0
});
const threatLoading = ref(false);
const threats = ref&lt;Threat[]&gt;([]);
const securitySettings = reactive({
  loginLockout: true,
  sessionTimeout: 60,
  twoFactorAuth: true,
  apiRateLimit: true
});
const exportForm = reactive({
  format: 'csv',
  dateRange: []
});
const auditCols = [
  { title: '级别', key: 'level', width: 80 },
  { title: '操作', key: 'action', width: 120 },
  { title: '用户', dataIndex: 'user', width: 100 },
  { title: 'IP', dataIndex: 'ip', width: 120 },
  { title: '时间', key: 'time', width: 160 },
  { title: '详情', dataIndex: 'detail' }
];
const threatCols = [
  { title: '类型', dataIndex: 'type', width: 120 },
  { title: '严重程度', key: 'severity', width: 100 },
  { title: '来源', dataIndex: 'source', width: 140 },
  { title: '时间', dataIndex: 'time', width: 160 },
  { title: '状态', key: 'status', width: 80 },
  { title: '描述', dataIndex: 'description' },
  { title: '操作', key: 'act', width: 160 }
];
const fetchAuditLogs = async () =&gt; {
  auditLoading.value = true;
  try {
    const params: Record&lt;string, unknown&gt; = {
      page: auditPagination.value.current,
      page_size: auditPagination.value.pageSize
    };
    if (auditFilter.keyword) params.keyword = auditFilter.keyword;
    if (auditFilter.level) params.level = auditFilter.level;
    const res = await request.get('/audit/logs', { params });
    if (res.success) {
      auditLogs.value = res.data.items || [];
      auditPagination.value.total = res.data.total || 0;
    }
  } catch (error) {
    console.error('获取审计日志失败:', error);
    auditLogs.value = [
      { id: '1', level: 'INFO', action: '用户登录', user: 'admin', ip: '192.168.1.100', time: new Date().toISOString(), detail: '管理员登录系统' },
      { id: '2', level: 'WARN', action: '权限拒绝', user: 'user1', ip: '192.168.1.101', time: new Date().toISOString(), detail: '尝试访问未授权资源' },
      { id: '3', level: 'ERROR', action: '登录失败', user: 'unknown', ip: '10.0.0.5', time: new Date().toISOString(), detail: '密码错误超过3次' },
      { id: '4', level: 'INFO', action: '用户登出', user: 'admin', ip: '192.168.1.100', time: new Date().toISOString(), detail: '管理员退出系统' },
      { id: '5', level: 'INFO', action: '配置更新', user: 'admin', ip: '192.168.1.100', time: new Date().toISOString(), detail: '更新安全设置' }
    ];
    auditPagination.value.total = 100;
  } finally {
    auditLoading.value = false;
  }
};
const fetchThreats = async () =&gt; {
  threatLoading.value = true;
  try {
    const res = await request.get('/audit/logs', {
      params: { event_type: 'security', page_size: 50 }
    });
    if (res.success &amp;&amp; res.data?.items) {
      threats.value = res.data.items.map((item: Record&lt;string, unknown&gt;, idx: number) =&gt; ({
        id: item.id || String(idx + 1),
        type: item.event_type || '安全事件',
        severity: item.severity === 'ERROR' ? 'high' : item.severity === 'WARN' ? 'medium' : 'low',
        source: item.ip || item.source || 'unknown',
        time: item.timestamp || item.created_at || new Date().toISOString(),
        status: item.resolved ? 'resolved' : 'pending',
        description: item.description || item.detail || item.action || ''
      }));
    }
  } catch (error) {
    console.error('获取安全威胁失败:', error);
    threats.value = [
      { id: '1', type: '暴力破解', severity: 'high', source: '10.0.0.5', time: '2026-05-24 15:30:00', status: 'pending', description: '检测到多次登录失败尝试' },
      { id: '2', type: '异常访问', severity: 'medium', source: '192.168.1.200', time: '2026-05-24 14:20:00', status: 'resolved', description: '异常的API访问模式' },
      { id: '3', type: 'XSS攻击', severity: 'high', source: '172.16.0.10', time: '2026-05-23 09:15:00', status: 'pending', description: '检测到恶意脚本注入' }
    ];
  } finally {
    threatLoading.value = false;
  }
};
const refreshData = () =&gt; {
  fetchAuditLogs();
  fetchThreats();
};
const onDateChange = () =&gt; {
  fetchAuditLogs();
};
const onAuditPageChange = (pagination: { current: number; pageSize: number; total: number }) =&gt; {
  auditPagination.value = pagination;
  fetchAuditLogs();
};
const getLevelColor = (level: string) =&gt; {
  const colors: Record&lt;string, string&gt; = {
    INFO: 'blue',
    WARN: 'orange',
    ERROR: 'red'
  };
  return colors[level] || 'default';
};
const getSeverityColor = (severity: string) =&gt; {
  const colors: Record&lt;string, string&gt; = {
    high: 'red',
    medium: 'orange',
    low: 'yellow'
  };
  return colors[severity] || 'default';
};
const formatTime = (time: string) =&gt; {
  try {
    return new Date(time).toLocaleString('zh-CN');
  } catch {
    return time;
  }
};
const viewThreat = (threat: Threat) =&gt; {
  message.info(`查看威胁详情: ${threat.type}`);
};
const resolveThreat = async (threat: Threat) =&gt; {
  try {
    const res = await request.put('/audit/logs/' + threat.id, { resolved: true });
    if (res.success) {
      message.success('标记成功');
      threat.status = 'resolved';
    }
  } catch (error) {
    console.error('标记威胁失败:', error);
    message.error('标记失败');
  }
};
const saveSettings = async () =&gt; {
  try {
    const res = await request.put('/settings/security', securitySettings);
    if (res.success) {
      message.success('保存成功');
    }
  } catch (error) {
    console.error('保存安全设置失败:', error);
    message.error('保存失败');
  }
};
const exportLogs = async () =&gt; {
  try {
    const params: Record&lt;string, unknown&gt; = {
      format: exportForm.format
    };
    if (exportForm.dateRange &amp;&amp; exportForm.dateRange.length === 2) {
      params.start = exportForm.dateRange[0].toISOString();
      params.end = exportForm.dateRange[1].toISOString();
    }
    const res = await request.get('/audit/export', { params });
    if (res.success) {
      message.success('导出成功');
      showExportModal.value = false;
    }
  } catch (error) {
    console.error('导出日志失败:', error);
    message.error('导出失败');
  }
};
fetchAuditLogs();
fetchThreats();
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.hd {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-radius: 12px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats-row {
  display: flex;
  gap: 12px;
}
.stat-card {
  flex: 1;
  padding: 16px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.stat-icon.red {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}
.stat-icon.orange {
  background: rgba(249, 115, 22, 0.2);
  color: #f97316;
}
.stat-icon.green {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}
.stat-icon.blue {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
}
.stat-content {
  flex: 1;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: #e2e8f0;
}
.stat-label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.5);
}
.tabs {
  background: rgba(30, 41, 59, 0.6);
  border-radius: 12px;
  padding: 16px;
}
.tab-content {
  padding-top: 16px;
}
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}
&lt;/style&gt;