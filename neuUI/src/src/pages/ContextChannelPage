&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;ShareAltOutlined :style="{ color: '#06b6d4' }" /&gt; 渠道上下文共享&lt;/h2&gt;
      &lt;div &gt;
        &lt;a-button @click="loadConfig" :loading="loading"&gt;&lt;ReloadOutlined /&gt; 刷新&lt;/a-button&gt;
        &lt;a-button type="primary" @click="handleToggleSharing" :loading="saving"&gt;
          {{ sharingConfig.enabled ? '禁用共享' : '启用共享' }}
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;ShareAltOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ sharingConfig.enabled ? '已启用' : '已禁用' }}&lt;/div&gt;
          &lt;div &gt;共享状态&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;LinkOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ sharingConfig.shared_channels?.length || 0 }}&lt;/div&gt;
          &lt;div &gt;共享渠道数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;ApiOutlined  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ availableChannels.length }}&lt;/div&gt;
          &lt;div &gt;可用渠道&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" style="margin-bottom: 16px" /&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;div v-if="!loading" &gt;
      &lt;!-- 共享配置 --&gt;
      &lt;div &gt;
        &lt;h3&gt;&lt;SettingOutlined /&gt; 共享配置&lt;/h3&gt;
        &lt;a-form layout="vertical" style="max-width: 600px"&gt;
          &lt;a-form-item label="共享描述"&gt;
            &lt;a-input v-model:value="sharingConfig.description" placeholder="输入共享配置描述" :disabled="!sharingConfig.enabled" /&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item label="共享渠道"&gt;
            &lt;a-select
              v-model:value="sharingConfig.shared_channels"
              mode="multiple"
              placeholder="选择要共享的渠道"
              :disabled="!sharingConfig.enabled"
              style="width: 100%"
            &gt;
              &lt;a-select-option v-for="ch in availableChannels" :key="ch" :value="ch"&gt;
                {{ getChannelLabel(ch) }}
              &lt;/a-select-option&gt;
            &lt;/a-select&gt;
          &lt;/a-form-item&gt;
          &lt;a-form-item&gt;
            &lt;a-space&gt;
              &lt;a-button type="primary" @click="handleSaveConfig" :loading="saving" :disabled="!sharingConfig.enabled"&gt;
                保存配置
              &lt;/a-button&gt;
              &lt;a-button @click="handleTestSharing" :loading="testing" :disabled="!sharingConfig.enabled"&gt;
                测试共享
              &lt;/a-button&gt;
            &lt;/a-space&gt;
          &lt;/a-form-item&gt;
        &lt;/a-form&gt;
      &lt;/div&gt;
      &lt;!-- 可用渠道 --&gt;
      &lt;div &gt;
        &lt;h3&gt;&lt;ApiOutlined /&gt; 可用渠道&lt;/h3&gt;
        &lt;a-list :data-source="availableChannels" size="small" bordered&gt;
          &lt;template #renderItem="{ item }"&gt;
            &lt;a-list-item&gt;
              &lt;a-list-item-meta :title="getChannelLabel(item)" :description="'渠道: ' + item"&gt;
                &lt;template #avatar&gt;
                  &lt;a-avatar :style="{ backgroundColor: getChannelColor(item) }"&gt;
                    {{ item[0].toUpperCase() }}
                  &lt;/a-avatar&gt;
                &lt;/template&gt;
              &lt;/a-list-item-meta&gt;
              &lt;template #actions&gt;
                &lt;a-tag :color="sharingConfig.shared_channels?.includes(item) ? 'green' : 'default'"&gt;
                  {{ sharingConfig.shared_channels?.includes(item) ? '已共享' : '未共享' }}
                &lt;/a-tag&gt;
              &lt;/template&gt;
            &lt;/a-list-item&gt;
          &lt;/template&gt;
        &lt;/a-list&gt;
      &lt;/div&gt;
      &lt;!-- 共享状态 --&gt;
      &lt;div &gt;
        &lt;h3&gt;&lt;InfoCircleOutlined /&gt; 共享状态&lt;/h3&gt;
        &lt;a-descriptions bordered :column="2" v-if="statusData"&gt;
          &lt;a-descriptions-item label="启用状态"&gt;
            &lt;a-tag :color="statusData.enabled ? 'green' : 'red'"&gt;
              {{ statusData.enabled ? '已启用' : '已禁用' }}
            &lt;/a-tag&gt;
          &lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="共享渠道数"&gt;{{ statusData.shared_channel_count || 0 }}&lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="上次更新时间"&gt;{{ statusData.last_updated || '-' }}&lt;/a-descriptions-item&gt;
          &lt;a-descriptions-item label="配置版本"&gt;{{ statusData.config_version || '-' }}&lt;/a-descriptions-item&gt;
        &lt;/a-descriptions&gt;
        &lt;a-empty v-else description="暂无状态数据" /&gt;
      &lt;/div&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  ShareAltOutlined,
  LinkOutlined,
  ApiOutlined,
  ReloadOutlined,
  SettingOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons-vue'
