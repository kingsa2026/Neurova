/**
 * EnterpriseSourcesPage — U-conn 连接器扩展批契约测试（8 个新 kind 的向导适配）。
 *
 * 代表形态四家（覆盖三种凭据形态与可选字段语义）：
 * - bigquery：湖仓 SQL REST 组——base_url＋credential_env 单 env 指针＋project_id/query 必填、watermark_column 可选；
 * - cassandra：NoSQL 组——contact_points/keyspace/table/cql 全必填＋credentialEnv 对象（username/password 两个 env 名）；
 * - looker：SaaS REST 组——base_url/query_id＋credentialEnv 对象（client_id/client_secret）；
 * - git：代码仓组——仅 repo_url 必填，branch/file_glob 可选、credentialEnv 可选（公共仓免凭据，不落空对象）。
 *
 * 另覆盖：步 0 分组渲染（5 组 17 卡）、其余四家（databricks/salesforce/servicenow/airflow）
 * 的专属字段出现、列表类型标签对新增 sourceType 的本地化回显。
 * 描述符字段名与后端（connectors_saas.py / connectors_nosql.py / connectors_git.py）逐字对齐。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__enterpriseSourcesAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__enterpriseSourcesAuthUser
    },
  }),
}))

vi.mock('@/api/modules/ontology', () => ({
  listEnterpriseSources: vi.fn(),
  submitEnterpriseSource: vi.fn(),
  triggerEnterpriseIngest: vi.fn(),
  getEnterpriseSourceHealth: vi.fn(),
  deleteEnterpriseSource: vi.fn(),
  triggerEnterpriseMedia: vi.fn(),
  listCatalogTables: vi.fn(),
  getCatalogTableDetail: vi.fn(),
  refreshSourceCatalog: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import EnterpriseSourcesPage from '@/pages/EnterpriseSourcesPage.vue'
import { submitEnterpriseSource } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const submitMock = submitEnterpriseSource as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { edit: '编辑', delete: '删除', prev: '上一步', next: '下一步', save: '保存', cancel: '取消', yes: '是', no: '否', error: '操作失败', success: '成功' },
    },
  },
})

/** a-table stub：列表页仅用于类型标签回显断言 */
const tableStub = {
  props: ['dataSource'],
  template: `<div class="stub-table">
    <div v-for="row in dataSource || []" :key="row.source_id" class="stub-row">
      <span class="cell-type"><slot name="bodyCell" :column="{ key: 'type' }" :record="row" /></span>
      <span class="cell-actions"><slot name="bodyCell" :column="{ key: 'actions' }" :record="row" /></span>
    </div>
    <div v-if="!(dataSource || []).length" class="stub-table-empty" />
  </div>`,
}

