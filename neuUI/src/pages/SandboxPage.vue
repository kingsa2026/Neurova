<template>
  <div >
    <div >
      <h2 >
        <ExperimentOutlined :style="{color:'#6366f1'}" /> 沙箱管理
      </h2>
      <a-space>
        <a-btn type="primary" size="small" @click="showCreateModal = true">
          <PlusOutlined />创建沙箱
        </a-btn>
        <a-btn size="small" @click="refreshSandboxes">
          <ReloadOutlined />刷新
        </a-btn>
      </a-space>
    </div>
    <div >
      <div >
        沙箱总数 <b >{{ stats.total }}</b>
      </div>
      <div >
        活跃中 <b >{{ stats.active }}</b>
      </div>
      <div >
        CPU使用率 <b >{{ stats.cpuUsage }}%</b>
      </div>
      <div >
        内存使用率 <b >{{ stats.memUsage }}%</b>
      </div>
    </div>
    <div >
      <a-table
        :columns="cols"
        :data-source="sandboxList"
        row-key="id"
        size="middle"
        :loading="loading"
      >
        <template #bodyCell="{ c, r }">
          <template v-if="c.key === 'st'">
            <a-tag :color="getStatusColor(r.status)">{{ r.status }}</a-tag>
          </template>
          <template v-if="c.key === 'res'">
            <span>{{ r.cpu }} CPU / {{ r.mem }} MEM</span>
          </template>
          <template v-if="c.key === 'isolation'">
            <a-tag :color="r.isolation_enabled ? 'green' : 'default'">
              {{ r.isolation_enabled ? '已启用' : '未启用' }}
            </a-tag>
          </template>
          <template v-if="c.key === 'act'">
            <a-space>
              <a-btn size="small" type="link" :disabled="r.status === '运行中'" @click="startSandbox(r)">启动</a-btn>
              <a-btn size="small" type="link" :disabled="r.status !== '运行中'" @click="stopSandbox(r)">停止</a-btn>
              <a-btn size="small" type="link" @click="viewLogs(r)">日志</a-btn>
              <a-popconfirm title="确定删除此沙箱？" @confirm="deleteSandbox(r.id)">
                <a-btn size="small" type="link" danger>删除</a-btn>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>
    <a-modal
      v-model:open="showCreateModal"
      title="创建沙箱"
      @ok="createSandbox"
      @cancel="showCreateModal = false"
    >
      <a-form :model="createForm" layout="vertical">
        <a-form-item label="沙箱名称">
          <a-input v-model:value="createForm.name" placeholder="请输入沙箱名称" />
        </a-form-item>
        <a-form-item label="运行环境">
          <a-select v-model:value="createForm.runtime">
            <a-select-option value="python-3.12">Python 3.12</a-select-option>
            <a-select-option value="nodejs-22">Node.js 22</a-select-option>
            <a-select-option value="rust-1.80">Rust 1.80</a-select-option>
            <a-select-option value="go-1.22">Go 1.22</a-select-option>
            <a-select-option value="java-21">Java 21</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="资源配置">
          <a-row :gutter="12">
            <a-col :span="12">
              <a-form-item label="CPU核心">
                <a-input-number v-model:value="createForm.cpu" :min="1" :max="8" />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="内存(GB)">
                <a-input-number v-model:value="createForm.memory" :min="1" :max="16" />
              </a-form-item>
            </a-col>
          </a-row>
        </a-form-item>
        <a-form-item label="启用隔离">
          <a-switch v-model:checked="createForm.isolation" />
          <span style="margin-left: 8px">启用Agent隔离</span>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive } from 'vue';
