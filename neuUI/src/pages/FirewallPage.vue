<template>
  <div >
    <div >
      <h2 >
        <FirewallOutlined :style="{color:'#f97316'}" /> 防火墙管理
      </h2>
      <a-space>
        <a-switch v-model:checked="globalEnabled" @change="toggleGlobal" />
        <span>{{ globalEnabled ? '已启用' : '已禁用' }}</span>
      </a-space>
    </div>
    <div >
      <div >
        <div >
          <ShieldAlertOutlined />
        </div>
        <div >
          <div >{{ stats.blockedRequests }}</div>
          <div >今日拦截</div>
        </div>
      </div>
      <div >
        <div >
          <CheckCircleOutlined />
        </div>
        <div >
          <div >{{ stats.allowedRequests }}</div>
          <div >今日放行</div>
        </div>
      </div>
      <div >
        <div >
          <BanOutlined />
        </div>
        <div >
          <div >{{ stats.blacklistedIPs }}</div>
          <div >黑名单IP</div>
        </div>
      </div>
      <div >
        <div >
          <ClockCircleOutlined />
        </div>
        <div >
          <div >{{ stats.rateLimitHits }}</div>
          <div >触发限流</div>
        </div>
      </div>
    </div>
    <a-tabs default-active-key="rules" :items="tabs" >
      <template #rules>
        <div >
          <div >
            <h3 >全局规则</h3>
            <a-form :model="globalRules" layout="vertical">
              <a-row :gutter="16">
                <a-col :span="8">
                  <a-form-item label="速率限制 (次/分钟)">
                    <a-input-number v-model:value="globalRules.rateLimit" :min="10" :max="1000" />
                  </a-form-item>
                </a-col>
                <a-col :span="8">
                  <a-form-item label="最大请求大小 (MB)">
                    <a-input-number v-model:value="globalRules.maxPayloadMB" :min="1" :max="100" />
                  </a-form-item>
                </a-col>
                <a-col :span="8">
                  <a-form-item label="启用IP过滤">
                    <a-switch v-model:checked="globalRules.enableIPFilter" />
                  </a-form-item>
                </a-col>
              </a-row>
              <a-form-item label="禁止的文件扩展名">
                <a-input
                  v-model:value="globalRules.blockedExtensions"
                  placeholder="逗号分隔，如: .exe,.php,.sh"
                />
              </a-form-item>
              <a-form-item label="禁止的路径模式">
                <a-textarea
                  v-model:value="globalRules.blockedPaths"
                  placeholder="每行一个路径模式"
                  :rows="3"
                />
              </a-form-item>
              <a-form-item>
                <a-btn type="primary" @click="saveGlobalRules">保存全局规则</a-btn>
              </a-form-item>
            </a-form>
          </div>
        </div>
      </template>
      <template #whitelist>
        <div >
          <div >
            <a-input-search
              placeholder="搜索IP"
              v-model:value="ipFilter"
              @search="searchIP"
              style="width: 260px"
            />
            <a-btn type="primary" size="small" @click="showAddIPModal = true">
              <PlusOutlined />添加白名单
            </a-btn>
          </div>
          <a-table
            :columns="ipCols"
            :data-source="whitelistIPs"
            row-key="ip"
            size="small"
          >
            <template #bodyCell="{ c, r }">
              <template v-if="c.key === 'status'">
                <a-tag :color="r.status === 'active' ? 'green' : 'default'">
                  {{ r.status === 'active' ? '活跃' : '禁用' }}
                </a-tag>
              </template>
              <template v-if="c.key === 'actions'">
                <a-space>
                  <a-btn size="small" type="link" @click="toggleIPStatus(r)">
                    {{ r.status === 'active' ? '禁用' : '启用' }}
                  </a-btn>
                  <a-popconfirm title="确定删除此IP？" @confirm="removeIP(r.ip)">
                    <a-btn size="small" type="link" danger>删除</a-btn>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </div>
      </template>
      <template #blacklist>
        <div >
          <a-table
            :columns="blacklistCols"
            :data-source="blacklistIPs"
            row-key="ip"
            size="small"
          >
            <template #bodyCell="{ c, r }">
              <template v-if="c.key === 'reason'">
                <a-tag color="red">{{ r.reason }}</a-tag>
              </template>
              <template v-if="c.key === 'actions'">
                <a-space>
                  <a-btn size="small" type="link" @click="unblockIP(r)">解除封禁</a-btn>
                </a-space>
              </template>
            </template>
          </a-table>
        </div>
      </template>
      <template #logs>
        <div >
          <a-table
            :columns="logCols"
            :data-source="firewallLogs"
            row-key="id"
            size="small"
            :pagination="logPagination"
          >
            <template #bodyCell="{ c, r }">
              <template v-if="c.key === 'action'">
                <a-tag :color="r.action === 'block' ? 'red' : 'green'">
                  {{ r.action === 'block' ? '拦截' : '放行' }}
                </a-tag>
              </template>
              <template v-if="c.key === 'time'">
                {{ formatTime(r.time) }}
              </template>
            </template>
          </a-table>
        </div>
      </template>
    </a-tabs>
    <a-modal
      v-model:open="showAddIPModal"
      title="添加白名单IP"
      @ok="addWhitelistIP"
      @cancel="showAddIPModal = false"
    >
      <a-form :model="newIPForm" layout="vertical">
        <a-form-item label="IP地址">
          <a-input v-model:value="newIPForm.ip" placeholder="请输入IP地址" />
        </a-form-item>
        <a-form-item label="备注">
          <a-input v-model:value="newIPForm.note" placeholder="可选，如：公司办公网" />
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
const whitelistIPs = ref<WhitelistIP[]>([
  { ip: '192.168.1.0/24', note: '内网网段', status: 'active', added_at: '2026-01-15' },
  { ip: '10.0.0.0/8', note: '公司内网', status: 'active', added_at: '2026-02-01' },
  { ip: '172.16.0.0/12', note: '测试环境', status: 'active', added_at: '2026-03-10' },
  { ip: '47.252.31.69', note: '生产服务器', status: 'active', added_at: '2026-04-05' },
  { ip: '127.0.0.1', note: '本地回环', status: 'active', added_at: '2026-01-01' }
]);
const blacklistIPs = ref<BlacklistIP[]>([
  { ip: '10.0.0.5', reason: '暴力破解', blocked_at: '2026-05-24', block_count: 156 },
  { ip: '198.51.100.20', reason: '恶意扫描', blocked_at: '2026-05-23', block_count: 89 },
  { ip: '203.0.113.45', reason: 'DDOS攻击', blocked_at: '2026-05-22', block_count: 456 },
  { ip: '192.0.2.100', reason: '异常请求', blocked_at: '2026-05-21', block_count: 34 }
]);
const firewallLogs = ref<FirewallLog[]>([
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
const toggleGlobal = async () => {
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
const saveGlobalRules = async () => {
  try {
    const res = await request.put('/firewall/global', {
      rate_limit_per_minute: globalRules.rateLimit,
      max_payload_bytes: globalRules.maxPayloadMB * 1024 * 1024,
      blocked_extensions: globalRules.blockedExtensions.split(',').map(s => s.trim()),
      blocked_patterns: globalRules.blockedPaths.split('\n').map(s => s.trim()).filter(Boolean),
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
const searchIP = () => {
  console.log('搜索IP:', ipFilter.value);
};
const addWhitelistIP = async () => {
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
const toggleIPStatus = (item: WhitelistIP) => {
  item.status = item.status === 'active' ? 'disabled' : 'active';
  message.success(`IP ${item.ip} ${item.status === 'active' ? '已启用' : '已禁用'}`);
};
const removeIP = async (ip: string) => {
  try {
    const res = await request.put('/firewall/user/rules', {
      extra_blocked_paths: []
    });
    if (res.success) {
      message.success('删除成功');
      whitelistIPs.value = whitelistIPs.value.filter(item => item.ip !== ip);
    }
  } catch (error) {
    console.error('删除白名单失败:', error);
    whitelistIPs.value = whitelistIPs.value.filter(item => item.ip !== ip);
    message.success('本地删除成功');
  }
};
const unblockIP = async (item: BlacklistIP) => {
  try {
    const res = await request.post('/firewall/user/rules', {
      extra_blocked_paths: []
    });
    if (res.success) {
      message.success('已解除封禁');
      blacklistIPs.value = blacklistIPs.value.filter(i => i.ip !== item.ip);
    }
  } catch (error) {
    console.error('解除封禁失败:', error);
    blacklistIPs.value = blacklistIPs.value.filter(i => i.ip !== item.ip);
    message.success('本地解除成功');
  }
};
const formatTime = (time: string) => {
  try {
    return new Date(time).toLocaleString('zh-CN');
  } catch {
    return time;
  }
};
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
</style>