const stubs = {
  'a-table': tableStub,
  'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="stub-badge">{{ text }}</span>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-modal': { props: ['open', 'title'], template: '<div v-if="open" class="stub-modal"><slot /><slot name="footer" /></div>' },
  'a-steps': { props: ['current'], template: '<div class="stub-steps" :data-current="current"><slot /></div>' },
  'a-step': { props: ['title'], template: '<div class="stub-step">{{ title }}</div>' },
  'a-form': { template: '<form class="stub-form"><slot /></form>' },
  'a-form-item': { props: ['label'], template: '<label class="stub-form-item"><slot /></label>' },
  'a-input': {
    props: ['value', 'disabled', 'placeholder'],
    emits: ['update:value'],
    template: '<input class="stub-input" :value="value" :data-placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  'a-textarea': {
    props: ['value', 'rows', 'placeholder'],
    emits: ['update:value'],
    template: '<textarea class="stub-textarea" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  'a-select': {
    props: ['value', 'options', 'placeholder'],
    emits: ['update:value'],
    template: `<select class="stub-select" :value="value" @change="$emit('update:value', $event.target.value)">
      <option v-for="o in options || []" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>`,
  },
  'a-radio-group': {
    props: ['value'],
    emits: ['update:value'],
    template: `<select class="stub-radio" :value="value" @change="$emit('update:value', $event.target.value)"><slot /></select>`,
  },
  'a-radio': { props: ['value'], template: '<option :value="value"><slot /></option>' },
  'a-switch': {
    props: ['checked', 'disabled', 'size'],
    emits: ['change'],
    template: '<button class="stub-switch" :disabled="disabled" @click="$emit(\'change\', !checked)" />',
  },
  'a-popconfirm': {
    props: ['title'],
    template: '<span class="stub-pop"><button class="pop-confirm-btn" @click="$emit(\'confirm\')"><slot /></button></span>',
  },
  'a-row': { template: '<div class="stub-row-el"><slot /></div>' },
  'a-col': { template: '<div class="stub-col"><slot /></div>' },
  'a-drawer': { props: ['open', 'title'], template: '<div v-if="open" class="stub-drawer"><slot /></div>' },
  'a-spin': { props: ['spinning'], template: '<div class="stub-spin"><slot /></div>' },
  'a-divider': { template: '<div class="stub-divider"><slot /></div>' },
  'a-descriptions': { template: '<div class="stub-desc"><slot /></div>' },
  'a-descriptions-item': { props: ['label'], template: '<div class="stub-desc-item"><slot /></div>' },
  GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
  GlassButton: {
    props: ['loading', 'disabled', 'variant'],
    emits: ['click'],
    template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
}

const mountPage = () =>
  mount(EnterpriseSourcesPage, {
    global: { plugins: [i18n], stubs },
    attachTo: document.body,
  })

const nextBtn = (wrapper: ReturnType<typeof mountPage>) =>
  wrapper.find('[data-testid="ent-wizard-next"]').element as HTMLButtonElement

/** 按卡名文本选步 0 连接对象卡（匹配 kind-name 精确文本，不依赖卡序；卡 desc 可能含他卡同名厂商字样） */
async function selectKind(wrapper: ReturnType<typeof mountPage>, label: string) {
  const card = wrapper.findAll('.kind-card').find((c) => c.find('.kind-name').text() === label)
  expect(card, `kind card: ${label}`).toBeTruthy()
  await card!.trigger('click')
}

/** 按 data-testid 填向导输入框（存在性一并断言） */
async function fill(wrapper: ReturnType<typeof mountPage>, testid: string, value: string) {
  const el = wrapper.find(`[data-testid="${testid}"]`)
  expect(el.exists(), `field: ${testid}`).toBe(true)
  await el.setValue(value)
}

/** 走完步 2 字段映射与步 3 保存 */
async function fillMappingAndSave(wrapper: ReturnType<typeof mountPage>) {
  const inputs = wrapper.find('.stub-modal').findAll('.stub-input')
  await inputs[0].setValue('order_id, status') // columns
  await inputs[1].setValue('order_id') // subject column
  await inputs[2].setValue('has_status') // predicate
  await inputs[3].setValue('status') // object value
  await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
  await wrapper.find('[data-testid="ent-wizard-save"]').trigger('click')
  await flushPromises()
}

function sourceRow(overrides: Record<string, unknown> = {}) {
  return {
    source_id: 'src',
    descriptor: { sourceType: 'sql', columns: ['order_id'] },
    cursor: '',
    enabled: false,
    adapter_registered: false,
    created_at: '2026-11-23T10:00:00',
    updated_at: '2026-11-23T10:00:00',
    ingested_count: 0,
    ...overrides,
  }
}

beforeEach(() => {
  submitMock.mockReset()
  submitMock.mockResolvedValue({ code: 0, message: 'ok', data: sourceRow() })
  authUser.role = 'admin'
})

describe('EnterpriseSourcesPage（U-conn 扩展：步 0 分组选型）', () => {
  it('连接对象卡按 5 个连接器族分组展示，共 17 张卡', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    const titles = wrapper.findAll('.kind-group-title').map((n) => n.text())
    expect(titles).toEqual(['核心源型', '湖仓 / SQL REST', 'NoSQL', 'SaaS REST', '代码仓'])
    expect(wrapper.findAll('.kind-card').length).toBe(17)
  })

  it('列表类型标签：新增 sourceType 走本地化标签（bigquery/git 抽查）', async () => {
    const { listEnterpriseSources } = await import('@/api/modules/ontology')
    ;(listEnterpriseSources as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: 0,
      data: {
        items: [
          sourceRow({ source_id: 'bq_src', descriptor: { sourceType: 'bigquery', columns: [] } }),
          sourceRow({ source_id: 'git_src', descriptor: { sourceType: 'git', columns: [] } }),
        ],
        total: 2,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    const rows = wrapper.findAll('.stub-row')
    expect(rows[0].find('.cell-type').text()).toContain('BigQuery')
    expect(rows[1].find('.cell-type').text()).toContain('Git 仓库')
  })
})

describe('EnterpriseSourcesPage（U-conn 扩展：bigquery 湖仓 SQL REST）', () => {
  it('字段出现＋必填守门＋描述符逐字对齐（credential_env 单指针、watermark_column 可选）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, 'BigQuery')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    // 专属字段齐备
    for (const tid of ['ent-base-url', 'ent-cred-env', 'ent-bq-project', 'ent-sql-rest-query', 'ent-bq-watermark']) {
      expect(wrapper.find(`[data-testid="${tid}"]`).exists(), tid).toBe(true)
    }
    // 必填守门：source_id/base_url/凭据指针/project_id/query 未齐 → 下一步禁用
    await fill(wrapper, 'ent-wizard-source-id', 'bq_src')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-base-url', 'https://bigquery.googleapis.com')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cred-env', 'NEUROVA_BQ_TOKEN')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-bq-project', 'neurova-prod')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-sql-rest-query', 'SELECT order_id, status FROM orders')
    expect(nextBtn(wrapper).disabled).toBe(false)
    // 可选字段：水位列
    await fill(wrapper, 'ent-bq-watermark', 'updated_at')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    await fillMappingAndSave(wrapper)

    expect(submitMock).toHaveBeenCalledTimes(1)
    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor).toMatchObject({
      sourceType: 'bigquery',
      base_url: 'https://bigquery.googleapis.com',
      credential_env: 'NEUROVA_BQ_TOKEN',
      project_id: 'neurova-prod',
      query: 'SELECT order_id, status FROM orders',
      watermark_column: 'updated_at',
    })
  })
})

