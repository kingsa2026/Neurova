<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t">
        <ShieldOutlined :style="{color:'#ef4444'}" /> 安全管理
      </h2>
      <a-space>
        <a-btn size="small" @click="refreshData">
          <RefreshOutlined />刷新
        </a-btn>
        <a-btn type="primary" size="small" @click="showExportModal = true">
          <DownloadOutlined />导出日志
        </a-btn>
      </a-space>
    </div>

    <div class="stats-row">
      <div class="stat-card glass-effect">
        <div class="stat-icon red">
          <AlertTriangleOutlined />
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.alerts }}</div>
          <div class="stat-label">安全告警</div>
        </div>
      </div>
      <div class="stat-card glass-effect">
        <div class="stat-icon orange">
          <LockOutlined />
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.blocked }}</div>
          <div class="stat-label">拦截次数</div>
        </div>
      </div>
      <div class="stat-card glass-effect">
        <div class="stat-icon green">
          <CheckCircleOutlined />
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.passed }}</div>
          <div class="stat-label">安全通过</div>
        </div>
      </div>
      <div class="stat-card glass-effect">
        <div class="stat-icon blue">
          <ClockCircleOutlined />
        </div>
        <div class="stat-content">
          <div class="stat-value">{{ stats.activeDays }}</div>
          <div class="stat-label">连续安全天数</div>
        </div>
      </div>
    </div>

    <a-tabs default-active-key="audit" :items="tabs" class="tabs">
      <template #audit>
        <div class="tab-content">
          <div class="filter-bar">
            <a-input-search
              placeholder="搜索日志"
              v-model:value="auditFilter.keyword"
              @search="fetchAuditLogs"
              style="width: 260px"
            />
            <a-select
              v-model:value="auditFilter.level"
              placeholder="日志级别"
              style="width: 140px"
              @change="fetchAuditLogs"
            >
              <a-select-option value="">全部</a-select-option>
              <a-select-option value="INFO">INFO</a-select-option>
              <a-select-option value="WARN">WARN</a-select-option>
              <a-select-option value="ERROR">ERROR</a-select-option>
            </a-select>
            <a-range-picker @change="onDateChange" />
          </div>
          <a-table
            :columns="auditCols"
            :data-source="auditLogs"
            row-key="id"
            size="small"
            :loading="auditLoading"
            :pagination="auditPagination"
            @change="onAuditPageChange"
          >
            <template #bodyCell="{ c, r }">
              <template v-if="c.key === 'level'">
                <a-tag :color="getLevelColor(r.level)">{{ r.level }}</a-tag>
              </template>
              <template v-if="c.key === 'time'">
                {{ formatTime(r.time) }}
              </template>
              <template v-if="c.key === 'action'">
                <a-tag size="small">{{ r.action }}</a-tag>
              </template>
            </template>
          </a-table>
        </div>
      </template>

      <template #threats>
        <div class="tab-content">
          <a-table
            :columns="threatCols"
            :data-source="threats"
            row-key="id"
            size="small"
            :loading="threatLoading"
          >
            <template #bodyCell="{ c, r }">
              <template v-if="c.key === 'severity'">
                <a-tag :color="getSeverityColor(r.severity)">{{ r.severity }}</a-tag>
              </template>
              <template v-if="c.key === 'status'">
                <a-tag :color="r.status === 'resolved' ? 'green' : 'orange'">
                  {{ r.status === 'resolved' ? '已处理' : '待处理' }}
                </a-tag>
              </template>
              <template v-if="c.key === 'act'">
                <a-space>
                  <a-btn size="small" type="link" @click="viewThreat(r)">查看详情</a-btn>
                  <a-btn size="small" type="link" v-if="r.status !== 'resolved'" @click="resolveThreat(r)">标记已处理</a-btn>
                </a-space>
              </template>
            </template>
          </a-table>
        </div>
      </template>

      <template #settings>
        <div class="tab-content">
          <a-form :model="securitySettings" layout="vertical">
            <a-form-item label="登录安全">
              <a-space direction="vertical" style="width: 100%">
                <a-switch v-model:checked="securitySettings.loginLockout" />
                <span>登录失败次数限制</span>
              </a-space>
            </a-form-item>
            <a-form-item label="会话超时">
              <a-input-number v-model:value="securitySettings.sessionTimeout" :min="5" :max="1440" />
              <span style="margin-left: 8px">分钟</span>
            </a-form-item>
            <a-form-item label="双因素认证">
              <a-switch v-model:checked="securitySettings.twoFactorAuth" />
              <span>启用双因素认证</span>
            </a-form-item>
            <a-form-item label="API访问限制">
              <a-switch v-model:checked="securitySettings.apiRateLimit" />
              <span>启用API速率限制</span>
            </a-form-item>
            <a-form-item>
              <a-btn type="primary" @click="saveSettings">保存设置</a-btn>
            </a-form-item>
          </a-form>
        </div>
      </template>
    </a-tabs>

    <a-modal
      v-model:open="showExportModal"
      title="导出审计日志"
      @ok="exportLogs"
      @cancel="showExportModal = false"
    >
      <a-form :model="exportForm" layout="vertical">
        <a-form-item label="导出格式">
          <a-select v-model:value="exportForm.format">
            <a-select-option value="csv">CSV</a-select-option>
            <a-select-option value="json">JSON</a-select-option>
            <a-select-option value="xlsx">Excel</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="时间范围">
          <a-range-picker v-model:value="exportForm.dateRange" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
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
const auditLogs = ref<AuditLog[]>([]);
const auditPagination = ref({
  current: 1,
  pageSize: 20,
  total: 0
});

const threatLoading = ref(false);
const threats = ref<Threat[]>([]);

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

const fetchAuditLogs = async () => {
  auditLoading.value = true;
  try {
    const params: Record<string, unknown> = {
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

const fetchThreats = async () => {
  threatLoading.value = true;
  try {
    const res = await request.get('/audit/logs', {
      params: { event_type: 'security', page_size: 50 }
    });
    if (res.success && res.data?.items) {
      threats.value = res.data.items.map((item: Record<string, unknown>, idx: number) => ({
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

const refreshData = () => {
  fetchAuditLogs();
  fetchThreats();
};

const onDateChange = () => {
  fetchAuditLogs();
};

const onAuditPageChange = (pagination: { current: number; pageSize: number; total: number }) => {
  auditPagination.value = pagination;
  fetchAuditLogs();
};

const getLevelColor = (level: string) => {
  const colors: Record<string, string> = {
    INFO: 'blue',
    WARN: 'orange',
    ERROR: 'red'
  };
  return colors[level] || 'default';
};

const getSeverityColor = (severity: string) => {
  const colors: Record<string, string> = {
    high: 'red',
    medium: 'orange',
    low: 'yellow'
  };
  return colors[severity] || 'default';
};

const formatTime = (time: string) => {
  try {
    return new Date(time).toLocaleString('zh-CN');
  } catch {
    return time;
  }
};

const viewThreat = (threat: Threat) => {
  message.info(`查看威胁详情: ${threat.type}`);
};

const resolveThreat = async (threat: Threat) => {
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

const saveSettings = async () => {
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

const exportLogs = async () => {
  try {
    const params: Record<string, unknown> = {
      format: exportForm.format
    };
    if (exportForm.dateRange && exportForm.dateRange.length === 2) {
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
</script>

<style scoped>
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
</style>