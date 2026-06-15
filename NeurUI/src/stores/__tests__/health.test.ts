import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useHealthStore } from '@/stores/health'

vi.mock('@/api/modules/health', () => ({
  getHealthStatus: vi.fn(),
  getHealthChecks: vi.fn(),
  getHealthReport: vi.fn(),
}))

import { getHealthStatus, getHealthChecks, getHealthReport } from '@/api/modules/health'

describe('useHealthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts with null status', () => {
    const store = useHealthStore()
    expect(store.status).toBe(null)
    expect(store.isHealthy).toBe(false)
    expect(store.overallStatus).toBe('unknown')
  })

  it('fetchStatus populates status', async () => {
    vi.mocked(getHealthStatus).mockResolvedValue({
      data: { status: 'healthy', version: '1.0', uptime_seconds: 100, timestamp: '2024-01-01' },
    } as any)

    const store = useHealthStore()
    await store.fetchStatus()

    expect(store.status?.status).toBe('healthy')
    expect(store.isHealthy).toBe(true)
    expect(store.lastUpdated).not.toBeNull()
  })

  it('fetchChecks populates checks', async () => {
    vi.mocked(getHealthChecks).mockResolvedValue({
      data: [{ name: 'db', status: 'ok', message: '' }],
    } as any)

    const store = useHealthStore()
    await store.fetchChecks()

    expect(store.checks).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  it('fetchReport populates all fields', async () => {
    vi.mocked(getHealthReport).mockResolvedValue({
      data: {
        overall: 'degraded',
        version: '2.0',
        timestamp: '2024-01-01',
        checks: [{ name: 'api', status: 'warn' }],
      },
    } as any)

    const store = useHealthStore()
    await store.fetchReport()

    expect(store.status?.status).toBe('degraded')
    expect(store.isDegraded).toBe(true)
    expect(store.checks).toHaveLength(1)
  })

  it('handles fetchStatus errors gracefully', async () => {
    vi.mocked(getHealthStatus).mockRejectedValue(new Error('network'))

    const store = useHealthStore()
    await store.fetchStatus()

    expect(store.status).toBe(null)
  })
})