describe('EnterpriseSourcesPage（U-conn 扩展：cassandra NoSQL）', () => {
  it('字段出现＋全字段必填＋credentialEnv 对象双指针（username/password 两个 env 名）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, 'Cassandra')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    for (const tid of ['ent-cassandra-contact-points', 'ent-cassandra-keyspace', 'ent-cassandra-table', 'ent-cassandra-cql', 'ent-cred-user', 'ent-cred-password']) {
      expect(wrapper.find(`[data-testid="${tid}"]`).exists(), tid).toBe(true)
    }
    await fill(wrapper, 'ent-wizard-source-id', 'cass_src')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cassandra-contact-points', '10.0.0.1,10.0.0.2')
    await fill(wrapper, 'ent-cassandra-keyspace', 'shop')
    await fill(wrapper, 'ent-cassandra-table', 'orders')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cassandra-cql', 'SELECT order_id, status FROM orders')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cred-user', 'NEUROVA_CASS_USER')
    await fill(wrapper, 'ent-cred-password', 'NEUROVA_CASS_PASS')
    expect(nextBtn(wrapper).disabled).toBe(false)
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    await fillMappingAndSave(wrapper)

    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor).toMatchObject({
      sourceType: 'cassandra',
      contact_points: '10.0.0.1,10.0.0.2',
      keyspace: 'shop',
      table: 'orders',
      cql: 'SELECT order_id, status FROM orders',
      credentialEnv: { username: 'NEUROVA_CASS_USER', password: 'NEUROVA_CASS_PASS' },
    })
  })
})