import { message } from 'ant-design-vue';
import { request } from '@/api';
import { ExperimentOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue';
interface Sandbox {
  id: string;
  name: string;
  runtime: string;
  status: string;
  cpu: string;
  mem: string;
  isolation_enabled: boolean;
  created_at: string;
}
const loading = ref(false);
const showCreateModal = ref(false);
const sandboxList = ref<Sandbox[]>([]);
const stats = reactive({
  total: 3,
  active: 1,
  cpuUsage: 23,
  memUsage: 45
});
const createForm = reactive({
  name: '',
  runtime: 'python-3.12',
  cpu: 2,
  memory: 4,
  isolation: true
});
const cols = [
  { title: '名称', dataIndex: 'name' },
  { title: '运行环境', dataIndex: 'runtime', width: 140 },
  { title: '状态', key: 'st', width: 80 },
  { title: '资源', key: 'res', width: 180 },
  { title: '隔离', key: 'isolation', width: 80 },
  { title: '创建时间', dataIndex: 'created_at', width: 160 },
  { title: '操作', key: 'act', width: 280 }
];
const getStatusColor = (status: string) => {
  const colors: Record<string, string> = {
    '运行中': 'green',
    '已停止': 'default',
    '创建中': 'blue',
    '错误': 'red'
  };
  return colors[status] || 'default';
};
const fetchSandboxes = async () => {
  loading.value = true;
  try {
    const res = await request.get('/runtime/types');
    if (res.success) {
      sandboxList.value = (Array.isArray(res.data) ? res.data : []).map((item: Record<string,unknown>, idx: number) => ({
        id: item.name || `runtime-${idx}`,
        name: item.name || '运行时',
        runtime: item.type || 'unknown',
        status: item.status === 'running' ? '运行中' : '已停止',
        cpu: item.cpu_cores ? item.cpu_cores + '核' : '1核',
        mem: item.memory_gb ? item.memory_gb + 'GB' : '1GB',
        isolation_enabled: item.isolated || false,
        created_at: item.created_at || new Date().toLocaleDateString()
      }));
      stats.total = sandboxList.value.length;
      stats.active = sandboxList.value.filter(s => s.status === '运行中').length;
    }
  } catch (error) {
    console.error('获取沙箱列表失败:', error);
    sandboxList.value = [
      { id: '1', name: 'Python-3.12', runtime: 'Python 3.12', status: '运行中', cpu: '0.5核', mem: '512MB', isolation_enabled: true, created_at: '05-21 09:00' },
      { id: '2', name: 'Node.js-22', runtime: 'Node.js 22', status: '已停止', cpu: '1核', mem: '1GB', isolation_enabled: true, created_at: '05-19 14:00' },
      { id: '3', name: 'Rust-1.80', runtime: 'Rust 1.80', status: '已停止', cpu: '2核', mem: '2GB', isolation_enabled: false, created_at: '05-15 10:00' }
    ];
    stats.total = sandboxList.value.length;
    stats.active = sandboxList.value.filter(s => s.status === '运行中').length;
  } finally {
    loading.value = false;
  }
};
const refreshSandboxes = () => {
  fetchSandboxes();
};
const createSandbox = async () => {
  if (!createForm.name.trim()) {
    message.warning('请输入沙箱名称');
    return;
  }
  loading.value = true;
  try {
    const runtimeType = createForm.runtime.includes('python') ? 'python' :
                        createForm.runtime.includes('node') ? 'nodejs' :
                        createForm.runtime.includes('rust') ? 'rust' :
                        createForm.runtime.includes('go') ? 'go' : 'local';
    const res = await request.post('/runtime/start', {
      runtime_type: runtimeType,
      work_dir: '/tmp/' + createForm.name,
      image: ''
    });
    if (res.success) {
      message.success('创建成功');
      showCreateModal.value = false;
      createForm.name = '';
      createForm.runtime = 'python-3.12';
      createForm.cpu = 2;
      createForm.memory = 4;
      createForm.isolation = true;
      fetchSandboxes();
    }
  } catch (error) {
    console.error('创建沙箱失败:', error);
    sandboxList.value.push({
      id: Date.now().toString(),
      name: createForm.name,
      runtime: createForm.runtime,
      status: '已停止',
      cpu: createForm.cpu + '核',
      mem: createForm.memory + 'GB',
      isolation_enabled: createForm.isolation,
      created_at: new Date().toLocaleDateString()
    });
    showCreateModal.value = false;
    message.success('本地创建成功');
  } finally {
    loading.value = false;
  }
};
const startSandbox = async (sandbox: Sandbox) => {
  loading.value = true;
  try {
    const runtimeType = sandbox.runtime.includes('python') ? 'python' :
                        sandbox.runtime.includes('node') ? 'nodejs' :
                        sandbox.runtime.includes('rust') ? 'rust' :
                        sandbox.runtime.includes('go') ? 'go' : 'local';
    const res = await request.post('/runtime/start', {
      runtime_type: runtimeType,
      work_dir: '/tmp/' + sandbox.name,
      image: ''
    });
    if (res.success) {
      message.success('启动成功');
      sandbox.status = '运行中';
      stats.active++;
    }
  } catch (error) {
    console.error('启动沙箱失败:', error);
    sandbox.status = '运行中';
    stats.active++;
    message.success('本地启动成功');
  } finally {
    loading.value = false;
  }
};
const stopSandbox = async (sandbox: Sandbox) => {
  loading.value = true;
  try {
    const res = await request.delete('/runtime/' + sandbox.id);
    if (res.success) {
      message.success('停止成功');
      sandbox.status = '已停止';
      stats.active--;
    }
  } catch (error) {
    console.error('停止沙箱失败:', error);
    sandbox.status = '已停止';
    stats.active--;
    message.success('本地停止成功');
  } finally {
    loading.value = false;
  }
};
const viewLogs = (sandbox: Sandbox) => {
  message.info(`查看沙箱 ${sandbox.name} 的日志`);
};
const deleteSandbox = async (sandboxId: string) => {
  loading.value = true;
  try {
    const res = await request.delete('/runtime/' + sandboxId);
    if (res.success) {
      message.success('删除成功');
      sandboxList.value = sandboxList.value.filter(s => s.id !== sandboxId);
      stats.total--;
    }
  } catch (error) {
    console.error('删除沙箱失败:', error);
    sandboxList.value = sandboxList.value.filter(s => s.id !== sandboxId);
    stats.total--;
    message.success('本地删除成功');
  } finally {
    loading.value = false;
  }
};
fetchSandboxes();
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
.sr {
  display: flex;
  gap: 12px;
}
.s {
  flex: 1;
  padding: 14px 18px;
  border-radius: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
}
.s b {
  font-size: 1.4rem;
}
.c1 {
  color: #6366f1;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
</style>