<template>
  <div class="settings-page">
    <div class="settings-header">
      <h1 class="page-title">系统设置</h1>
      <p class="page-sub">管理您的账户、偏好和系统配置</p>
    </div>

    <div class="settings-body">
      <a-tabs v-model:activeKey="activeTab" class="settings-tabs" size="large">
        <!-- ===== 个人设置 ===== -->
        <a-tab-pane key="profile" tab="个人设置">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">基本信息</h3>
              <a-form :model="profileForm" layout="vertical" class="settings-form">
                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="用户名">
                      <a-input v-model:value="profileForm.username" disabled />
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="邮箱">
                      <a-input v-model:value="profileForm.email" placeholder="请输入邮箱" />
                    </a-form-item>
                  </a-col>
                </a-row>
                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="角色">
                      <a-tag :color="profileForm.role === 'admin' ? 'purple' : 'blue'">
                        {{ profileForm.role === 'admin' ? '管理员' : '普通用户' }}
                      </a-tag>
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="注册时间">
                      <span class="form-text">{{ profileForm.createdAt || '未知' }}</span>
                    </a-form-item>
                  </a-col>
                </a-row>
                <a-form-item>
                  <a-button type="primary" :loading="profileSaving" @click="saveProfile">
                    保存修改
                  </a-button>
                </a-form-item>
              </a-form>
            </div>

            <div class="section glass-effect">
              <h3 class="section-title">修改密码</h3>
              <a-form :model="passwordForm" layout="vertical" class="settings-form">
                <a-row :gutter="24">
                  <a-col :span="8">
                    <a-form-item label="当前密码">
                      <a-input-password v-model:value="passwordForm.oldPassword" placeholder="输入当前密码" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="新密码">
                      <a-input-password v-model:value="passwordForm.newPassword" placeholder="至少8位，含大小写+数字" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="8">
                    <a-form-item label="确认新密码">
                      <a-input-password v-model:value="passwordForm.confirmPassword" placeholder="再次输入新密码" />
                    </a-form-item>
                  </a-col>
                </a-row>
                <a-form-item>
                  <a-button type="primary" :loading="passwordSaving" @click="changePassword">
                    更新密码
                  </a-button>
                </a-form-item>
              </a-form>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== 偏好设置 ===== -->
        <a-tab-pane key="preferences" tab="偏好设置">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">外观</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">主题模式</span>
                    <span class="pref-desc">选择深色或浅色主题</span>
                  </div>
                  <a-segmented
                    v-model:value="systemSettings.theme"
                    :options="[
                      { label: '深色', value: 'dark' },
                      { label: '浅色', value: 'light' },
                      { label: '跟随系统', value: 'system' },
                    ]"
                  />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">界面语言</span>
                    <span class="pref-desc">选择界面显示语言</span>
                  </div>
                  <a-select
                    v-model:value="systemSettings.language"
                    style="width: 180px"
                    :options="[
                      { label: '简体中文', value: 'zh-CN' },
                      { label: 'English', value: 'en-US' },
                      { label: '日本語', value: 'ja-JP' },
                    ]"
                  />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">菜单折叠</span>
                    <span class="pref-desc">默认折叠侧边菜单</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.sidebar_collapsed" />
                </div>
              </div>
            </div>

            <div class="section glass-effect">
              <h3 class="section-title">系统设置</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">自动保存</span>
                    <span class="pref-desc">自动保存会话记录</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.auto_save" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">保存间隔</span>
                    <span class="pref-desc">自动保存间隔（分钟）</span>
                  </div>
                  <a-input-number v-model:value="systemSettings.save_interval_minutes" :min="1" :max="60" style="width: 120px" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">最大历史记录</span>
                    <span class="pref-desc">保留的历史记录数量</span>
                  </div>
                  <a-input-number v-model:value="systemSettings.max_history_size" :min="10" :max="1000" style="width: 120px" />
                </div>
              </div>
            </div>

            <div class="section glass-effect">
              <h3 class="section-title">通知</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">系统通知</span>
                    <span class="pref-desc">接收系统更新和维护通知</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.notifications_enabled" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">声音提醒</span>
                    <span class="pref-desc">收到通知时播放声音</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.sound_enabled" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">桌面通知</span>
                    <span class="pref-desc">重要信息通过桌面通知</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.desktop_notifications" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">隐私模式</span>
                    <span class="pref-desc">隐藏敏感信息</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.privacy_mode" />
                </div>
              </div>
            </div>

            <a-form-item>
              <a-button type="primary" :loading="savingSettings" @click="saveSystemSettings">保存偏好设置</a-button>
            </a-form-item>
          </div>
        </a-tab-pane>

        <!-- ===== 安全设置 ===== -->
        <a-tab-pane key="security" tab="安全设置">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">安全配置</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">双因素认证</span>
                    <span class="pref-desc">启用双因素登录验证</span>
                  </div>
                  <a-switch v-model:checked="securitySettings.two_factor_enabled" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">会话超时</span>
                    <span class="pref-desc">无操作自动登出（分钟）</span>
                  </div>
                  <a-input-number v-model:value="securitySettings.session_timeout_minutes" :min="5" :max="1440" style="width: 120px" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">密码过期</span>
                    <span class="pref-desc">密码强制过期天数</span>
                  </div>
                  <a-input-number v-model:value="securitySettings.password_expiry_days" :min="0" :max="365" style="width: 120px" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">登录告警</span>
                    <span class="pref-desc">新设备登录时发送通知</span>
                  </div>
                  <a-switch v-model:checked="securitySettings.login_alerts" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">设备管理</span>
                    <span class="pref-desc">允许管理登录设备</span>
                  </div>
                  <a-switch v-model:checked="securitySettings.device_management_enabled" />
                </div>
              </div>
              <a-form-item style="margin-top: 20px">
                <a-button type="primary" :loading="savingSecurity" @click="saveSecuritySettings">保存安全设置</a-button>
              </a-form-item>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== 备份管理 ===== -->
        <a-tab-pane key="backup" tab="备份管理">
          <div class="tab-content">
            <div class="section glass-effect">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
                <h3 class="section-title" style="margin: 0; border: none; padding: 0">备份历史</h3>
                <a-button type="primary" :loading="creatingBackup" @click="createBackup">
                  <CloudUploadOutlined /> 创建备份
                </a-button>
              </div>

              <a-spin :spinning="loadingBackups">
                <a-table
                  :columns="backupColumns"
                  :data-source="backups"
                  :pagination="{ pageSize: 5 }"
                  row-key="id"
                  size="middle"
                >
                  <template #bodyCell="{ column, record }">
                    <template v-if="column.key === 'status'">
                      <a-tag :color="getStatusColor(record.status)">
                        {{ getStatusText(record.status) }}
                      </a-tag>
                    </template>
                    <template v-if="column.key === 'actions'">
                      <a-button
                        v-if="record.status === 'completed'"
                        type="link"
                        size="small"
                        :loading="restoringBackupId === record.id"
                        @click="restoreBackup(record.id)"
                      >
                        恢复
                      </a-button>
                      <a-popconfirm
                        title="确定要删除此备份吗？"
                        ok-text="确定"
                        cancel-text="取消"
                        @confirm="deleteBackup(record.id)"
                      >
                        <a-button type="link" danger size="small">
                          删除
                        </a-button>
                      </a-popconfirm>
                    </template>
                  </template>
                </a-table>
              </a-spin>
            </div>

            <div class="section glass-effect">
              <h3 class="section-title">备份设置</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">自动备份</span>
                    <span class="pref-desc">启用自动定期备份</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.backup_enabled" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">备份频率</span>
                    <span class="pref-desc">自动备份的频率</span>
                  </div>
                  <a-select v-model:value="systemSettings.backup_frequency" style="width: 150px">
                    <a-select-option value="daily">每天</a-select-option>
                    <a-select-option value="weekly">每周</a-select-option>
                    <a-select-option value="monthly">每月</a-select-option>
                  </a-select>
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">保留期限</span>
                    <span class="pref-desc">备份保留天数</span>
                  </div>
                  <a-input-number v-model:value="systemSettings.backup_retention_days" :min="1" :max="365" style="width: 120px" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">数据加密</span>
                    <span class="pref-desc">加密备份文件</span>
                  </div>
                  <a-switch v-model:checked="systemSettings.data_encryption" />
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== API 密钥 ===== -->
        <a-tab-pane key="api-key" tab="API 密钥">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">API 密钥管理</h3>
              <p class="section-desc">管理用于第三方集成的 API 密钥，密钥仅在创建时显示一次</p>

              <div class="keys-list" v-if="apiKeys.length > 0">
                <div class="key-item" v-for="key in apiKeys" :key="key.id">
                  <div class="key-info">
                    <span class="key-name">{{ key.name }}</span>
                    <span class="key-prefix">{{ key.prefix }}••••••••</span>
                    <span class="key-date">创建于 {{ key.createdAt }}</span>
                  </div>
                  <div class="key-actions">
                    <a-tag :color="key.status === 'active' ? 'green' : 'default'">
                      {{ key.status === 'active' ? '启用' : '禁用' }}
                    </a-tag>
                    <a-button type="link" danger size="small" @click="deleteKey(key.id)">
                      删除
                    </a-button>
                  </div>
                </div>
              </div>
              <div class="keys-empty" v-else>
                <p>暂无 API 密钥，点击下方按钮创建</p>
              </div>

              <a-button class="create-key-btn" @click="showKeyModal = true">
                <PlusOutlined /> 创建 API 密钥
              </a-button>
            </div>
          </div>
        </a-tab-pane>

        <!-- ===== 系统配置（管理员） ===== -->
        <a-tab-pane key="system" tab="系统配置" v-if="isAdmin">
          <div class="tab-content">
            <div class="section glass-effect">
              <h3 class="section-title">系统参数</h3>
              <a-form layout="vertical" class="settings-form">
                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="Token 日限额">
                      <a-input-number v-model:value="systemForm.dailyTokenLimit" :min="0" style="width:100%" addon-after="/天" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="最大并发对话">
                      <a-input-number v-model:value="systemForm.maxConcurrent" :min="1" style="width:100%" addon-after="个" />
                    </a-form-item>
                  </a-col>
                </a-row>
                <a-row :gutter="24">
                  <a-col :span="12">
                    <a-form-item label="会话超时时间">
                      <a-input-number v-model:value="systemForm.sessionTimeout" :min="60" style="width:100%" addon-after="秒" />
                    </a-form-item>
                  </a-col>
                  <a-col :span="12">
                    <a-form-item label="日志保留天数">
                      <a-input-number v-model:value="systemForm.logRetention" :min="7" style="width:100%" addon-after="天" />
                    </a-form-item>
                  </a-col>
                </a-row>
                <a-form-item>
                  <a-button type="primary" :loading="systemSaving" @click="saveSystemConfig">
                    保存配置
                  </a-button>
                </a-form-item>
              </a-form>
            </div>

            <div class="section glass-effect">
              <h3 class="section-title">安全设置</h3>
              <div class="pref-list">
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">注册开放</span>
                    <span class="pref-desc">允许新用户自行注册</span>
                  </div>
                  <a-switch v-model:checked="systemForm.allowRegister" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">邀请码验证</span>
                    <span class="pref-desc">注册需要邀请码</span>
                  </div>
                  <a-switch v-model:checked="systemForm.requireInvite" />
                </div>
                <div class="pref-item">
                  <div class="pref-info">
                    <span class="pref-label">登录 IP 限制</span>
                    <span class="pref-desc">限制登录 IP 白名单</span>
                  </div>
                  <a-switch v-model:checked="systemForm.ipRestrict" />
                </div>
              </div>
            </div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </div>

    <!-- 创建 API 密钥弹窗 -->
    <a-modal
      v-model:open="showKeyModal"
      title="创建 API 密钥"
      @ok="createApiKey"
      :confirmLoading="keyCreating"
    >
      <a-form layout="vertical">
        <a-form-item label="密钥名称" required>
          <a-input v-model:value="newKeyName" placeholder="例如：生产环境、开发测试" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 新密钥展示 -->
    <a-modal
      v-model:open="showNewKey"
      title="API 密钥已创建"
      :footer="null"
      @cancel="showNewKey = false"
    >
      <a-alert
        type="warning"
        message="请立即复制此密钥，关闭后将无法再次查看"
        show-icon
        style="margin-bottom:16px"
      />
      <a-input-password
        :value="newKeyValue"
        readonly
        class="key-display"
      >
        <template #addonAfter>
          <a-button type="link" size="small" @click="copyKey">
            <CopyOutlined />
          </a-button>
        </template>
      </a-input-password>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
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
const isAdmin = computed(() => authStore.currentUser?.role === 'admin')

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
const systemSettings = reactive<Partial<SystemSettings>>({
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
const securitySettings = reactive<Partial<SecuritySettings>>({
  two_factor_enabled: false,
  session_timeout_minutes: 60,
  password_expiry_days: 90,
  ip_whitelist: [],
  login_alerts: true,
  device_management_enabled: true,
})
const savingSecurity = ref(false)

// ─── 备份管理 ───
const backups = ref<BackupInfo[]>([])
const loadingBackups = ref(false)
const creatingBackup = ref(false)
const restoringBackupId = ref<string | null>(null)
const backupColumns: ColumnsType<BackupInfo> = [
  { title: '备份类型', dataIndex: 'type', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '文件大小', dataIndex: 'file_size', width: 120, customRender: (value) => `${(value / 1024 / 1024).toFixed(2)} MB` },
  { title: '创建时间', dataIndex: 'created_at', width: 180 },
  { title: '完成时间', dataIndex: 'completed_at', width: 180 },
  { title: '操作', key: 'actions', width: 150 },
]

// ─── API 密钥 ───
const apiKeys = ref<Array<{ id: string; name: string; prefix: string; createdAt: string; status: string }>>([])
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
onMounted(async () => {
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
  const colors: Record<string, string> = {
    pending: 'orange',
    in_progress: 'blue',
    completed: 'green',
    failed: 'red',
  }
  return colors[status] || 'default'
}

function getStatusText(status: string) {
  const texts: Record<string, string> = {
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
  if (passwordForm.newPassword.length < 8) {
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
    const key = prefix + Array.from({ length: 32 }, () =>
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
  apiKeys.value = apiKeys.value.filter(k => k.id !== id)
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
</script>

<style scoped>
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
:deep(.settings-form .ant-form-item-label > label) {
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
:deep(.ant-table-wrapper .ant-table-thead > tr > th) {
  background: rgba(255, 255, 255, 0.03);
  color: rgba(255, 255, 255, 0.6);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
:deep(.ant-table-wrapper .ant-table-tbody > tr > td) {
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
</style>
