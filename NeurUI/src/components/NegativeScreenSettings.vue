<template>
  <div class="negative-screen-settings">
    <GlassCard :title="t('negativeScreen.title')">
      <a-form layout="vertical" :model="config">
        <!-- 启用开关 -->
        <a-form-item :label="t('negativeScreen.enable')">
          <a-switch v-model:checked="config.enabled" />
          <span class="hint">{{ t('negativeScreen.enableHint') }}</span>
        </a-form-item>

        <!-- Auth Code -->
        <a-form-item :label="t('negativeScreen.authCode')">
          <a-input-password
            v-model:value="config.auth_code"
            :placeholder="t('negativeScreen.authCodePlaceholder')"
            :disabled="!config.enabled"
          >
            <template #prefix>
              <LockOutlined />
            </template>
          </a-input-password>
          <div class="auth-code-hint">
            <p>{{ t('negativeScreen.getAuthCodeSteps') }}</p>
            <ol>
              <li>{{ t('negativeScreen.step1') }}</li>
              <li>{{ t('negativeScreen.step2') }}</li>
              <li>{{ t('negativeScreen.step3') }}</li>
            </ol>
          </div>
        </a-form-item>

        <!-- 推送 URL -->
        <a-form-item :label="t('negativeScreen.pushUrl')">
          <a-input
            v-model:value="config.push_url"
            :placeholder="t('negativeScreen.pushUrlPlaceholder')"
            :disabled="!config.enabled"
          />
          <span class="hint">{{ t('negativeScreen.pushUrlHint') }}</span>
        </a-form-item>

        <!-- 测试推送 -->
        <a-form-item>
          <div class="test-section">
            <GlassButton
              variant="secondary"
              size="sm"
              :loading="testing"
              :disabled="!config.enabled || !config.auth_code"
              @click="testPush"
            >
              {{ t('negativeScreen.testPush') }}
            </GlassButton>
            <span v-if="testResult" :class="['test-result', testResult.success ? 'success' : 'error']">
              {{ testResult.success ? t('negativeScreen.testSuccess') : t('negativeScreen.testFailed') + testResult.error }}
            </span>
          </div>
        </a-form-item>
      </a-form>

      <template #footer>
        <div class="footer-actions">
          <GlassButton
            variant="primary"
            size="sm"
            :loading="saving"
            @click="saveConfig"
          >
            {{ t('common.save') }}
          </GlassButton>
          <GlassButton
            variant="danger"
            size="sm"
            :loading="deleting"
            @click="deleteConfig"
          >
            {{ t('negativeScreen.deleteConfig') }}
          </GlassButton>
        </div>
      </template>
    </GlassCard>

    <!-- 推送统计 -->
    <GlassCard :title="t('negativeScreen.statsTitle')" class="stats-card">
      <a-descriptions :column="2" bordered size="small">
        <a-descriptions-item :label="t('negativeScreen.totalNotifications')">
          {{ statistics.total_task_notifications || 0 }}
        </a-descriptions-item>
        <a-descriptions-item :label="t('negativeScreen.pushedCount')">
          {{ statistics.pushed_to_negative_screen || 0 }}
        </a-descriptions-item>
        <a-descriptions-item :label="t('negativeScreen.failedCount')">
          {{ statistics.push_failed || 0 }}
        </a-descriptions-item>
        <a-descriptions-item :label="t('negativeScreen.successRate')">
          {{ ((statistics.push_rate || 0) * 100).toFixed(1) }}%
        </a-descriptions-item>
      </a-descriptions>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { LockOutlined } from '@ant-design/icons-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

// 配置数据
const config = ref({
  auth_code: '',
  enabled: false,
  push_url: 'https://hiboard-claw-drcn.ai.dbankcloud.cn/distribution/message/cloud/claw/msg/upload'
})

// 统计数据
const statistics = ref({
  total_task_notifications: 0,
  pushed_to_negative_screen: 0,
  push_failed: 0,
  push_rate: 0
})

