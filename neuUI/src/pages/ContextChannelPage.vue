<template>
  <div >
    <div >
      <h2 ><ShareAltOutlined :style="{ color: '#06b6d4' }" /> 渠道上下文共享</h2>
      <div >
        <a-button @click="loadConfig" :loading="loading"><ReloadOutlined /> 刷新</a-button>
        <a-button type="primary" @click="handleToggleSharing" :loading="saving">
          {{ sharingConfig.enabled ? '禁用共享' : '启用共享' }}
        </a-button>
      </div>
    </div>
    <div >
      <div >
        <ShareAltOutlined  />
        <div >
          <div >{{ sharingConfig.enabled ? '已启用' : '已禁用' }}</div>
          <div >共享状态</div>
        </div>
      </div>
      <div >
        <LinkOutlined  />
        <div >
          <div >{{ sharingConfig.shared_channels?.length || 0 }}</div>
          <div >共享渠道数</div>
        </div>
      </div>
      <div >
        <ApiOutlined  />
        <div >
          <div >{{ availableChannels.length }}</div>
          <div >可用渠道</div>
        </div>
      </div>
    </div>
    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" style="margin-bottom: 16px" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <div v-if="!loading" >
      <!-- 共享配置 -->
      <div >
        <h3><SettingOutlined /> 共享配置</h3>
        <a-form layout="vertical" style="max-width: 600px">
          <a-form-item label="共享描述">
            <a-input v-model:value="sharingConfig.description" placeholder="输入共享配置描述" :disabled="!sharingConfig.enabled" />
          </a-form-item>
          <a-form-item label="共享渠道">
            <a-select
              v-model:value="sharingConfig.shared_channels"
              mode="multiple"
              placeholder="选择要共享的渠道"
              :disabled="!sharingConfig.enabled"
              style="width: 100%"
            >
              <a-select-option v-for="ch in availableChannels" :key="ch" :value="ch">
                {{ getChannelLabel(ch) }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item>
            <a-space>
              <a-button type="primary" @click="handleSaveConfig" :loading="saving" :disabled="!sharingConfig.enabled">
                保存配置
              </a-button>
              <a-button @click="handleTestSharing" :loading="testing" :disabled="!sharingConfig.enabled">
                测试共享
              </a-button>
            </a-space>
          </a-form-item>
        </a-form>
      </div>
      <!-- 可用渠道 -->
      <div >
        <h3><ApiOutlined /> 可用渠道</h3>
        <a-list :data-source="availableChannels" size="small" bordered>
          <template #renderItem="{ item }">
            <a-list-item>
              <a-list-item-meta :title="getChannelLabel(item)" :description="'渠道: ' + item">
                <template #avatar>
                  <a-avatar :style="{ backgroundColor: getChannelColor(item) }">
                    {{ item[0].toUpperCase() }}
                  </a-avatar>
                </template>
              </a-list-item-meta>
              <template #actions>
                <a-tag :color="sharingConfig.shared_channels?.includes(item) ? 'green' : 'default'">
                  {{ sharingConfig.shared_channels?.includes(item) ? '已共享' : '未共享' }}
                </a-tag>
              </template>
            </a-list-item>
          </template>
        </a-list>
      </div>
      <!-- 共享状态 -->
      <div >
        <h3><InfoCircleOutlined /> 共享状态</h3>
        <a-descriptions bordered :column="2" v-if="statusData">
          <a-descriptions-item label="启用状态">
            <a-tag :color="statusData.enabled ? 'green' : 'red'">
              {{ statusData.enabled ? '已启用' : '已禁用' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="共享渠道数">{{ statusData.shared_channel_count || 0 }}</a-descriptions-item>
          <a-descriptions-item label="上次更新时间">{{ statusData.last_updated || '-' }}</a-descriptions-item>
          <a-descriptions-item label="配置版本">{{ statusData.config_version || '-' }}</a-descriptions-item>
        </a-descriptions>
        <a-empty v-else description="暂无状态数据" />
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
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
const availableChannels = ref<string[]>([])
interface StatusInfo {
  enabled?: boolean
  shared_channel_count?: number
  last_updated?: string
  config_version?: string
}
const statusData = ref<StatusInfo | null>(null)
const channelLabels: Record<string, string> = {
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
      channelSharingAPI.getConfig().catch(() => ({ data: null })),
      channelSharingAPI.getAvailableChannels().catch(() => ({ data: [] })),
      channelSharingAPI.getStatus().catch(() => ({ data: null })),
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
onMounted(() => {
  loadConfig()
})
</script>
<style scoped>
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
</style>
 