describe('EnterpriseSourcesPage（U-conn 扩展：looker SaaS REST）', () => {
  it('字段出现＋必填守门＋credentialEnv 对象（client_id/client_secret）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, 'Looker')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    for (const tid of ['ent-base-url', 'ent-looker-query-id', 'ent-cred-client-id', 'ent-cred-client-secret']) {
      expect(wrapper.find(`[data-testid="${tid}"]`).exists(), tid).toBe(true)
    }
    await fill(wrapper, 'ent-wizard-source-id', 'looker_src')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-base-url', 'https://example.looker.com')
    await fill(wrapper, 'ent-looker-query-id', '42')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cred-client-id', 'NEUROVA_LOOKER_ID')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-cred-client-secret', 'NEUROVA_LOOKER_SECRET')
    expect(nextBtn(wrapper).disabled).toBe(false)
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    await fillMappingAndSave(wrapper)

    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor).toMatchObject({
      sourceType: 'looker',
      base_url: 'https://example.looker.com',
      query_id: '42',
      credentialEnv: { client_id: 'NEUROVA_LOOKER_ID', client_secret: 'NEUROVA_LOOKER_SECRET' },
    })
  })
})

describe('EnterpriseSourcesPage（U-conn 扩展：git 代码仓）', () => {
  it('仅 repo_url 必填（公共仓免凭据）：branch/file_glob 可选落键、credentialEnv 不落空对象', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, 'Git 仓库')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    for (const tid of ['ent-git-repo-url', 'ent-git-branch', 'ent-git-file-glob', 'ent-cred-user', 'ent-cred-token']) {
      expect(wrapper.find(`[data-testid="${tid}"]`).exists(), tid).toBe(true)
    }
    await fill(wrapper, 'ent-wizard-source-id', 'git_src')
    expect(nextBtn(wrapper).disabled).toBe(true)
    await fill(wrapper, 'ent-git-repo-url', 'https://github.com/example/repo.git')
    // 凭据留空即可放行（公共仓免凭据）
    expect(nextBtn(wrapper).disabled).toBe(false)
    await fill(wrapper, 'ent-git-branch', 'main')
    await fill(wrapper, 'ent-git-file-glob', 'docs/**/*.md')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    await fillMappingAndSave(wrapper)

    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor).toMatchObject({
      sourceType: 'git',
      repo_url: 'https://github.com/example/repo.git',
      branch: 'main',
      file_glob: 'docs/**/*.md',
    })
    expect(body.descriptor.credentialEnv).toBeUndefined()
  })

  it('私有仓：username/token 两个 env 指针填入后落 credentialEnv 对象', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, 'Git 仓库')
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    await fill(wrapper, 'ent-wizard-source-id', 'git_priv')
    await fill(wrapper, 'ent-git-repo-url', 'https://github.com/example/private.git')
    await fill(wrapper, 'ent-cred-user', 'NEUROVA_GIT_USER')
    await fill(wrapper, 'ent-cred-token', 'NEUROVA_GIT_TOKEN')
    expect(nextBtn(wrapper).disabled).toBe(false)
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')

    await fillMappingAndSave(wrapper)

    const body = submitMock.mock.calls[0][0]
    expect(body.descriptor.credentialEnv).toEqual({ username: 'NEUROVA_GIT_USER', token: 'NEUROVA_GIT_TOKEN' })
  })
})

describe('EnterpriseSourcesPage（U-conn 扩展：其余四家字段出现）', () => {
  it.each([
    ['Databricks', ['ent-base-url', 'ent-db-warehouse', 'ent-sql-rest-query', 'ent-cred-env']],
    ['Salesforce', ['ent-base-url', 'ent-soql', 'ent-cred-env']],
    ['ServiceNow', ['ent-base-url', 'ent-sn-table', 'ent-sn-query', 'ent-cred-user', 'ent-cred-password']],
    ['Airflow', ['ent-base-url', 'ent-airflow-dag', 'ent-cred-user', 'ent-cred-password']],
  ])('%s 向导步 1 专属字段齐备', async (label, testids) => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="ent-add-btn"]').trigger('click')
    await selectKind(wrapper, label as string)
    await wrapper.find('[data-testid="ent-wizard-next"]').trigger('click')
    for (const tid of testids as string[]) {
      expect(wrapper.find(`[data-testid="${tid}"]`).exists(), `${label}: ${tid}`).toBe(true)
    }
  })
})