// 状态
const saving = ref(false)
const deleting = ref(false)
const testing = ref(false)
const testResult = ref<{ success: boolean; error?: string } | null>(null)

// 加载配置
const loadConfig = async () => {
  try {
    const res: any = await request.get('/negative-screen')
    const data = res?.data ?? res ?? {}
    
    if (data.auth_code) {
      config.value.auth_code = data.auth_code
    }
    if (data.enabled !== undefined) {
      config.value.enabled = data.enabled
    }
    if (data.push_url) {
      config.value.push_url = data.push_url
    }
  } catch (error) {
    console.error('加载负一屏配置失败:', error)
  }
}

// 加载统计
const loadStatistics = async () => {
  try {
    const res: any = await request.get('/notifications/push-statistics')
    const data = res?.data ?? res ?? {}
    statistics.value = data
  } catch (error) {
    console.error('加载推送统计失败:', error)
  }
}

// 保存配置
const saveConfig = async () => {
  saving.value = true
  try {
    await request.put('/negative-screen', config.value)
    message.success(t('negativeScreen.configSaved'))
  } catch (error) {
    message.error(t('negativeScreen.saveFailed'))
    console.error('保存负一屏配置失败:', error)
  } finally {
    saving.value = false
  }
}

// 删除配置
const deleteConfig = async () => {
  deleting.value = true
  try {
    await request.delete('/negative-screen')
    config.value = {
      auth_code: '',
      enabled: false,
      push_url: 'https://hiboard-claw-drcn.ai.dbankcloud.cn/distribution/message/cloud/claw/msg/upload'
    }
    message.success(t('negativeScreen.configDeleted'))
  } catch (error) {
    message.error(t('negativeScreen.deleteFailed'))
    console.error('删除负一屏配置失败:', error)
  } finally {
    deleting.value = false
  }
}

// 测试推送
const testPush = async () => {
  testing.value = true
  testResult.value = null
  
  try {
    const res: any = await request.post('/negative-screen/test', {
      task_name: '测试推送',
      task_content: '## 测试内容\n\n这是一条来自 Neurova 的测试推送消息。\n\n**时间**: ' + new Date().toLocaleString(),
      task_result: '测试完成'
    })
    
    const data = res?.data ?? res ?? {}
    testResult.value = {
      success: data.success || false,
      error: data.error
    }
    
    if (data.success) {
      message.success(t('negativeScreen.testPushSuccess'))
    } else {
      message.error(t('negativeScreen.testPushFailed') + ': ' + (data.error || t('negativeScreen.unknownError')))
    }
  } catch (error: any) {
    testResult.value = {
      success: false,
      error: error.message || t('negativeScreen.networkError')
    }
    message.error(t('negativeScreen.testPushFailed'))
  } finally {
    testing.value = false
  }
}

// 组件挂载时加载数据
onMounted(() => {
  loadConfig()
  loadStatistics()
})
</script>

<style scoped>
.negative-screen-settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.hint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
  margin-left: 8px;
}

.auth-code-hint {
  margin-top: 8px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  font-size: 13px;
}

.auth-code-hint p {
  margin: 0 0 8px 0;
  color: rgba(255, 255, 255, 0.7);
}

.auth-code-hint ol {
  margin: 0;
  padding-left: 20px;
  color: rgba(255, 255, 255, 0.6);
}

.auth-code-hint li {
  margin-bottom: 4px;
}

.test-section {
  display: flex;
  align-items: center;
  gap: 12px;
}

.test-result {
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 4px;
}

.test-result.success {
  color: #52c41a;
  background: rgba(82, 196, 26, 0.1);
}

.test-result.error {
  color: #ff4d4f;
  background: rgba(255, 77, 79, 0.1);
}

.footer-actions {
  display: flex;
  gap: 8px;
}

.stats-card {
  margin-top: 16px;
}
</style>
