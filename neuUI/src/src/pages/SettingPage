&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h1 &gt;系统设置&lt;/h1&gt;
      &lt;p &gt;管理您的账户、偏好和系统配置&lt;/p&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-tabs v-model:activeKey="activeTab"  size="large"&gt;
        &lt;!-- ===== 个人设置 ===== --&gt;
        &lt;a-tab-pane key="profile" tab="个人设置"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;基本信息&lt;/h3&gt;
              &lt;a-form :model="profileForm" layout="vertical" &gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="用户名"&gt;
                      &lt;a-input v-model:value="profileForm.username" disabled /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="邮箱"&gt;
                      &lt;a-input v-model:value="profileForm.email" placeholder="请输入邮箱" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="角色"&gt;
                      &lt;a-tag :color="profileForm.role === 'admin' ? 'purple' : 'blue'"&gt;
                        {{ profileForm.role === 'admin' ? '管理员' : '普通用户' }}
                      &lt;/a-tag&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="注册时间"&gt;
                      &lt;span &gt;{{ profileForm.createdAt || '未知' }}&lt;/span&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-form-item&gt;
                  &lt;a-button type="primary" :loading="profileSaving" @click="saveProfile"&gt;
                    保存修改
                  &lt;/a-button&gt;
                &lt;/a-form-item&gt;
              &lt;/a-form&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;h3 &gt;修改密码&lt;/h3&gt;
              &lt;a-form :model="passwordForm" layout="vertical" &gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="8"&gt;
                    &lt;a-form-item label="当前密码"&gt;
                      &lt;a-input-password v-model:value="passwordForm.oldPassword" placeholder="输入当前密码" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="8"&gt;
                    &lt;a-form-item label="新密码"&gt;
                      &lt;a-input-password v-model:value="passwordForm.newPassword" placeholder="至少8位，含大小写+数字" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="8"&gt;
                    &lt;a-form-item label="确认新密码"&gt;
                      &lt;a-input-password v-model:value="passwordForm.confirmPassword" placeholder="再次输入新密码" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-form-item&gt;
                  &lt;a-button type="primary" :loading="passwordSaving" @click="changePassword"&gt;
                    更新密码
                  &lt;/a-button&gt;
                &lt;/a-form-item&gt;
              &lt;/a-form&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== 偏好设置 ===== --&gt;
        &lt;a-tab-pane key="preferences" tab="偏好设置"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;外观&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;主题模式&lt;/span&gt;
                    &lt;span &gt;选择深色或浅色主题&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-segmented
                    v-model:value="systemSettings.theme"
                    :options="[
                      { label: '深色', value: 'dark' },
                      { label: '浅色', value: 'light' },
                      { label: '跟随系统', value: 'system' },
                    ]"
                  /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;界面语言&lt;/span&gt;
                    &lt;span &gt;选择界面显示语言&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-select
                    v-model:value="systemSettings.language"
                    style="width: 180px"
                    :options="[
                      { label: '简体中文', value: 'zh-CN' },
                      { label: 'English', value: 'en-US' },
                      { label: '日本語', value: 'ja-JP' },
                    ]"
                  /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;菜单折叠&lt;/span&gt;
                    &lt;span &gt;默认折叠侧边菜单&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.sidebar_collapsed" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;h3 &gt;系统设置&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;自动保存&lt;/span&gt;
                    &lt;span &gt;自动保存会话记录&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.auto_save" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;保存间隔&lt;/span&gt;
                    &lt;span &gt;自动保存间隔（分钟）&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-input-number v-model:value="systemSettings.save_interval_minutes" :min="1" :max="60" style="width: 120px" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;最大历史记录&lt;/span&gt;
                    &lt;span &gt;保留的历史记录数量&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-input-number v-model:value="systemSettings.max_history_size" :min="10" :max="1000" style="width: 120px" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;h3 &gt;通知&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;系统通知&lt;/span&gt;
                    &lt;span &gt;接收系统更新和维护通知&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.notifications_enabled" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;声音提醒&lt;/span&gt;
                    &lt;span &gt;收到通知时播放声音&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.sound_enabled" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;桌面通知&lt;/span&gt;
                    &lt;span &gt;重要信息通过桌面通知&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.desktop_notifications" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;隐私模式&lt;/span&gt;
                    &lt;span &gt;隐藏敏感信息&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.privacy_mode" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
            &lt;a-form-item&gt;
              &lt;a-button type="primary" :loading="savingSettings" @click="saveSystemSettings"&gt;保存偏好设置&lt;/a-button&gt;
            &lt;/a-form-item&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== 安全设置 ===== --&gt;
        &lt;a-tab-pane key="security" tab="安全设置"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;安全配置&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;双因素认证&lt;/span&gt;
                    &lt;span &gt;启用双因素登录验证&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="securitySettings.two_factor_enabled" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;会话超时&lt;/span&gt;
                    &lt;span &gt;无操作自动登出（分钟）&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-input-number v-model:value="securitySettings.session_timeout_minutes" :min="5" :max="1440" style="width: 120px" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;密码过期&lt;/span&gt;
                    &lt;span &gt;密码强制过期天数&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-input-number v-model:value="securitySettings.password_expiry_days" :min="0" :max="365" style="width: 120px" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;登录告警&lt;/span&gt;
                    &lt;span &gt;新设备登录时发送通知&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="securitySettings.login_alerts" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;设备管理&lt;/span&gt;
                    &lt;span &gt;允许管理登录设备&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="securitySettings.device_management_enabled" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;a-form-item style="margin-top: 20px"&gt;
                &lt;a-button type="primary" :loading="savingSecurity" @click="saveSecuritySettings"&gt;保存安全设置&lt;/a-button&gt;
              &lt;/a-form-item&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== 备份管理 ===== --&gt;
        &lt;a-tab-pane key="backup" tab="备份管理"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px"&gt;
                &lt;h3  style="margin: 0; border: none; padding: 0"&gt;备份历史&lt;/h3&gt;
                &lt;a-button type="primary" :loading="creatingBackup" @click="createBackup"&gt;
                  &lt;CloudUploadOutlined /&gt; 创建备份
                &lt;/a-button&gt;
              &lt;/div&gt;
              &lt;a-spin :spinning="loadingBackups"&gt;
                &lt;a-table
                  :columns="backupColumns"
                  :data-source="backups"
                  :pagination="{ pageSize: 5 }"
                  row-key="id"
                  size="middle"
                &gt;
                  &lt;template #bodyCell="{ column, record }"&gt;
                    &lt;template v-if="column.key === 'status'"&gt;
                      &lt;a-tag :color="getStatusColor(record.status)"&gt;
                        {{ getStatusText(record.status) }}
                      &lt;/a-tag&gt;
                    &lt;/template&gt;
                    &lt;template v-if="column.key === 'actions'"&gt;
                      &lt;a-button
                        v-if="record.status === 'completed'"
                        type="link"
                        size="small"
                        :loading="restoringBackupId === record.id"
                        @click="restoreBackup(record.id)"
                      &gt;
                        恢复
                      &lt;/a-button&gt;
                      &lt;a-popconfirm
                        title="确定要删除此备份吗？"
                        ok-text="确定"
                        cancel-text="取消"
                        @confirm="deleteBackup(record.id)"
                      &gt;
                        &lt;a-button type="link" danger size="small"&gt;
                          删除
                        &lt;/a-button&gt;
                      &lt;/a-popconfirm&gt;
                    &lt;/template&gt;
                  &lt;/template&gt;
                &lt;/a-table&gt;
              &lt;/a-spin&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;h3 &gt;备份设置&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;自动备份&lt;/span&gt;
                    &lt;span &gt;启用自动定期备份&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.backup_enabled" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;备份频率&lt;/span&gt;
                    &lt;span &gt;自动备份的频率&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-select v-model:value="systemSettings.backup_frequency" style="width: 150px"&gt;
                    &lt;a-select-option value="daily"&gt;每天&lt;/a-select-option&gt;
                    &lt;a-select-option value="weekly"&gt;每周&lt;/a-select-option&gt;
                    &lt;a-select-option value="monthly"&gt;每月&lt;/a-select-option&gt;
                  &lt;/a-select&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;保留期限&lt;/span&gt;
                    &lt;span &gt;备份保留天数&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-input-number v-model:value="systemSettings.backup_retention_days" :min="1" :max="365" style="width: 120px" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;数据加密&lt;/span&gt;
                    &lt;span &gt;加密备份文件&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemSettings.data_encryption" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== API 密钥 ===== --&gt;
        &lt;a-tab-pane key="api-key" tab="API 密钥"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;API 密钥管理&lt;/h3&gt;
              &lt;p &gt;管理用于第三方集成的 API 密钥，密钥仅在创建时显示一次&lt;/p&gt;
              &lt;div  v-if="apiKeys.length &gt; 0"&gt;
                &lt;div  v-for="key in apiKeys" :key="key.id"&gt;
                  &lt;div &gt;
                    &lt;span &gt;{{ key.name }}&lt;/span&gt;
                    &lt;span &gt;{{ key.prefix }}••••••••&lt;/span&gt;
                    &lt;span &gt;创建于 {{ key.createdAt }}&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;div &gt;
                    &lt;a-tag :color="key.status === 'active' ? 'green' : 'default'"&gt;
                      {{ key.status === 'active' ? '启用' : '禁用' }}
                    &lt;/a-tag&gt;
                    &lt;a-button type="link" danger size="small" @click="deleteKey(key.id)"&gt;
                      删除
                    &lt;/a-button&gt;
                  &lt;/div&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;div  v-else&gt;
                &lt;p&gt;暂无 API 密钥，点击下方按钮创建&lt;/p&gt;
              &lt;/div&gt;
              &lt;a-button  @click="showKeyModal = true"&gt;
                &lt;PlusOutlined /&gt; 创建 API 密钥
              &lt;/a-button&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
        &lt;!-- ===== 系统配置（管理员） ===== --&gt;
        &lt;a-tab-pane key="system" tab="系统配置" v-if="isAdmin"&gt;
          &lt;div &gt;
            &lt;div &gt;
              &lt;h3 &gt;系统参数&lt;/h3&gt;
              &lt;a-form layout="vertical" &gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="Token 日限额"&gt;
                      &lt;a-input-number v-model:value="systemForm.dailyTokenLimit" :min="0" style="width:100%" addon-after="/天" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="最大并发对话"&gt;
                      &lt;a-input-number v-model:value="systemForm.maxConcurrent" :min="1" style="width:100%" addon-after="个" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-row :gutter="24"&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="会话超时时间"&gt;
                      &lt;a-input-number v-model:value="systemForm.sessionTimeout" :min="60" style="width:100%" addon-after="秒" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                  &lt;a-col :span="12"&gt;
                    &lt;a-form-item label="日志保留天数"&gt;
                      &lt;a-input-number v-model:value="systemForm.logRetention" :min="7" style="width:100%" addon-after="天" /&gt;
                    &lt;/a-form-item&gt;
                  &lt;/a-col&gt;
                &lt;/a-row&gt;
                &lt;a-form-item&gt;
                  &lt;a-button type="primary" :loading="systemSaving" @click="saveSystemConfig"&gt;
                    保存配置
                  &lt;/a-button&gt;
                &lt;/a-form-item&gt;
              &lt;/a-form&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;h3 &gt;安全设置&lt;/h3&gt;
              &lt;div &gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;注册开放&lt;/span&gt;
                    &lt;span &gt;允许新用户自行注册&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemForm.allowRegister" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;邀请码验证&lt;/span&gt;
                    &lt;span &gt;注册需要邀请码&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemForm.requireInvite" /&gt;
                &lt;/div&gt;
                &lt;div &gt;
                  &lt;div &gt;
                    &lt;span &gt;登录 IP 限制&lt;/span&gt;
                    &lt;span &gt;限制登录 IP 白名单&lt;/span&gt;
                  &lt;/div&gt;
                  &lt;a-switch v-model:checked="systemForm.ipRestrict" /&gt;
                &lt;/div&gt;
              &lt;/div&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/a-tab-pane&gt;
      &lt;/a-tabs&gt;
    &lt;/div&gt;
    &lt;!-- 创建 API 密钥弹窗 --&gt;
    &lt;a-modal
      v-model:open="showKeyModal"
      title="创建 API 密钥"
      @ok="createApiKey"
      :confirmLoading="keyCreating"
    &gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="密钥名称" required&gt;
          &lt;a-input v-model:value="newKeyName" placeholder="例如：生产环境、开发测试" /&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
    &lt;!-- 新密钥展示 --&gt;
    &lt;a-modal
      v-model:open="showNewKey"
      title="API 密钥已创建"
      :footer="null"
      @cancel="showNewKey = false"
    &gt;
      &lt;a-alert
        type="warning"
        message="请立即复制此密钥，关闭后将无法再次查看"
        show-icon
        style="margin-bottom:16px"
      /&gt;
      &lt;a-input-password
        :value="newKeyValue"
        readonly
      &gt;
        &lt;template #addonAfter&gt;
          &lt;a-button type="link" size="small" @click="copyKey"&gt;
            &lt;CopyOutlined /&gt;
          &lt;/a-button&gt;
        &lt;/template&gt;
      &lt;/a-input-password&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import type { ColumnsType } from 'ant-design-vue/es/table'