import { channelSharingAPI } from '@/api/modules/channel_sharing'
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const sharingConfig = reactive({
  enabled: false,
  description: '',
  shared_channels: [] as string[],
})
const availableChannels = ref&lt;string[]&gt;([])
interface StatusInfo {
  enabled?: boolean
  shared_channel_count?: number
  last_updated?: string
  config_version?: string
}
const statusData = ref&lt;StatusInfo | null&gt;(null)
const channelLabels: Record&lt;string, string&gt; = {
  feishu: '飞书',
  wechat: '微信',
  dingtalk: '钉钉',
  slack: 'Slack',
  discord: 'Discord',
  telegram: 'Telegram',
}
const channelColors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
function getChannelLabel(channel: string) {
  return channelLabels[channel] || channel
}
function getChannelColor(channel: string) {
  const index = availableChannels.value.indexOf(channel) % channelColors.length
  return channelColors[index]
}
async function loadConfig() {
  loading.value = true
  error.value = ''
  try {
    const [configRes, channelsRes, statusRes] = await Promise.all([
      channelSharingAPI.getConfig().catch(() =&gt; ({ data: null })),
      channelSharingAPI.getAvailableChannels().catch(() =&gt; ({ data: [] })),
      channelSharingAPI.getStatus().catch(() =&gt; ({ data: null })),
    ])
    if (configRes.data) {
      Object.assign(sharingConfig, {
        enabled: configRes.data.enabled || false,
        description: configRes.data.description || '',
        shared_channels: configRes.data.shared_channels || [],
      })
    }
    if (channelsRes.data) {
      availableChannels.value = Array.isArray(channelsRes.data) ? channelsRes.data : []
    }
    if (statusRes.data) {
      statusData.value = statusRes.data
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    error.value = err?.message || '加载配置失败'
  } finally {
    loading.value = false
  }
}
async function handleToggleSharing() {
  saving.value = true
  try {
    const api = sharingConfig.enabled ? channelSharingAPI.disable : channelSharingAPI.enable
    const res = await api()
    if (res.data?.success || res.data?.code === 0) {
      sharingConfig.enabled = !sharingConfig.enabled
      message.success(sharingConfig.enabled ? '已启用共享' : '已禁用共享')
      await loadConfig()
    } else {
      message.error(res.data?.message || '操作失败')
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    message.error(err?.message || '操作失败')
  } finally {
    saving.value = false
  }
}
async function handleSaveConfig() {
  saving.value = true
  try {
    const res = await channelSharingAPI.setChannels({
      channels: sharingConfig.shared_channels,
      description: sharingConfig.description,
    })
    if (res.data?.success || res.data?.code === 0) {
      message.success('配置已保存')
      await loadConfig()
    } else {
      message.error(res.data?.message || '保存失败')
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    message.error(err?.message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function handleTestSharing() {
  testing.value = true
  try {
    const res = await channelSharingAPI.test({
      channel: sharingConfig.shared_channels[0] || 'feishu',
      other_channels: sharingConfig.shared_channels.slice(1),
    })
    if (res.data?.success || res.data?.code === 0) {
      message.success('共享测试成功')
    } else {
      message.error(res.data?.message || '测试失败')
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    message.error(err?.message || '测试失败')
  } finally {
    testing.value = false
  }
}
onMounted(() =&gt; {
  loadConfig()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
}
.hd {
  padding: 14px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hd-actions {
  display: flex;
  gap: 8px;
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
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.s {
  padding: 20px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.s-icon {
  font-size: 2rem;
  color: #06b6d4;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section {
  padding: 20px;
  border-radius: 12px;
}
.section h3 {
  margin: 0 0 16px 0;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 8px;
}
&lt;/style&gt;
&nbsp;