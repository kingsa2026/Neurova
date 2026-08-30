<template>
  <a-drawer
    v-model:open="open"
    :title="t('canvas.storeTitle')"
    :width="560"
    @close="handleClose"
  >
    <div class="store-drawer">
      <!-- 店铺列表：按平台分组 -->
      <div v-if="stores.length === 0 && !loading" class="store-empty">
        <p>{{ t('canvas.storeEmpty') }}</p>
        <p class="store-empty-tip">{{ t('canvas.storeEmptyTip') }}</p>
      </div>
      <div v-else class="store-list">
        <div v-for="store in stores" :key="store.store_id" class="store-row">
          <div class="store-row-main">
            <div class="store-row-title">
              <span class="store-name">{{ store.store_name }}</span>
              <span class="store-badge" :class="`badge-${store.status ?? 'pending'}`">{{ store.status ?? 'pending' }}</span>
            </div>
            <div class="store-meta">
              {{ platformDisplayName(store.platform) }} · {{ store.app_key_masked || t('canvas.storeNoAppKey') }}
              <span v-if="store.last_error" class="store-error" :title="store.last_error">· {{ t('canvas.storeErrorTag') }}</span>
            </div>
          </div>
          <div class="store-row-actions">
            <a-button size="small" :loading="busy === store.store_id" @click="handleTest(store)">{{ t('canvas.storeTest') }}</a-button>
            <a-button size="small" :loading="busy === `${store.store_id}:refresh`" @click="handleRefresh(store)">{{ t('canvas.storeRefresh') }}</a-button>
            <a-popconfirm :title="t('canvas.storeDeleteConfirm')" @confirm="handleDelete(store)">
              <a-button size="small" danger>{{ t('canvas.storeDelete') }}</a-button>
            </a-popconfirm>
          </div>
        </div>
      </div>

      <a-divider>{{ t('canvas.storeConnectNew') }}</a-divider>

      <div class="store-form">
        <div class="form-row">
          <label>{{ t('canvas.storePlatform') }}</label>
          <a-select v-model:value="platform" :options="platformOptions" style="flex: 1" />
        </div>
        <div class="form-row">
          <label>{{ t('canvas.storeNameLabel') }}</label>
          <a-input v-model:value="storeName" :placeholder="t('canvas.storeNamePh')" />
        </div>
        <template v-if="platform">
          <div v-for="cred in credentialFields" :key="cred.key" class="form-row">
            <label :title="t(cred.hint)">{{ t(cred.label) }}</label>
            <a-input-password v-if="cred.secret" v-model:value="credentialDraft[cred.key]" :placeholder="t(cred.hint)" />
            <a-input v-else v-model:value="credentialDraft[cred.key]" :placeholder="t(cred.hint)" />
          </div>
        </template>
        <p v-if="admissionHint(platform)" class="store-admission">{{ admissionHint(platform) }}</p>
        <a-button type="primary" block :loading="submitting" :disabled="!platform || !storeName" @click="handleSubmit">
          {{ t('canvas.storeConnect') }}
        </a-button>
        <a-button v-if="oauthSupported" block class="oauth-btn" @click="handleOAuth">
          {{ t('canvas.oauthAuthorize') }}
        </a-button>
      </div>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
/**
 * 画布店铺管理抽屉（§6.2）
 *
 * 凭据字段按平台动态渲染（与 docs/neurflow-store-connection-design.md §2 表一一对应）；
 * 提交后自动触发一次连接测试；测试/刷新失败展示状态与错误摘要。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { uiMessage } from '@/utils/message'
import config from '@/config'
import {
  createStore,
  deleteStore,
  listStores,
  refreshStoreToken,
  testStoreConnection,
  type ConnectedStore,
} from '@/api/modules/neurflow'
import { PLATFORM_NAME_KEYS, platformDisplayName } from './canvasStores'

const { t } = useI18n()

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ changed: [] }>()

const stores = ref<ConnectedStore[]>([])
const loading = ref(false)
const busy = ref('')
const submitting = ref(false)

const platform = ref('')
const storeName = ref('')
const credentialDraft = ref<Record<string, string>>({})

interface CredField {
  key: string
  /** i18n key（canvas.label*） */
  label: string
  /** i18n key（canvas.cred*，"如何获取"要点） */
  hint: string
  secret?: boolean
  into?: 'credentials' | 'extra' | 'top'
}