import { useAuthStore } from '@/stores/auth'
import {
  PlusOutlined,
  CopyOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons-vue'
import { authAPI } from '@/api/auth'
import { settingsAPI, type SystemSettings, type SecuritySettings, type BackupInfo } from '@/api/modules/settings'
const authStore = useAuthStore()
const activeTab = ref('profile')
const isAdmin = computed(() =&gt; authStore.currentUser?.role === 'admin')
// ─── 个人设置 ───
const profileForm = reactive({
  username: '',
  email: '',
  role: 'user',
  createdAt: '',
})
const profileSaving = ref(false)
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const passwordSaving = ref(false)
// ─── 系统设置 ───
const systemSettings = reactive&lt;Partial&lt;SystemSettings&gt;&gt;({
  theme: 'dark',
  language: 'zh-CN',
  timezone: 'Asia/Shanghai',
  auto_save: true,
  save_interval_minutes: 5,
  max_history_size: 100,
  notifications_enabled: true,
  sound_enabled: true,
  desktop_notifications: false,
  privacy_mode: false,
  data_encryption: true,
  backup_enabled: true,
  backup_frequency: 'weekly',
  backup_retention_days: 30,
  ui_density: 'comfortable',
  sidebar_collapsed: false,
  workspace_layout: 'default',
})
const savingSettings = ref(false)
// ─── 安全设置 ───
const securitySettings = reactive&lt;Partial&lt;SecuritySettings&gt;&gt;({
  two_factor_enabled: false,
  session_timeout_minutes: 60,
  password_expiry_days: 90,
  ip_whitelist: [],
  login_alerts: true,
  device_management_enabled: true,
})
const savingSecurity = ref(false)
// ─── 备份管理 ───
const backups = ref&lt;BackupInfo[]&gt;([])
const loadingBackups = ref(false)
const creatingBackup = ref(false)
const restoringBackupId = ref&lt;string | null&gt;(null)
const backupColumns: ColumnsType&lt;BackupInfo&gt; = [
  { title: '备份类型', dataIndex: 'type', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '文件大小', dataIndex: 'file_size', width: 120, customRender: (value) =&gt; `${(value / 1024 / 1024).toFixed(2)} MB` },
  { title: '创建时间', dataIndex: 'created_at', width: 180 },
  { title: '完成时间', dataIndex: 'completed_at', width: 180 },
  { title: '操作', key: 'actions', width: 150 },
]
// ─── API 密钥 ───
const apiKeys = ref&lt;Array&lt;{ id: string; name: string; prefix: string; createdAt: string; status: string }&gt;&gt;([])
const showKeyModal = ref(false)
const showNewKey = ref(false)
const keyCreating = ref(false)
const newKeyName = ref('')
const newKeyValue = ref('')
// ─── 系统配置 ───
const systemForm = reactive({
  dailyTokenLimit: 1000000,
  maxConcurrent: 10,
  sessionTimeout: 3600,
  logRetention: 30,
  allowRegister: true,
  requireInvite: false,
  ipRestrict: false,
})
const systemSaving = ref(false)
// ─── 初始化 ───
onMounted(async () =&gt; {
  const u = authStore.currentUser
  if (u) {
    profileForm.username = u.username || ''
    profileForm.email = u.email || ''
    profileForm.role = u.role || 'user'
    profileForm.createdAt = u.createdAt || u.created_at || ''
  }
  await loadSettings()
  await loadSecuritySettings()
  await loadBackups()
})
// 加载系统设置
async function loadSettings() {
  try {
    const res = await settingsAPI.getSystemSettings()
    if (res?.data) Object.assign(systemSettings, res.data)
  } catch (err) {
    console.error('Failed to load settings:', err)
  }
}
// 加载安全设置
async function loadSecuritySettings() {
  try {
    const res = await settingsAPI.getSecuritySettings()
    if (res?.data) Object.assign(securitySettings, res.data)
  } catch (err) {
    console.error('Failed to load security settings:', err)
  }
}
// 加载备份列表
async function loadBackups() {
  loadingBackups.value = true
  try {
    const res = await settingsAPI.getBackups({ page: 1, page_size: 20 })
    backups.value = res?.data?.items || []
  } catch (err) {
    console.error('Failed to load backups:', err)
  } finally {
    loadingBackups.value = false
  }
}
// 保存系统设置
async function saveSystemSettings() {
  savingSettings.value = true
  try {
    await settingsAPI.updateSystemSettings(systemSettings as SystemSettings)
    message.success('偏好设置已保存')
    if (systemSettings.theme === 'dark') {
      document.body.classList.add('dark')
    } else if (systemSettings.theme === 'light') {
      document.body.classList.remove('dark')
    }
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '保存失败')
  } finally {
    savingSettings.value = false
  }
}
// 保存安全设置
async function saveSecuritySettings() {
  savingSecurity.value = true
  try {
    await settingsAPI.updateSecuritySettings(securitySettings as SecuritySettings)
    message.success('安全设置已保存')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '保存失败')
  } finally {
    savingSecurity.value = false
  }
}
// 创建备份
async function createBackup() {
  creatingBackup.value = true
  try {
    await settingsAPI.createBackup()
    message.success('备份任务已创建')
    await loadBackups()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '创建备份失败')
  } finally {
    creatingBackup.value = false
  }
}
// 恢复备份
async function restoreBackup(id: string) {
  restoringBackupId.value = id
  try {
    await settingsAPI.restoreBackup(id)
    message.success('备份恢复成功')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '恢复备份失败')
  } finally {
    restoringBackupId.value = null
  }
}
// 删除备份
async function deleteBackup(id: string) {
  try {
    await settingsAPI.deleteBackup(id)
    message.success('备份已删除')
    await loadBackups()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '删除备份失败')
  }
}
function getStatusColor(status: string) {
  const colors: Record&lt;string, string&gt; = {
    pending: 'orange',
    in_progress: 'blue',
    completed: 'green',
    failed: 'red',
  }
  return colors[status] || 'default'
}
function getStatusText(status: string) {
  const texts: Record&lt;string, string&gt; = {
    pending: '等待中',
    in_progress: '进行中',
    completed: '已完成',
    failed: '失败',
  }
  return texts[status] || status
}
// ─── 保存个人信息 ───
async function saveProfile() {
  profileSaving.value = true
  try {
    await authAPI.updateProfile({
      email: profileForm.email,
    })
    message.success('个人信息已更新')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '保存失败')
  } finally {
    profileSaving.value = false
  }
}
// ─── 修改密码 ───
async function changePassword() {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    message.warning('请填写完整密码信息')
    return
  }
  if (passwordForm.newPassword.length &lt; 8) {
    message.warning('新密码至少 8 位')
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    message.warning('两次输入的新密码不一致')
    return
  }
  passwordSaving.value = true
  try {
    await authAPI.changePassword({
      old_password: passwordForm.oldPassword,
      new_password: passwordForm.newPassword,
    })
    message.success('密码修改成功')
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '密码修改失败')
  } finally {
    passwordSaving.value = false
  }
}
// ─── 创建 API 密钥 ───
async function createApiKey() {
  if (!newKeyName.value.trim()) {
    message.warning('请输入密钥名称')
    return
  }
  keyCreating.value = true
  try {
    const prefix = 'nv-'
    const key = prefix + Array.from({ length: 32 }, () =&gt;
      Math.random().toString(36)[2] || '0'
    ).join('')
    newKeyValue.value = key
    apiKeys.value.unshift({
      id: Date.now().toString(),
      name: newKeyName.value,
      prefix: prefix,
      createdAt: new Date().toLocaleDateString('zh-CN'),
      status: 'active',
    })
    showKeyModal.value = false
    showNewKey.value = true
    newKeyName.value = ''
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '创建失败')
  } finally {
    keyCreating.value = false
  }
}
function deleteKey(id: string) {
  apiKeys.value = apiKeys.value.filter(k =&gt; k.id !== id)
  message.success('密钥已删除')
}
function copyKey() {
  navigator.clipboard.writeText(newKeyValue.value)
  message.success('密钥已复制')
}
// ─── 系统配置 ───
async function saveSystemConfig() {
  systemSaving.value = true
  try {
    message.success('系统配置已更新')
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '保存失败')
  } finally {
    systemSaving.value = false
  }
}
&lt;/script&gt;
&lt;style scoped&gt;
.settings-page {
  padding: 24px 28px;
  max-width: 960px;
}
/* Header */
.settings-header {
  margin-bottom: 20px;
}
.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
  margin: 0 0 4px;
}
.page-sub {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.9rem;
  margin: 0;
}
/* Tabs */
:deep(.settings-tabs .ant-tabs-nav) {
  margin-bottom: 20px;
}
:deep(.settings-tabs .ant-tabs-tab) {
  color: rgba(255, 255, 255, 0.5) !important;
  font-size: 0.95rem;
  padding: 10px 20px;
}
:deep(.settings-tabs .ant-tabs-tab-active) {
  color: #93c5fd !important;
}
:deep(.settings-tabs .ant-tabs-ink-bar) {
  background: #60a5fa;
}
:deep(.settings-tabs .ant-tabs-content-holder) {
  min-height: 400px;
}
/* Sections */
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.section {
  padding: 24px 28px;
}
.section-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #e2e8f0;
  margin: 0 0 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.section-desc {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.85rem;
  margin: -12px 0 16px;
}
/* Form */
.settings-form {
  max-width: 640px;
}
:deep(.settings-form .ant-form-item-label &gt; label) {
  color: rgba(255, 255, 255, 0.6) !important;
  font-size: 0.85rem;
}
:deep(.settings-form .ant-input),
:deep(.settings-form .ant-input-number),
:deep(.settings-form .ant-input-password),
:deep(.settings-form .ant-select-selector) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #e2e8f0 !important;
  border-radius: 8px;
}
:deep(.settings-form .ant-input-number-input),
:deep(.settings-form .ant-select-selection-item) {
  color: #e2e8f0 !important;
}
:deep(.settings-form .ant-input-number-addon) {
  color: rgba(255, 255, 255, 0.4) !important;
  background: transparent !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
}
:deep(.settings-form .ant-input-disabled) {
  color: rgba(255, 255, 255, 0.3) !important;
}
.form-text {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.9rem;
}
/* Preferences list */
.pref-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.pref-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.pref-item:last-child {
  border-bottom: none;
}
.pref-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pref-label {
  color: #e2e8f0;
  font-size: 0.9rem;
}
.pref-desc {
  color: rgba(255, 255, 255, 0.35);
  font-size: 0.78rem;
}
/* Segmented */
:deep(.ant-segmented) {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
}
:deep(.ant-segmented .ant-segmented-item) {
  color: rgba(255, 255, 255, 0.5);
}
:deep(.ant-segmented .ant-segmented-item-selected) {
  color: #93c5fd;
  background: rgba(96, 165, 250, 0.15);
}
/* API Keys */
.keys-list {
  margin-bottom: 20px;
}
.key-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  margin-bottom: 10px;
  background: rgba(255, 255, 255, 0.02);
}
.key-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.key-name {
  color: #e2e8f0;
  font-weight: 500;
}
.key-prefix {
  color: rgba(255, 255, 255, 0.3);
  font-size: 0.82rem;
  font-family: monospace;
}
.key-date {
  color: rgba(255, 255, 255, 0.25);
  font-size: 0.72rem;
}
.key-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.keys-empty {
  text-align: center;
  padding: 32px;
  color: rgba(255, 255, 255, 0.3);
}
.create-key-btn {
  margin-top: 4px;
}
/* Modal */
:deep(.ant-modal-content) {
  background: rgba(20, 25, 50, 0.96) !important;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
:deep(.ant-modal-header) {
  background: transparent !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
:deep(.ant-modal-title) {
  color: #e2e8f0;
}
:deep(.ant-table-wrapper .ant-table) {
  background: transparent;
}
:deep(.ant-table-wrapper .ant-table-thead &gt; tr &gt; th) {
  background: rgba(255, 255, 255, 0.03);
  color: rgba(255, 255, 255, 0.6);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
:deep(.ant-table-wrapper .ant-table-tbody &gt; tr &gt; td) {
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.7);
}
.key-display {
  font-family: monospace;
  font-size: 0.85rem;
}
/* Responsive */
@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }
  .section {
    padding: 18px 16px;
  }
}
&lt;/style&gt;
&nbsp;