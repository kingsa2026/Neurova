&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;FirewallOutlined :style="{color:'#f97316'}" /&gt; 防火墙管理
      &lt;/h2&gt;
      &lt;a-space&gt;
        &lt;a-switch v-model:checked="globalEnabled" @change="toggleGlobal" /&gt;
        &lt;span&gt;{{ globalEnabled ? '已启用' : '已禁用' }}&lt;/span&gt;
      &lt;/a-space&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;ShieldAlertOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.blockedRequests }}&lt;/div&gt;
          &lt;div &gt;今日拦截&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;CheckCircleOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.allowedRequests }}&lt;/div&gt;
          &lt;div &gt;今日放行&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;BanOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.blacklistedIPs }}&lt;/div&gt;
          &lt;div &gt;黑名单IP&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;
          &lt;ClockCircleOutlined /&gt;
        &lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.rateLimitHits }}&lt;/div&gt;
          &lt;div &gt;触发限流&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-tabs default-active-key="rules" :items="tabs" &gt;
      &lt;template #rules&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;h3 &gt;全局规则&lt;/h3&gt;
            &lt;a-form :model="globalRules" layout="vertical"&gt;
              &lt;a-row :gutter="16"&gt;
                &lt;a-col :span="8"&gt;
                  &lt;a-form-item label="速率限制 (次/分钟)"&gt;
                    &lt;a-input-number v-model:value="globalRules.rateLimit" :min="10" :max="1000" /&gt;
                  &lt;/a-form-item&gt;
                &lt;/a-col&gt;
                &lt;a-col :span="8"&gt;
                  &lt;a-form-item label="最大请求大小 (MB)"&gt;
                    &lt;a-input-number v-model:value="globalRules.maxPayloadMB" :min="1" :max="100" /&gt;
                  &lt;/a-form-item&gt;
                &lt;/a-col&gt;
                &lt;a-col :span="8"&gt;
                  &lt;a-form-item label="启用IP过滤"&gt;
                    &lt;a-switch v-model:checked="globalRules.enableIPFilter" /&gt;
                  &lt;/a-form-item&gt;
                &lt;/a-col&gt;
              &lt;/a-row&gt;
              &lt;a-form-item label="禁止的文件扩展名"&gt;
                &lt;a-input
                  v-model:value="globalRules.blockedExtensions"
                  placeholder="逗号分隔，如: .exe,.php,.sh"
                /&gt;
              &lt;/a-form-item&gt;
              &lt;a-form-item label="禁止的路径模式"&gt;
                &lt;a-textarea
                  v-model:value="globalRules.blockedPaths"
                  placeholder="每行一个路径模式"
                  :rows="3"
                /&gt;
              &lt;/a-form-item&gt;
              &lt;a-form-item&gt;
                &lt;a-btn type="primary" @click="saveGlobalRules"&gt;保存全局规则&lt;/a-btn&gt;
              &lt;/a-form-item&gt;
            &lt;/a-form&gt;
          &lt;/div&gt;
        &lt;/div&gt;
      &lt;/template&gt;
      &lt;template #whitelist&gt;
        &lt;div &gt;
          &lt;div &gt;
            &lt;a-input-search
              placeholder="搜索IP"
              v-model:value="ipFilter"
              @search="searchIP"
              style="width: 260px"
            /&gt;
            &lt;a-btn type="primary" size="small" @click="showAddIPModal = true"&gt;
              &lt;PlusOutlined /&gt;添加白名单
            &lt;/a-btn&gt;
          &lt;/div&gt;
          &lt;a-table
            :columns="ipCols"
            :data-source="whitelistIPs"
            row-key="ip"
            size="small"
          &gt;
            &lt;template #bodyCell="{ c, r }"&gt;
              &lt;template v-if="c.key === 'status'"&gt;
                &lt;a-tag :color="r.status === 'active' ? 'green' : 'default'"&gt;
                  {{ r.status === 'active' ? '活跃' : '禁用' }}
                &lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'actions'"&gt;
                &lt;a-space&gt;
                  &lt;a-btn size="small" type="link" @click="toggleIPStatus(r)"&gt;
                    {{ r.status === 'active' ? '禁用' : '启用' }}
                  &lt;/a-btn&gt;
                  &lt;a-popconfirm title="确定删除此IP？" @confirm="removeIP(r.ip)"&gt;
                    &lt;a-btn size="small" type="link" danger&gt;删除&lt;/a-btn&gt;
                  &lt;/a-popconfirm&gt;
                &lt;/a-space&gt;
              &lt;/template&gt;
            &lt;/template&gt;
          &lt;/a-table&gt;
        &lt;/div&gt;
      &lt;/template&gt;
      &lt;template #blacklist&gt;
        &lt;div &gt;
          &lt;a-table
            :columns="blacklistCols"
            :data-source="blacklistIPs"
            row-key="ip"
            size="small"
          &gt;
            &lt;template #bodyCell="{ c, r }"&gt;
              &lt;template v-if="c.key === 'reason'"&gt;
                &lt;a-tag color="red"&gt;{{ r.reason }}&lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'actions'"&gt;
                &lt;a-space&gt;
                  &lt;a-btn size="small" type="link" @click="unblockIP(r)"&gt;解除封禁&lt;/a-btn&gt;
                &lt;/a-space&gt;
              &lt;/template&gt;
            &lt;/template&gt;
          &lt;/a-table&gt;
        &lt;/div&gt;
      &lt;/template&gt;
      &lt;template #logs&gt;
        &lt;div &gt;
          &lt;a-table
            :columns="logCols"
            :data-source="firewallLogs"
            row-key="id"
            size="small"
            :pagination="logPagination"
          &gt;
            &lt;template #bodyCell="{ c, r }"&gt;
              &lt;template v-if="c.key === 'action'"&gt;
                &lt;a-tag :color="r.action === 'block' ? 'red' : 'green'"&gt;
                  {{ r.action === 'block' ? '拦截' : '放行' }}
                &lt;/a-tag&gt;
              &lt;/template&gt;
              &lt;template v-if="c.key === 'time'"&gt;
                {{ formatTime(r.time) }}
              &lt;/template&gt;
            &lt;/template&gt;
          &lt;/a-table&gt;
        &lt;/div&gt;
      &lt;/template&gt;
    &lt;/a-tabs&gt;
    &lt;a-modal
      v-model:open="showAddIPModal"
      title="添加白名单IP"
      @ok="addWhitelistIP"
      @cancel="showAddIPModal = false"
    &gt;
      &lt;a-form :model="newIPForm" layout="vertical"&gt;
        &lt;a-form-item label="IP地址"&gt;
          &lt;a-input v-model:value="newIPForm.ip" placeholder="请输入IP地址" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="备注"&gt;
          &lt;a-input v-model:value="newIPForm.note" placeholder="可选，如：公司办公网" /&gt;
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
  FirewallOutlined, ShieldAlertOutlined, CheckCircleOutlined,
  BanOutlined, ClockCircleOutlined, PlusOutlined
} from '@ant-design/icons-vue';
interface WhitelistIP {
  ip: string;
  note?: string;
  status: string;
  added_at: string;
}
interface BlacklistIP {
  ip: string;
  reason: string;
  blocked_at: string;
  block_count: number;
}
interface FirewallLog {
  id: string;
  ip: string;
  action: string;
  rule: string;
  time: string;
  detail: string;
}
const tabs = [
  { key: 'rules', label: '规则设置' },
  { key: 'whitelist', label: 'IP白名单' },
  { key: 'blacklist', label: 'IP黑名单' },
  { key: 'logs', label: '拦截日志' }
];
const globalEnabled = ref(true);
const showAddIPModal = ref(false);
const ipFilter = ref('');
const stats = reactive({
  blockedRequests: 127,
  allowedRequests: 8945,
  blacklistedIPs: 15,
  rateLimitHits: 23
});
const globalRules = reactive({
  rateLimit: 100,
  maxPayloadMB: 10,
  enableIPFilter: true,
  blockedExtensions: '.exe,.php,.sh,.py,.bat,.cmd',
  blockedPaths: '/etc/\n/home/\n/root/'
});
const newIPForm = reactive({
  ip: '',
  note: ''
});
const whitelistIPs = ref&lt;WhitelistIP[]&gt;([
  { ip: '192.168.1.0/24', note: '内网网段', status: 'active', added_at: '2026-01-15' },
  { ip: '10.0.0.0/8', note: '公司内网', status: 'active', added_at: '2026-02-01' },
  { ip: '172.16.0.0/12', note: '测试环境', status: 'active', added_at: '2026-03-10' },
  { ip: '47.252.31.69', note: '生产服务器', status: 'active', added_at: '2026-04-05' },
  { ip: '127.0.0.1', note: '本地回环', status: 'active', added_at: '2026-01-01' }
]);
const blacklistIPs = ref&lt;BlacklistIP[]&gt;([
  { ip: '10.0.0.5', reason: '暴力破解', blocked_at: '2026-05-24', block_count: 156 },
  { ip: '198.51.100.20', reason: '恶意扫描', blocked_at: '2026-05-23', block_count: 89 },
  { ip: '203.0.113.45', reason: 'DDOS攻击', blocked_at: '2026-05-22', block_count: 456 },
  { ip: '192.0.2.100', reason: '异常请求', blocked_at: '2026-05-21', block_count: 34 }
]);
const firewallLogs = ref&lt;FirewallLog[]&gt;([
  { id: '1', ip: '10.0.0.5', action: 'block', rule: '暴力破解检测', time: new Date().toISOString(), detail: '连续10次登录失败' },
  { id: '2', ip: '192.168.1.100', action: 'allow', rule: '白名单', time: new Date().toISOString(), detail: '来自信任IP' },
  { id: '3', ip: '198.51.100.20', action: 'block', rule: '恶意扫描', time: new Date().toISOString(), detail: '检测到端口扫描' },
  { id: '4', ip: '10.0.0.10', action: 'block', rule: '速率限制', time: new Date().toISOString(), detail: '超过每分钟100次请求' },
  { id: '5', ip: '172.16.0.5', action: 'allow', rule: '白名单', time: new Date().toISOString(), detail: '来自测试环境' }
]);
const logPagination = ref({
  current: 1,
  pageSize: 20,
  total: 100
});
const ipCols = [
  { title: 'IP地址', dataIndex: 'ip' },
  { title: '备注', dataIndex: 'note' },
  { title: '状态', key: 'status', width: 80 },
  { title: '添加时间', dataIndex: 'added_at', width: 120 },
  { title: '操作', key: 'actions', width: 160 }
];
const blacklistCols = [
  { title: 'IP地址', dataIndex: 'ip' },
  { title: '封禁原因', key: 'reason', width: 120 },
  { title: '封禁时间', dataIndex: 'blocked_at', width: 120 },
  { title: '拦截次数', dataIndex: 'block_count', width: 100 },
  { title: '操作', key: 'actions', width: 120 }
];
const logCols = [
  { title: 'IP地址', dataIndex: 'ip', width: 140 },
  { title: '操作', key: 'action', width: 80 },
  { title: '规则', dataIndex: 'rule', width: 120 },
  { title: '时间', key: 'time', width: 160 },
  { title: '详情', dataIndex: 'detail' }
];
const toggleGlobal = async () =&gt; {
  try {
    const res = await request.put('/firewall/global', {
      enabled: globalEnabled.value
    });
    if (res.success) {
      message.success(globalEnabled.value ? '防火墙已启用' : '防火墙已禁用');
    }
  } catch (error) {
    console.error('切换防火墙状态失败:', error);
    globalEnabled.value = !globalEnabled.value;
    message.error('操作失败');
  }
};
const saveGlobalRules = async () =&gt; {
  try {
    const res = await request.put('/firewall/global', {
      rate_limit_per_minute: globalRules.rateLimit,
      max_payload_bytes: globalRules.maxPayloadMB * 1024 * 1024,
      blocked_extensions: globalRules.blockedExtensions.split(',').map(s =&gt; s.trim()),
      blocked_patterns: globalRules.blockedPaths.split('\n').map(s =&gt; s.trim()).filter(Boolean),
      ip_whitelist_enabled: globalRules.enableIPFilter
    });
    if (res.success) {
      message.success('保存成功');
    }
  } catch (error) {
    console.error('保存全局规则失败:', error);
    message.error('保存失败');
  }
};
const searchIP = () =&gt; {
  console.log('搜索IP:', ipFilter.value);
};
const addWhitelistIP = async () =&gt; {
  if (!newIPForm.ip.trim()) {
    message.warning('请输入IP地址');
    return;
  }
  try {
    const res = await request.post('/firewall/user/rules', {
      extra_blocked_paths: [newIPForm.ip]
    });
    if (res.success) {
      message.success('添加成功');
      showAddIPModal.value = false;
      newIPForm.ip = '';
      newIPForm.note = '';
      whitelistIPs.value.push({
        ip: newIPForm.ip || 'new_ip',
        note: newIPForm.note || '',
        status: 'active',
        added_at: new Date().toLocaleDateString()
      });
    }
  } catch (error) {
    console.error('添加白名单失败:', error);
    whitelistIPs.value.push({
      ip: newIPForm.ip,
      note: newIPForm.note,
      status: 'active',
      added_at: new Date().toLocaleDateString()
    });
    showAddIPModal.value = false;
    newIPForm.ip = '';
    newIPForm.note = '';
    message.success('本地添加成功');
  }
};
const toggleIPStatus = (item: WhitelistIP) =&gt; {
  item.status = item.status === 'active' ? 'disabled' : 'active';
  message.success(`IP ${item.ip} ${item.status === 'active' ? '已启用' : '已禁用'}`);
};
const removeIP = async (ip: string) =&gt; {
  try {
    const res = await request.put('/firewall/user/rules', {
      extra_blocked_paths: []
    });
    if (res.success) {
      message.success('删除成功');
      whitelistIPs.value = whitelistIPs.value.filter(item =&gt; item.ip !== ip);
    }
  } catch (error) {
    console.error('删除白名单失败:', error);
    whitelistIPs.value = whitelistIPs.value.filter(item =&gt; item.ip !== ip);
    message.success('本地删除成功');
  }
};
const unblockIP = async (item: BlacklistIP) =&gt; {
  try {
    const res = await request.post('/firewall/user/rules', {
      extra_blocked_paths: []
    });
    if (res.success) {
      message.success('已解除封禁');
      blacklistIPs.value = blacklistIPs.value.filter(i =&gt; i.ip !== item.ip);
    }
  } catch (error) {
    console.error('解除封禁失败:', error);
    blacklistIPs.value = blacklistIPs.value.filter(i =&gt; i.ip !== item.ip);
    message.success('本地解除成功');
  }
};
const formatTime = (time: string) =&gt; {
  try {
    return new Date(time).toLocaleString('zh-CN');
  } catch {
    return time;
  }
};
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
.stat-icon.orange {
  background: rgba(249, 115, 22, 0.2);
  color: #f97316;
}
.stat-icon.green {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}
.stat-icon.red {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
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
.rule-section {
  background: rgba(15, 23, 42, 0.6);
  padding: 20px;
  border-radius: 10px;
}
.section-title {
  font-size: 1rem;
  color: #e2e8f0;
  margin: 0 0 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
&lt;/style&gt;