/** 各平台凭据字段（§2 表对应；label/hint 均为 i18n key） */
const CRED_SCHEMAS: Record<string, CredField[]> = {
  amazon: [
    { key: 'client_id', label: 'canvas.labelLwaClientId', secret: true, hint: 'canvas.credAmazonClientId', into: 'credentials' },
    { key: 'client_secret', label: 'canvas.labelLwaClientSecret', secret: true, hint: 'canvas.credAmazonClientSecret', into: 'credentials' },
    { key: 'refresh_token', label: 'canvas.labelRefreshToken', secret: true, hint: 'canvas.credAmazonRefreshToken', into: 'credentials' },
    { key: 'marketplace_id', label: 'canvas.labelMarketplaceId', hint: 'canvas.credAmazonMarketplace', into: 'top' },
    { key: 'region', label: 'canvas.labelSpApiRegion', hint: 'canvas.credAmazonRegion', into: 'top' },
  ],
  taobao: [
    { key: 'app_key', label: 'canvas.labelAppKey', secret: true, hint: 'canvas.credTaobaoAppKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecret', secret: true, hint: 'canvas.credTaobaoAppSecret', into: 'credentials' },
    { key: 'session_key', label: 'canvas.labelSession', secret: true, hint: 'canvas.credTaobaoSession', into: 'credentials' },
  ],
  jd: [
    { key: 'app_key', label: 'canvas.labelAppKey', secret: true, hint: 'canvas.credJdKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecret', secret: true, hint: 'canvas.credJdKey', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelAccessToken', secret: true, hint: 'canvas.credJdAccessToken', into: 'credentials' },
  ],
  pdd: [
    { key: 'client_id', label: 'canvas.labelClientId', secret: true, hint: 'canvas.credPddClientId', into: 'credentials' },
    { key: 'client_secret', label: 'canvas.labelClientSecret', secret: true, hint: 'canvas.credPddSecret', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelAccessToken', secret: true, hint: 'canvas.credHintOAuth', into: 'credentials' },
  ],
  'douyin-ecom': [
    { key: 'app_key', label: 'canvas.labelAppKey', secret: true, hint: 'canvas.credDouyinAppKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecret', secret: true, hint: 'canvas.credDouyinSecret', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelShopAccessToken', secret: true, hint: 'canvas.credHintOAuth', into: 'credentials' },
  ],
  tiktok: [
    { key: 'app_key', label: 'canvas.labelAppKey', secret: true, hint: 'canvas.credTiktokKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecret', secret: true, hint: 'canvas.credTiktokKey', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelShopAccessToken', secret: true, hint: 'canvas.credTiktokAccessToken', into: 'credentials' },
    { key: 'shop_cipher', label: 'canvas.labelShopCipher', hint: 'canvas.credTiktokShopCipher', into: 'extra' },
  ],
  ali1688: [
    { key: 'app_key', label: 'canvas.labelAppKeyNoSpace', secret: true, hint: 'canvas.credAli1688AppKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecretNoSpace', secret: true, hint: 'canvas.credAli1688Secret', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelAccessToken', secret: true, hint: 'canvas.credAli1688AccessToken', into: 'credentials' },
  ],
  xiaohongshu: [
    { key: 'app_key', label: 'canvas.labelAppKeyNoSpace', secret: true, hint: 'canvas.credXhsAppKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelAppSecretNoSpace', secret: true, hint: 'canvas.credXhsSecret', into: 'credentials' },
    { key: 'access_token', label: 'canvas.labelAccessToken', secret: true, hint: 'canvas.credXhsAccessToken', into: 'credentials' },
  ],
  xianyu: [
    { key: 'app_key', label: 'canvas.labelTopAppKey', secret: true, hint: 'canvas.credXianyuAppKey', into: 'credentials' },
    { key: 'app_secret', label: 'canvas.labelTopAppSecret', secret: true, hint: 'canvas.credXianyuSecret', into: 'credentials' },
    { key: 'session', label: 'canvas.labelSession', secret: true, hint: 'canvas.credXianyuSession', into: 'credentials' },
  ],
}

function admissionHint(p: string): string {
  if (p === 'xiaohongshu') return t('canvas.admitXhs')
  if (p === 'xianyu') return t('canvas.admitXianyu')
  return ''
}

const credentialFields = computed<CredField[]>(() => CRED_SCHEMAS[platform.value] ?? [])

const platformOptions = computed(() =>
  Object.keys(PLATFORM_NAME_KEYS).map(value => ({ label: platformDisplayName(value), value })),
)

function resetForm(): void {
  platform.value = ''
  storeName.value = ''
  credentialDraft.value = {}
}

/** Tier 2 OAuth 支持平台（与后端 _OAUTH_SUPPORTED 对齐） */
const OAUTH_SUPPORTED = ['taobao', 'xianyu', 'jd', 'pdd', 'douyin-ecom', 'tiktok', 'ali1688', 'xiaohongshu']
const oauthSupported = computed(() => OAUTH_SUPPORTED.includes(platform.value))

function handleOAuth(): void {
  const creds = credentialFields.value.filter(f => f.into === 'credentials')
  const appKey = String(credentialDraft.value[creds.find(f => f.key.includes('key') || f.key === 'client_id')?.key ?? 'app_key'] ?? '')
  const appSecret = String(credentialDraft.value[creds.find(f => f.key.includes('secret') || f.key === 'client_secret')?.key ?? 'app_secret'] ?? '')
  if (!appKey || !appSecret) {
    uiMessage.warning(t('canvas.msgOAuthNeedCreds'))
    return
  }
  const params = new URLSearchParams({
    platform: platform.value,
    app_key: appKey,
    app_secret: appSecret,
    store_name: storeName.value || '',
  })
  window.open(`${config.apiBaseUrl}/neurflow/stores/oauth/authorize?${params.toString()}`, '_blank')
}

async function loadStores(): Promise<void> {
  loading.value = true
  try {
    stores.value = await listStores()
  } catch {
    stores.value = []
  } finally {
    loading.value = false
  }
}

watch(open, (v) => {
  if (v) void loadStores()
})

function handleClose(): void {
  open.value = false
}

async function handleSubmit(): Promise<void> {
  if (!platform.value || !storeName.value) return
  submitting.value = true
  try {
    const credentials: Record<string, string> = {}
    const extra: Record<string, unknown> = {}
    const top: Record<string, unknown> = {}
    for (const f of credentialFields.value) {
      const value = String(credentialDraft.value[f.key] ?? '').trim()
      if (!value) continue
      if (f.into === 'extra') extra[f.key] = value
      else if (f.into === 'top') top[f.key] = value
      else credentials[f.key] = value
    }
    const payload: Record<string, unknown> = {
      platform: platform.value,
      store_name: storeName.value,
      credentials,
      ...top,
    }
    if (Object.keys(extra).length > 0) payload.extra = extra
    const store = await createStore(payload)
    uiMessage.success(t('canvas.msgStoreConnected', { name: store.store_name }))
    const result = await testStoreConnection(store.store_id)
    if ((result as { status?: string }).status === 'active') {
      uiMessage.success(t('canvas.msgTestPassed'))
    } else {
      const reason = (result as { detail?: string }).detail ?? (result as { error?: string }).error ?? t('canvas.msgUnknownReason')
      uiMessage.warning(t('canvas.msgTestFailed', { reason }))
    }
    resetForm()
    await loadStores()
    emit('changed')
  } catch (err) {
    uiMessage.error(t('canvas.msgConnectFailed', { err: String(err) }))
  } finally {
    submitting.value = false
  }
}

async function handleTest(store: ConnectedStore): Promise<void> {
  busy.value = store.store_id
  try {
    const result = await testStoreConnection(store.store_id)
    if ((result as { status?: string }).status === 'active') uiMessage.success(t('canvas.msgStoreActive', { name: store.store_name }))
    else uiMessage.warning(t('canvas.msgStoreTestFailed', { name: store.store_name, reason: (result as { detail?: string }).detail ?? '' }))
    await loadStores()
    emit('changed')
  } catch (err) {
    uiMessage.error(String(err))
  } finally {
    busy.value = ''
  }
}

async function handleRefresh(store: ConnectedStore): Promise<void> {
  busy.value = `${store.store_id}:refresh`
  try {
    const result = await refreshStoreToken(store.store_id)
    if ((result as { status?: string }).status === 'active') uiMessage.success(t('canvas.msgTokenRefreshed', { name: store.store_name }))
    else uiMessage.warning(t('canvas.msgRefreshFailed', { reason: (result as { detail?: string }).detail ?? '' }))
    await loadStores()
    emit('changed')
  } catch (err) {
    uiMessage.error(String(err))
  } finally {
    busy.value = ''
  }
}

async function handleDelete(store: ConnectedStore): Promise<void> {
  try {
    await deleteStore(store.store_id)
    uiMessage.success(t('canvas.msgStoreDeleted', { name: store.store_name }))
    await loadStores()
    emit('changed')
  } catch (err) {
    uiMessage.error(String(err))
  }
}
</script>

<style scoped>
.store-drawer { display: flex; flex-direction: column; gap: 8px; }
.store-empty { text-align: center; color: var(--nr-text-secondary, rgba(255, 255, 255, 0.55)); padding: 12px 0; }
.store-empty-tip { font-size: 12px; margin-top: 4px; }
.store-list { display: flex; flex-direction: column; gap: 8px; }
.store-row {
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 8px 10px; border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08)); border-radius: 6px;
}
.store-row-title { display: flex; align-items: center; gap: 8px; }
.store-name { font-weight: 500; }
.store-badge { font-size: 12px; padding: 0 6px; border-radius: 8px; }
.badge-active { background: rgba(82, 196, 26, 0.15); color: #52c41a; }
.badge-error { background: rgba(255, 77, 79, 0.15); color: #ff4d4f; }
.badge-expired, .badge-pending { background: rgba(250, 173, 20, 0.15); color: #faad14; }
.store-meta { font-size: 12px; color: var(--nr-text-secondary, rgba(255, 255, 255, 0.55)); margin-top: 2px; }
.store-error { color: #ff4d4f; }
.store-row-actions { display: flex; gap: 6px; flex-shrink: 0; }
.store-form { display: flex; flex-direction: column; gap: 10px; }
.form-row { display: flex; align-items: center; gap: 10px; }
.form-row label { width: 120px; flex-shrink: 0; font-size: 13px; text-align: right; }
.store-admission { font-size: 12px; color: #faad14; margin: 0; }
</style>
