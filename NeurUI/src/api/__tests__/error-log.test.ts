import { describe, expect, it, vi, beforeEach } from 'vitest'
import { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'

vi.mock('@/utils/logger', () => ({
  default: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))
vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn(() => null), set: vi.fn(), remove: vi.fn() },
}))

import logger from '@/utils/logger'
import { request } from '../index'

/** 用假 adapter 产出带真实 config 的 HTTP 状态错误（不依赖网络） */
function failWith(status: number): void {
  request.defaults.adapter = (cfg) =>
    Promise.reject(
      new AxiosError(
        `Request failed with status code ${status}`,
        AxiosError.ERR_BAD_REQUEST,
        cfg as never,
        null,
        { status, config: cfg, data: null, headers: {} } as unknown as AxiosResponse,
      ),
    )
}

describe('响应拦截器预期错误日志降级（2026-09-07 composition 404 噪音根治）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    failWith(404)
  })

  it('未声明预期 → 404 仍按 error 记录（真错误不失真）', async () => {
    await expect(request.get('/context/other')).rejects.toBeTruthy()
    expect(logger.error).toHaveBeenCalled()
  })

  it('声明 __expectedStatus=404 → 不刷 error，降级 debug', async () => {
    await expect(
      request.get('/context/composition', { __expectedStatus: 404 } as AxiosRequestConfig),
    ).rejects.toBeTruthy()
    expect(logger.error).not.toHaveBeenCalled()
    expect(logger.debug).toHaveBeenCalled()
  })
})
