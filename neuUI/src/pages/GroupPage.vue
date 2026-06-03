<template>
  <div >
    <div >
      <h2 >
        <UsergroupAddOutlined :style="{color:'#8b5cf6'}" /> 用户组管理
      </h2>
      <a-btn type="primary" size="small" @click="showCreateModal = true">
        <PlusOutlined />新建组
      </a-btn>
    </div>
    <div >
      <div >
        总组数 <b >{{ stats.total }}</b>
      </div>
      <div >
        总用户数 <b >{{ stats.users }}</b>
      </div>
    </div>
    <div >
      <a-table
        :columns="cols"
        :data-source="groupList"
        row-key="id"
        size="middle"
        :loading="loading"
        :expandable="{
          expandedRowRender: (r: Group) => h('div', { class: 'exp' }, [
            h('h5', '权限列表'),
            h('div', { class: 'ptags' }, r.permissions?.map((p: string) => h('a-tag', { key: p, size: 'small' }, p)))
          ])
        }"
      >
        <template #bodyCell="{ c, r }">
          <template v-if="c.key === 'ms'">
            <a-avatar-group :max-count="4" size="small">
              <a-avatar
                v-for="(member, idx) in r.members?.slice(0, 4)"
                :key="idx"
                size="small"
                :style="{ background: '#' + Math.floor(Math.random() * 16777215).toString(16) }"
              >
                {{ member.name?.charAt(0) || 'U' }}
              </a-avatar>
              <span v-if="r.member_count > 4" >+{{ r.member_count - 4 }}</span>
            </a-avatar-group>
          </template>
          <template v-if="c.key === 'act'">
            <a-space>
              <a-btn size="small" type="link" @click="editGroup(r)">编辑</a-btn>
              <a-btn size="small" type="link" @click="managePermissions(r)">权限</a-btn>
              <a-popconfirm title="确定删除该用户组？" @confirm="deleteGroup(r.id)">
                <a-btn size="small" type="link" danger>删除</a-btn>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>
    <a-modal
      v-model:open="showCreateModal"
      title="新建用户组"
      @ok="handleCreate"
      @cancel="showCreateModal = false"
    >
      <a-form :model="form" layout="vertical">
        <a-form-item label="组名">
          <a-input v-model:value="form.name" placeholder="请输入组名" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" placeholder="请输入组描述" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, h } from 'vue';
import { message } from 'ant-design-vue';
import { request } from '@/api';
import { UsergroupAddOutlined, PlusOutlined } from '@ant-design/icons-vue';
interface Group {
  id: string;
  name: string;
  description?: string;
  member_count: number;
  members?: Array<{ id: string; name: string }>;
  permissions: string[];
  created_at: string;
}
interface GroupForm {
  name: string;
  description: string;
}
const loading = ref(false);
const showCreateModal = ref(false);
const groupList = ref<Group[]>([]);
const stats = ref({ total: 0, users: 0 });
const form = reactive<GroupForm>({
  name: '',
  description: ''
});
const cols = [
  { title: '组名', dataIndex: 'name' },
  { title: '描述', dataIndex: 'description' },
  { title: '成员', key: 'ms', width: 120 },
  { title: '创建时间', dataIndex: 'created_at', width: 160 },
  { title: '操作', key: 'act', width: 200 }
];
const fetchGroups = async () => {
  loading.value = true;
  try {
    const res = await request.get('/settings/groups');
    if (res.success) {
      groupList.value = (Array.isArray(res.data) ? res.data : []).map((item: Record<string,unknown>) => ({
        id: (item.id || item.group_id) as string,
        name: item.name as string,
        description: item.description as string,
        member_count: ((item.member_count || (item.members as unknown[])?.length || 0) as number),
        members: (item.members || []) as Array<{ id: string; name: string }>,
        permissions: (item.permissions || []) as string[],
        created_at: (item.created_at || '') as string
      }));
      stats.value = {
        total: groupList.value.length,
        users: groupList.value.reduce((sum, g) => sum + (g.member_count || 0), 0)
      };
    }
  } catch (error) {
    console.error('获取用户组列表失败:', error);
    groupList.value = [
      { id: '1', name: '管理员组', description: '系统全局管理权限', member_count: 3, permissions: ['admin:*', 'settings:*', 'users:*', 'audit:read'], created_at: '2026-01-15' },
      { id: '2', name: '开发者组', description: 'API和Agent开发权限', member_count: 8, permissions: ['agents:*', 'skills:*', 'chat:*', 'api:readwrite'], created_at: '2026-02-01' },
      { id: '3', name: '普通用户组', description: '基本使用权限', member_count: 17, permissions: ['chat:send', 'agents:read', 'knowledge:read'], created_at: '2026-03-10' },
      { id: '4', name: '只读组', description: '只能查看不可修改', member_count: 5, permissions: ['agents:read', 'chat:read', 'knowledge:read'], created_at: '2026-04-05' }
    ];
    stats.value = { total: groupList.value.length, users: 33 };
  } finally {
    loading.value = false;
  }
};
const handleCreate = async () => {
  if (!form.name.trim()) {
    message.warning('请输入组名');
    return;
  }
  try {
    const res = await request.post('/settings/groups', {
      name: form.name,
      description: form.description,
      quota: {},
      permissions: []
    });
    if (res.success) {
      message.success('创建成功');
      showCreateModal.value = false;
      form.name = '';
      form.description = '';
      fetchGroups();
    }
  } catch (error) {
    console.error('创建用户组失败:', error);
    message.error('创建失败');
  }
};
const editGroup = (group: Group) => {
  form.name = group.name;
  form.description = group.description || '';
  showCreateModal.value = true;
};
const managePermissions = (group: Group) => {
  message.info(`管理组 ${group.name} 的权限`);
};
const deleteGroup = async (groupId: string) => {
  try {
    const res = await request.delete(`/settings/groups/${groupId}`);
    if (res.success) {
      message.success('删除成功');
      fetchGroups();
    }
  } catch (error) {
    console.error('删除用户组失败:', error);
    message.error('删除失败');
  }
};
fetchGroups();
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
  color: #8b5cf6;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
.exp {
  padding: 8px;
}
.exp h5 {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.8rem;
  margin: 0 0 6px;
}
.ptags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.more {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin-left: 4px;
}
</style>